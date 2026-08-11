"""LG-W0-07｜上游 LangGraph 语义探针（vendored 1.2.10）.

在 FHD 侧验证 vendored 上游 `langgraph`（tag 1.2.10、锁定 commit
`41341457342327166d72fc11952ab28fb61ec0bf`）的核心图语义，作为后续
NeuroBus 引擎吸收状态机/并行/流式/Checkpoint 原语的行为基线。

运行环境约束（与 W0-06/W0-08 一致）：

  - **无 sys.path 变异、无 PYTHONPATH**：本文件不做任何 `sys.path` 注入；
  - 运行于**包本地锁定 uv 环境**（vendored 兄弟包以 editable 方式安装，
    模块路径解析到 `FHD/packages/xcagi*`）:
      * `xcagi_langgraph_core`       → `langgraph.graph`（`StateGraph`）
      * `xcagi_langgraph_checkpoint` → `langgraph.checkpoint.memory`（`InMemorySaver`）
      * `xcagi_langgraph_prebuilt`   → `langgraph.prebuilt`（`ToolNode` 等）
  - **fail-closed**：探针断言上述模块源文件路径解析在 `FHD/packages/xcagi*`
    目录内；任一 sibling 缺失或解析到 site-packages 时，顶层导入或路径断言
    直接失败，绝不静默跳过。

覆盖能力（确定性语义）：

  - 有类型状态 + reducer（`Annotated[list, operator.add]`）；
  - 条件边路由（`add_conditional_edges(START, ...)`）；
  - 并行扇出 / superstep（多节点同一步写共享 key，经 reducer 合并）；
  - 屏障合并（join）；
  - 子图（subgraph）作为节点接入；
  - 流式事件（`stream` 按节点产出）；
  - Checkpoint（`InMemorySaver` + `get_state_history` 回放）。

本文件同时作为可执行脚本与 pytest 用例使用。
"""

from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

__all__ = [
    "State",
    "VENDORED_PACKAGES_ROOT",
    "build_semantic_graph",
    "run_probe",
    "regenerate_fixture",
    "FIXTURE_PATH",
]

TAG = "1.2.10"
COMMIT = "41341457342327166d72fc11952ab28fb61ec0bf"

# FHD/packages 根目录：用于断言 vendored 兄弟包模块路径解析位置。
_FHD = Path(__file__).resolve().parents[2]
VENDORED_PACKAGES_ROOT = _FHD / "packages"

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PATH = _FIXTURE_DIR / "upstream_graph_1_2_10.json"


class State(TypedDict, total=False):
    """探针图状态：reducer 共享 key + 条件路由 key + 子图累加。"""

    log: Annotated[list[str], operator.add]
    route: str
    total: Annotated[int, operator.add]
    sub_total: int


class SubState(TypedDict, total=False):
    """子图独立状态：与父图隔离，避免子图节点触发父图 superstep 重跑。"""

    total: int
    sub_total: int


# ---------------------------------------------------------------------------
# fail-closed：vendored 源码路径断言
# ---------------------------------------------------------------------------
def assert_vendored_sources() -> dict[str, str]:
    """断言 core/checkpoint/prebuilt 模块解析在 FHD/packages/xcagi* 内。

    返回仓库相对路径（确定性，供 fixture 记录）。任一缺失即失败（fail-closed）。
    """
    import langgraph.checkpoint.memory as _mem
    import langgraph.graph.state as _core
    import langgraph.prebuilt as _pb

    actual = {
        "core.graph": _core.__file__,
        "checkpoint.memory": _mem.__file__,
        "prebuilt": _pb.__file__,
    }
    root_str = str(VENDORED_PACKAGES_ROOT.resolve())
    reported: dict[str, str] = {}
    for name, path in actual.items():
        resolved = Path(path).resolve()
        assert root_str in str(resolved), f"{name} 未解析到 FHD/packages（fail-closed）: {resolved}"
        assert "xcagi_langgraph" in str(resolved) or "checkpoint-" in str(resolved), resolved
        reported[name] = str(resolved.relative_to(_FHD))
    return reported


def assert_prebuilt_importable() -> dict[str, bool]:
    """验证 vendored prebuilt 工具层可导入且符号可用。"""
    from langgraph.prebuilt import ToolNode, create_react_agent, tools_condition

    result = {
        "ToolNode": callable(ToolNode),
        "tools_condition": callable(tools_condition),
        "create_react_agent": callable(create_react_agent),
    }
    assert all(result.values()), result
    return result


