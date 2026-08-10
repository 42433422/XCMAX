"""XCAGI vendored langgraph-checkpoint-sqlite 导入探针测试 (LG-W0-04).

核对任务要求的可导入符号:
  - SqliteSaver (checkpoint/sqlite)
  - AsyncSqliteSaver (checkpoint/sqlite/aio)
  - SqliteStore (store/sqlite)

本测试不使用 sys.path / PYTHONPATH 注入：运行环境必须是本包经 `uv run --locked` 的锁定安装
（含 `[tool.uv.sources]` 重定向到的兄弟包 xcagi_langgraph_checkpoint）。每个被测符号都会断言
其模块文件路径位于 FHD/packages 下的 vendored 包内，证明解析来自本地吸收副本而非任意 PYTHONPATH。
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

# FHD/packages 根目录（vendor 包全部位于其下）
# 本文件位于 FHD/packages/xcagi_langgraph_checkpoint_backends/<pkg>/tests/，parents[3] 即 FHD/packages
PACKAGES_ROOT = Path(__file__).resolve().parents[3]


def _assert_under_packages(mod: object, expected_prefixes: tuple[str, ...]) -> Path:
    """断言模块文件路径位于 FHD/packages 下，且属于预期 vendored 子包前缀之一。"""
    path = Path(inspect.getfile(mod)).resolve()
    root = str(PACKAGES_ROOT.resolve())
    if not str(path).startswith(root):
        pytest.fail(f"模块不在 FHD/packages 下: {path}")
    rel = str(path.relative_to(Path(root)))
    if not rel.startswith(expected_prefixes):
        pytest.fail(f"模块来源不符合 vendored 包预期 {expected_prefixes}: {rel}")
    return path


def test_sqlite_saver_importable() -> None:
    mod = importlib.import_module("langgraph.checkpoint.sqlite")
    assert hasattr(mod, "SqliteSaver")
    _assert_under_packages(mod, ("xcagi_langgraph_checkpoint_backends",))


def test_sqlite_async_saver_importable() -> None:
    mod = importlib.import_module("langgraph.checkpoint.sqlite.aio")
    assert hasattr(mod, "AsyncSqliteSaver")
    _assert_under_packages(mod, ("xcagi_langgraph_checkpoint_backends",))


def test_sqlite_store_importable() -> None:
    mod = importlib.import_module("langgraph.store.sqlite")
    assert hasattr(mod, "SqliteStore")
    _assert_under_packages(mod, ("xcagi_langgraph_checkpoint_backends",))


def test_checkpoint_sibling_under_packages() -> None:
    """兄弟包 langgraph-checkpoint 亦须来自 FHD/packages（重定向安装），且位于 xcagi_langgraph_checkpoint。"""
    mod = importlib.import_module("langgraph.checkpoint.base")
    _assert_under_packages(mod, ("xcagi_langgraph_checkpoint",))
