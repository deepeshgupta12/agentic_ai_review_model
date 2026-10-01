"""Text normalisation and near-duplicate measures for origin clustering (Step 07.3).

Normalised text keeps letters, combining marks and digits of every script (Devanagari included) and drops case,
URLs, punctuation and spacing differences, so a copied post matches its copy. Near-duplicates are judged on word
shingles: MinHash signatures with banded locality-sensitive hashing find candidate pairs, and the exact Jaccard
similarity of their shingle sets decides. Deterministic: the hash functions are fixed, so the same texts always
cluster the same way.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

URL = re.compile(r"https?://\S+|www\.\S+")
THOUSANDS = re.compile(r"(?<=\d),(?=\d)")
DECIMAL = re.compile(r"(?<=\d)\.(?=\d)")
SHINGLE = 5
PERMUTATIONS = 128
BANDS = 32  # 32 bands of 4 rows: pairs with Jaccard around 0.5 and above become candidates
MERSENNE = (1 << 61) - 1


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode()).digest()[:8], "big") % MERSENNE


_SEEDS = [(_seed(f"a{i}") or 1, _seed(f"b{i}")) for i in range(PERMUTATIONS)]


def normalise(text: str) -> str:
    """Keeps letters, combining marks and digits of every script. Python's \\w would drop Devanagari vowel signs
    and split "कीमत" into "क मत"; a decimal point is kept inside a number ("1.75" stays one token)."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = THOUSANDS.sub("", URL.sub(" ", text))
    text = DECIMAL.sub("\u2024", text)  # one dot leader: kept below as part of the number
    kept = (ch if unicodedata.category(ch)[0] in "LMN" or ch == "\u2024" else " " for ch in text)
    return " ".join("".join(kept).split()).replace("\u2024", ".")


def normalised_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def words(text: str) -> list[str]:
    return normalise(text).split()


def shingles(text: str, size: int = SHINGLE) -> set[int]:
    tokens = words(text)
    if len(tokens) < size:
        return {_hash(" ".join(tokens))} if tokens else set()
    return {_hash(" ".join(tokens[i : i + size])) for i in range(len(tokens) - size + 1)}


def _hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def minhash(items: set[int]) -> list[int]:
    if not items:
        return []
    return [min((a * x + b) % MERSENNE for x in items) for a, b in _SEEDS]


def bands(signature: list[int]) -> list[tuple[int, tuple[int, ...]]]:
    rows = PERMUTATIONS // BANDS
    return [(band, tuple(signature[band * rows : (band + 1) * rows])) for band in range(BANDS)] if signature else []


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(small: set[int], large: set[int]) -> float:
    """How much of the smaller text appears in the larger one (a copied passage inside a longer page)."""
    if not small or not large:
        return 0.0
    return len(small & large) / len(small)