# ---------------------------------------------------------------------------
# 语义图构造
# ---------------------------------------------------------------------------
def _set_fast(state: State) -> dict:
    return {"log": ["fast"]}


def _set_slow(state: State) -> dict:
    return {"log": ["slow"]}


def _pa(state: State) -> dict:
    return {"log": ["pa"], "total": 1}


def _pb(state: State) -> dict:
    return {"log": ["pb"], "total": 2}


def _pc(state: State) -> dict:
    return {"log": ["pc"], "total": 3}


def _join(state: State) -> dict:
    return {"log": ["join"]}


def _route(state: State) -> str:
    return "fast" if state.get("route") == "fast" else "slow"


def _sub_double(state: SubState) -> dict:
    return {"sub_total": (state.get("total", 0) or 0) * 2}


def _build_subgraph():
    """独立状态子图：读取 total 并翻倍写入 sub_total（与父图通道隔离）。"""
    sub = StateGraph(SubState)
    sub.add_node("double", _sub_double)
    sub.add_edge(START, "double")
    sub.add_edge("double", END)
    return sub.compile()


def _sub_node(state: State) -> dict:
    """父图节点：运行编译子图并按父图 key 回写结果。"""
    out = _build_subgraph().invoke({"total": state.get("total", 0)})
    return {"sub_total": out.get("sub_total")}


