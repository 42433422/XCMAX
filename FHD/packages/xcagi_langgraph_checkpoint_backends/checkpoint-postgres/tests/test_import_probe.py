"""XCAGI vendored langgraph-checkpoint-postgres 导入探针测试 (LG-W0-04).

核对任务要求的可导入符号:
  - PostgresSaver (checkpoint/postgres)
  - PostgresStore (store/postgres)

这些符号依赖兄弟包 langgraph-checkpoint 提供的命名空间 `langgraph.checkpoint` / `langgraph.store`，故本测试
同时把 vendored 兄弟包源码目录加入 sys.path 后导入。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent  # packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres

# 兄弟包 langgraph-checkpoint（提供 langgraph.checkpoint / langgraph.store 命名空间）
CHECKPOINT_SIBLING = PKG.parent.parent / "xcagi_langgraph_checkpoint"


@pytest.fixture(scope="module", autouse=True)
def _backends_on_path() -> None:
    for p in (PKG, CHECKPOINT_SIBLING):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def test_postgres_saver_importable() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    assert issubclass(PostgresSaver, object)


def test_postgres_async_saver_importable() -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    assert issubclass(AsyncPostgresSaver, object)


def test_postgres_store_importable() -> None:
    from langgraph.store.postgres import PostgresStore

    assert issubclass(PostgresStore, object)