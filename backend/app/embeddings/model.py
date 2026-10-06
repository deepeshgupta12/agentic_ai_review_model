"""bge-m3 dense embeddings on the CPU (Step 07.4; D50, D51). Only the embedder image imports this module.

The model is BAAI/bge-m3 as int8 ONNX (the Xenova export, pinned to one commit, with both files checked against
their SHA-256), run with onnxruntime and the model's own tokenizer: no torch. Dense vectors use CLS pooling and L2
normalisation, as the model card says, so the dot product of two vectors is their cosine similarity. bge-m3 needs no
query instruction. Texts are cut at EMBEDDING_MAX_TOKENS tokens.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)
TOKENIZER_FILE = "tokenizer.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class ModelFiles:
    onnx: Path
    tokenizer: Path


def fetch_model(settings: Settings) -> ModelFiles:
    """Download the pinned files once into the models volume and check their hashes."""
    from huggingface_hub import hf_hub_download

    files = {}
    for name, expected in (
        (settings.embedding_file, settings.embedding_sha256),
        (TOKENIZER_FILE, settings.embedding_tokenizer_sha256),
    ):
        path = Path(
            hf_hub_download(
                settings.embedding_model,
                name,
                revision=settings.embedding_revision,
                cache_dir=str(settings.embedding_models_dir),
            )
        )
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeError(f"{name}: SHA-256 {actual} does not match the pinned {expected}")
        files[name] = path
    return ModelFiles(files[settings.embedding_file], files[TOKENIZER_FILE])


class Bgem3:
    def __init__(self, files: ModelFiles, *, max_tokens: int, threads: int) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(files.tokenizer))
        self.tokenizer.enable_truncation(max_length=max_tokens)
        pad = "<pad>"
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id(pad) or 1, pad_token=pad)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False  # memory goes back after a large batch
        self.session = ort.InferenceSession(str(files.onnx), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str]) -> Any:
        """L2-normalised CLS vectors, one row per text (float32)."""
        import numpy as np

        encoded = self.tokenizer.encode_batch(texts)
        feed = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        }
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        hidden = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})[0]
        cls = hidden[:, 0, :].astype(np.float32)
        return cls / np.maximum(np.linalg.norm(cls, axis=1, keepdims=True), 1e-12)