def build_semantic_graph(checkpointer=None):
    """构造覆盖全部语义的图：

    START →(条件边)→ {fast|slow} →(并行扇出)→ {pa,pb,pc} → join → sub(子图) → END
    """
    builder = StateGraph(State)
    builder.add_node("n_fast", _set_fast)
    builder.add_node("n_slow", _set_slow)
    builder.add_node("pa", _pa)
    builder.add_node("pb", _pb)
    builder.add_node("pc", _pc)
    builder.add_node("join", _join)
    builder.add_node("sub", _sub_node)

    builder.add_conditional_edges(START, _route, {"fast": "n_fast", "slow": "n_slow"})
    builder.add_edge("n_fast", "pa")
    builder.add_edge("n_fast", "pb")
    builder.add_edge("n_fast", "pc")
    builder.add_edge("n_slow", "pa")
    builder.add_edge("n_slow", "pb")
    builder.add_edge("n_slow", "pc")
    builder.add_edge("pa", "join")
    builder.add_edge("pb", "join")
    builder.add_edge("pc", "join")
    builder.add_edge("join", "sub")
    builder.add_edge("sub", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


# ---------------------------------------------------------------------------
# 确定性语义探针
# ---------------------------------------------------------------------------
def run_probe() -> dict:
    """执行探针并返回确定性结果（无绝对路径 / 无时间戳 / 无随机 ID）。"""
    sources = assert_vendored_sources()
    prebuilt = assert_prebuilt_importable()

    # 每个语义片段使用独立 thread_id，避免 count-parallel 状态下跨调用累积
    graph_invoke = build_semantic_graph()
    cfg_invoke = {"configurable": {"thread_id": "lg-w0-07-invoke"}}
    result = graph_invoke.invoke({"log": [], "route": "fast", "total": 0}, cfg_invoke)

    graph_stream = build_semantic_graph()
    cfg_stream = {"configurable": {"thread_id": "lg-w0-07-stream"}}
    stream_nodes: set[str] = set()
    for item in graph_stream.stream({"log": [], "route": "slow", "total": 0}, cfg_stream):
        chunk = item[1] if isinstance(item, tuple) and len(item) == 2 else item
        if isinstance(chunk, dict):
            # updates 模式下 chunk 为 {node_name: update}
            for name in chunk:
                if isinstance(name, str):
                    stream_nodes.add(name)

    graph_ck = build_semantic_graph()
    cfg_ck = {"configurable": {"thread_id": "lg-w0-07-checkpoint"}}
    graph_ck.invoke({"log": [], "route": "fast", "total": 0}, cfg_ck)
    history = list(graph_ck.get_state_history(cfg_ck))
    history_count = len(history)
    latest = history[0].values if history else {}
    latest_log = sorted(latest.get("log", [])) if history else []

    probe = {
        "file": "tests/langgraph_absorption/upstream_graph_probe.py",
        "graph": "START ->(route)-> {fast|slow} ->(fanout)-> {pa,pb,pc} -> join -> sub(subgraph) -> END",
        "state": "State(log: Annotated[list, operator.add], route: str, total: Annotated[int, operator.add], sub_total: int)",
        "checkpointer": "langgraph.checkpoint.memory.InMemorySaver",
    }
    return {
        "spec": "LG-W0-07",
        "spec_title": "upstream langgraph graph semantic probe",
        "tag": TAG,
        "commit": COMMIT,
        "target": "packages/xcagi_langgraph_core (vendored) / xcagi_langgraph_checkpoint / xcagi_langgraph_prebuilt",
        "probe": probe,
        "vendored_sources": sources,
        "prebuilt": prebuilt,
        "semantics": {
            "conditional_route_fast": sorted(result.get("log", [])),
            "fanout_total": result.get("total"),
            "subgraph_sub_total": result.get("sub_total"),
            "streaming_node_count": len(stream_nodes),
            "streaming_nodes": sorted(stream_nodes),
            "checkpoint_count": history_count,
            "checkpoint_latest_log": latest_log,
        },
    }


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def regenerate_fixture() -> Path:
    """把探针结果写入 fixture（幂等：重复调用字节恒等）。"""
    _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(_canonical_json(run_probe()), encoding="utf-8")
    return FIXTURE_PATH


def main() -> None:
    print("vendored module paths:")
    for name, rel in assert_vendored_sources().items():
        print(f"  {name}: {rel}")
    print("prebuilt symbols:")
    for name, ok in assert_prebuilt_importable().items():
        print(f"  {name}: {ok}")

    payload = run_probe()
    print(json.dumps(payload["semantics"], ensure_ascii=False, sort_keys=True))
    regen = regenerate_fixture()
    print(f"fixture written: {regen}")
    print("LG-W0-07 UPSTREAM GRAPH SEMANTIC PROBE PASSED")


# ---------------------------------------------------------------------------
# pytest 用例（确定性；fixture 字节恒等）
# ---------------------------------------------------------------------------
def test_vendored_sources_and_prebuilt() -> None:
    sources = assert_vendored_sources()
    assert set(sources) == {"core.graph", "checkpoint.memory", "prebuilt"}
    assert assert_prebuilt_importable()["ToolNode"] is True


def test_conditional_route_and_fanout_superstep() -> None:
    graph = build_semantic_graph()
    cfg = {"configurable": {"thread_id": "lg-w0-07-t-cond"}}
    result = graph.invoke({"log": [], "route": "fast", "total": 0}, cfg)
    assert sorted(result["log"]) == ["fast", "join", "pa", "pb", "pc"]
    # 并行扇出 superstep 经 reducer 合并：total == 1+2+3
    assert result["total"] == 6


def test_subgraph_uses_parent_state() -> None:
    graph = build_semantic_graph()
    cfg = {"configurable": {"thread_id": "lg-w0-07-t-sub"}}
    result = graph.invoke({"log": [], "route": "slow", "total": 0}, cfg)
    # 子图读到父图 total=6 并翻倍
    assert result["sub_total"] == 12


def test_streaming_emits_node_events() -> None:
    graph = build_semantic_graph()
    cfg = {"configurable": {"thread_id": "lg-w0-07-t-stream"}}
    stream_nodes: set[str] = set()
    for item in graph.stream({"log": [], "route": "slow", "total": 0}, cfg):
        chunk = item[1] if isinstance(item, tuple) and len(item) == 2 else item
        if isinstance(chunk, dict):
            for name in chunk:
                if isinstance(name, str):
                    stream_nodes.add(name)
    assert {"join", "sub"} <= stream_nodes


def test_checkpoint_replay() -> None:
    graph = build_semantic_graph()
    config = {"configurable": {"thread_id": "lg-w0-07-semantic-ck"}}
    graph.invoke({"log": [], "route": "fast", "total": 0}, config)
    history = list(graph.get_state_history(config))
    assert len(history) >= 1
    assert sorted(history[0].values.get("log", [])) == ["fast", "join", "pa", "pb", "pc"]


def test_fixture_is_stable_and_deterministic() -> None:
    first = run_probe()
    second = run_probe()
    assert first == second
    assert _canonical_json(first) == _canonial_json_of_file()
    # 重新生成后字节恒等
    regen = regenerate_fixture()
    assert regen.read_bytes() == _canonical_json(first).encode("utf-8")


def _canonial_json_of_file() -> str:
    if not FIXTURE_PATH.exists():
        return ""
    return FIXTURE_PATH.read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
