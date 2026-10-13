"""Canonical hashing of content payloads and manifests (D23; contracts/v1/README "Canonical hashing").

SHA-256 over the RFC 8785 (JCS) bytes, written `sha256:<hex>`. Before hashing, non-integer numbers, integers beyond
plus or minus 2^53 - 1 and text or keys not in Unicode NFC are refused, so the Python backend and the TypeScript web
app always agree (the same rules as scripts/contract_tools.py, kept identical by a test against the shared vectors).
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

import rfc8785

SAFE_INTEGER = 2**53 - 1


class CanonicalError(ValueError):
    pass


def _check(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            raise CanonicalError(f"{path}: integer outside the safe range")
        return
    if isinstance(value, float):
        raise CanonicalError(f"{path}: non-integer numbers are not allowed in hashed content")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            raise CanonicalError(f"{path}: text is not in Unicode NFC form")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or unicodedata.normalize("NFC", key) != key:
                raise CanonicalError(f"{path}: object keys must be NFC strings")
            _check(item, f"{path}.{key}")
        return
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    _check(value)
    return rfc8785.dumps(value)


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def nfc(value: Any) -> Any:
    """The same structure with every string in NFC (text from sources and editors may arrive decomposed)."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [nfc(v) for v in value]
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", k): nfc(v) for k, v in value.items()}
    return value
