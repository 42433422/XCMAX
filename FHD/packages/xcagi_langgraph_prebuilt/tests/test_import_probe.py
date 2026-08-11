"""XCAGI vendored langgraph-prebuilt 导入探针测试 (LG-W0-05).

核对任务要求的可导入符号:
  - ToolNode / ToolRuntime / tools_condition / ValidationNode / create_react_agent
  - 中断相关类型 (HumanInterrupt / HumanResponse / ActionRequest / HumanInterruptConfig / Command / interrupt)

本测试在包本地 locked uv 环境运行（`uv run --locked pytest`），依赖经 [tool.uv.sources]
映射到 vendored 兄弟包安装。为防「空载通过」，本测试:
  - 不修改 sys.path，不依赖 PYTHONPATH / LANGGRAPH_CORE_SRC；
  - 不做任何 pytest.skip；
  - 断言每个导入模块的源码文件位于 FHD/packages 下的 vendored 包内（而非 PyPI 上游）。
"""
from __future__ import annotations

import inspect
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent          # packages/xcagi_langgraph_prebuilt
PACKAGES_ROOT = PKG.parent  # FHD/packages/


def _assert_vendored(module: object, expected_subdir: str) -> None:
    """断言模块源码文件位于 FHD/packages/<expected_subdir> 下（vendored，非 PyPI 上游）。"""
    file = Path(getattr(module, "__file__", "") or "")
    assert file.is_absolute(), f"{module.__name__} 无 __file__，疑似命名空间占位"
    resolved = file.resolve()
    assert resolved.is_relative_to(PACKAGES_ROOT), (
        f"{module.__name__} 源码 ({resolved}) 不在 FHD/packages 下"
        f"，可能来自 PyPI 上游而非 vendored 兄弟包"
    )
    assert expected_subdir in resolved.parts, (
        f"{module.__name__} 源码 ({resolved}) 不在期望的 vendored 包 {expected_subdir} 下"
    )


def test_toolnode_and_condition_importable() -> None:
    from langgraph.prebuilt import ToolNode, ToolRuntime, tools_condition

    assert issubclass(ToolNode, object)
    assert issubclass(ToolRuntime, object)
    assert callable(tools_condition)


def test_validation_node_importable() -> None:
    from langgraph.prebuilt import ValidationNode

    assert issubclass(ValidationNode, object)


def test_create_react_agent_unwrapped() -> None:
    from langgraph.prebuilt import create_react_agent

    # inspect.unwrap 穿透缓存/装饰器包装，返回底层可调用对象
    fn = inspect.unwrap(create_react_agent)
    assert callable(fn)


def test_interrupt_types_importable() -> None:
    from langgraph.prebuilt.interrupt import (
        ActionRequest,
        HumanInterrupt,
        HumanInterruptConfig,
        HumanResponse,
    )
    from langgraph.types import Command, interrupt

    for sym in (HumanInterrupt, HumanResponse, ActionRequest, HumanInterruptConfig, Command):
        assert isinstance(sym, type)
    assert callable(interrupt)


def test_dependencies_resolve_to_vendored_siblings() -> None:
    """断言本包与各兄弟依赖均来自 FHD/packages 下的 vendored 副本（非 PyPI 上游）。"""
    import langgraph.checkpoint.base
    import langgraph.checkpoint.postgres
    import langgraph.checkpoint.sqlite
    import langgraph.prebuilt
    import langgraph.types

    _assert_vendored(langgraph.prebuilt, "xcagi_langgraph_prebuilt")
    _assert_vendored(langgraph.types, "xcagi_langgraph_core")
    _assert_vendored(langgraph.checkpoint.base, "xcagi_langgraph_checkpoint")
    _assert_vendored(langgraph.checkpoint.sqlite, "xcagi_langgraph_checkpoint_backends")
    _assert_vendored(langgraph.checkpoint.postgres, "xcagi_langgraph_checkpoint_backends")