"""XCAGI vendored langgraph-checkpoint 导入探针测试 (LG-W0-03).

从 **uv 安装的包**（langgraph-checkpoint 4.1.1，经 `uv run --locked` 运行）导入真实公开符号，
**不做任何 sys.path / PYTHONPATH 注入**，以此证明已安装包可被正常导入使用。

核对任务要求的可导入公开符号:
  - BaseCheckpointSaver   (langgraph.checkpoint.base)
  - SerializerProtocol    (langgraph.checkpoint.serde.base)
  - JsonPlusSerializer    (langgraph.checkpoint.serde.jsonplus)
  - InMemorySaver         (langgraph.checkpoint.memory)
  - BaseStore             (langgraph.store.base)
"""

from __future__ import annotations

import pytest


def test_base_checkpoint_saver_importable() -> None:
    from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint

    assert issubclass(BaseCheckpointSaver, object)
    assert empty_checkpoint()["v"] == 2


def test_serializer_protocol_importable() -> None:
    from langgraph.checkpoint.serde.base import (
        SerializerProtocol,
        maybe_add_typed_methods,
    )

    assert SerializerProtocol is not None
    assert maybe_add_typed_methods is not None


def test_jsonplus_serializer_importable() -> None:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    assert issubclass(JsonPlusSerializer, object)
    s = JsonPlusSerializer()
    typ, blob = s.dumps_typed({"a": [1, 2, 3]})
    assert isinstance(blob, bytes) and len(blob) > 0
    assert s.loads_typed((typ, blob)) == {"a": [1, 2, 3]}


def test_inmemory_saver_importable() -> None:
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.memory import InMemorySaver

    assert issubclass(InMemorySaver, object)
    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    out = saver.put(cfg, empty_checkpoint(), {"source": "input", "step": -1}, {})
    assert saver.get_tuple(out) is not None


def test_base_store_importable() -> None:
    from langgraph.store.base import BaseStore

    assert issubclass(BaseStore, object)


@pytest.mark.parametrize(
    "modpath",
    [
        "langgraph.checkpoint.base",
        "langgraph.checkpoint.memory",
        "langgraph.checkpoint.serde.base",
        "langgraph.checkpoint.serde.jsonplus",
        "langgraph.store.base",
    ],
)
def test_no_path_injection_installed_import(modpath: str) -> None:
    """各公开符号所属模块均可从已安装包导入（不注入路径）。"""
    import importlib

    importlib.import_module(modpath)
