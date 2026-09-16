"""Audio processing stubs — conversion, mixing, normalization."""
from __future__ import annotations


def normalize_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in ("-", "_", ".")).strip() or "recording"
