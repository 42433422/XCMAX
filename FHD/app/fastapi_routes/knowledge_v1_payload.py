"""Knowledge payload sanitizers (extracted for source-governance)."""

from __future__ import annotations

import json
from typing import Any

_DATASET_METADATA_MAX_BYTES = 64 * 1024


def _ensure_bounded_metadata(value: Any, *, max_bytes: int = _DATASET_METADATA_MAX_BYTES) -> None:
    def walk(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise ValueError("metadata nesting exceeds 8 levels")
        if isinstance(item, dict):
            if len(item) > 200:
                raise ValueError("metadata has too many fields")
            for key, child in item.items():
                if len(str(key)) > 200:
                    raise ValueError("metadata key is too long")
                walk(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            if len(item) > 1000:
                raise ValueError("metadata list is too long")
            for child in item:
                walk(child, depth + 1)

    walk(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"metadata cannot exceed {max_bytes} bytes")


def _public_dataset_payload(value: Any) -> Any:
    """Remove local storage details from HTTP responses without changing service internals."""

    if isinstance(value, dict):
        return {
            str(key): _public_dataset_payload(item)
            for key, item in value.items()
            if not str(key).startswith("_")
            and str(key) not in {"storage_path", "file_path", "vector_index_path"}
        }
    if isinstance(value, list):
        return [_public_dataset_payload(item) for item in value]
    return value
