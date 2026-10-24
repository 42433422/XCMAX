"""Keep private storage details out of knowledge HTTP payloads."""

from __future__ import annotations

from typing import Any


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
