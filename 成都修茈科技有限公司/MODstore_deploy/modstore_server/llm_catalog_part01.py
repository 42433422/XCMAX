# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_catalog")


def clear_all_catalog_cache() -> None:
    """BYOK 变更后丢弃进程内模型列表缓存。"""
    _facade()._cache.clear()
