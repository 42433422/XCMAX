"""XCAGI vendored langgraph 核心包 导入与功能探针测试 (LG-W0-02).

核对任务要求的可导入/可运行符号:
  - from langgraph.graph import StateGraph
  - 图 build / compile / invoke 全流程可执行

`langgraph` 为核心包，本测试将其源码目录加入 sys.path 后直接导入（独立于 FHD 业务环境）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent  # packages/xcagi_langgraph_core


@pytest.fixture(scope="module", autouse=True)
def _core_on_path() -> None:
    pkg = str(PKG)
    if pkg not in sys.path:
        sys.path.insert(0, pkg)


def test_stategraph_importable() -> None:
    from langgraph.graph import END, START, StateGraph

    assert issubclass(StateGraph, object)
    assert START is not None
    assert END is not None


def test_stategraph_build_compile_invoke() -> None:
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

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
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class State(TypedDict):
        total: int

    async def add_one(s: State) -> State:
        return {"total": s["total"] + 1}

    g = StateGraph(State)
    g.add_node("add", add_one)
    g.add_edge(START, "add")
    g.add_edge("add", END)
    app = g.compile()

    import asyncio

    result = asyncio.run(app.ainvoke({"total": 5}))
    assert result["total"] == 6
