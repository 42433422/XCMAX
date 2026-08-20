# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.public_visualization_api")


def clear_public_visualization_cache() -> None:
    """Clear the per-process cache; exposed for tests and controlled reloads."""
    global _CACHE_VALUE, _CACHE_CREATED_MONOTONIC
    with _facade()._CACHE_LOCK:
        _facade()._CACHE_VALUE = None
        _facade()._CACHE_CREATED_MONOTONIC = 0.0
