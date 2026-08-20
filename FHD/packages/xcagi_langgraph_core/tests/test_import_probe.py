"""XCAGI vendored langgraph 核心包 导入与功能探针测试 (LG-W0-02).

核对:
  - 模块来源：`langgraph.graph` / `langgraph.checkpoint.serde` / `langgraph.prebuilt`
    必须从仓库内 XCAGI 兄弟包路径解析（非 PyPI），见 test_module_files_resolve_under_xcagi_packages。
  - 功能：`from langgraph.graph import StateGraph` 且 build/compile/invoke 全流程可执行。

说明: 本测试不修改 sys.path / PYTHONPATH，仅在「本包锁定 uv 环境」(uv run --locked) 中运行；
包依赖由 [tool.uv.sources] 指向的 XCAGI 兄弟包以可编辑方式安装，因此模块文件落在仓库内
FHD/packages/ 之下。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import langgraph.checkpoint.serde  # noqa: F401
import langgraph.prebuilt  # noqa: F401
from typing_extensions import TypedDict

import langgraph.graph  # noqa: F401
from langgraph.graph import END, START, StateGraph

HERE = Path(__file__).resolve().parent
PKG = HERE.parent  # packages/xcagi_langgraph_core
PACKAGES = PKG.parent  # FHD/packages/  (XCAGI 兄弟包根)


def _file(mod: Any, name: str) -> Path:
    f = getattr(mod, "__file__", None)
    assert f, f"{name} 应为常规子包（含 __init__.py），但 __file__ 为空"
    return Path(f).resolve()


def test_module_files_resolve_under_xcagi_packages() -> None:
    core = _file(langgraph.graph, "langgraph.graph")
    checkpoint = _file(langgraph.checkpoint.serde, "langgraph.checkpoint.serde")
    prebuilt = _file(langgraph.prebuilt, "langgraph.prebuilt")

    print(f"langgraph.graph            -> {core}")
    print(f"langgraph.checkpoint.serde -> {checkpoint}")
    print(f"langgraph.prebuilt         -> {prebuilt}")

    assert core.is_relative_to(PACKAGES), core
    assert checkpoint.is_relative_to(PACKAGES), checkpoint
    assert prebuilt.is_relative_to(PACKAGES), prebuilt

    assert "xcagi_langgraph_core" in core.parts, core
    assert "xcagi_langgraph_checkpoint" in checkpoint.parts, checkpoint
    assert "xcagi_langgraph_prebuilt" in prebuilt.parts, prebuilt


def test_stategraph_importable() -> None:
    assert issubclass(StateGraph, object)
    assert START is not None
    assert END is not None


def test_stategraph_build_compile_invoke() -> None:
    class State(TypedDict):
        x: int

    def inc(s: State) -> State:
        return {"x": s["x"] + 1}

    g = StateGraph(State)
    g.add_node("inc", inc)
    g.add_edge(START, "inc")
    g.add_edge("inc", END)
    app = g.compile()
    result = app.invoke({"x": 0})

    assert result["x"] == 1


def test_stategraph_async_invoke() -> None:
    class State(TypedDict):
        total: int

    async def add_one(s: State) -> State:
        return {"total": s["total"] + 1}

    g = StateGraph(State)
    g.add_node("add", add_one)
    g.add_edge(START, "add")
    g.add_edge("add", END)
    app = g.compile()

    result = asyncio.run(app.ainvoke({"total": 5}))
    assert result["total"] == 6
