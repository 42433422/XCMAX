"""LG-W0-07｜上游 graph 探针（upstream graph probe）— 多包综合版.

任务：在 FHD 侧验证 vendored 上游 `langgraph`（tag 1.2.10、锁定 commit
`41341457342327166d72fc11952ab28fb61ec0bf`）的『图编排』能力，作为后续
NeuroBus 引擎吸收图状态 / 条件路由 / 并行扇出 / 子图组合的行为基线。
本探针同时串联 3 个 vendored 兄弟包，证明其可协同导入：

  - `xcagi_langgraph_core`         → `langgraph.graph` / `langgraph.types` / `langgraph.constants`
  - `xcagi_langgraph_checkpoint`   → `langgraph.checkpoint.memory`（`InMemorySaver`）
  - `xcagi_langgraph_prebuilt`     → `langgraph.prebuilt`（`ToolNode` / `tools_condition` / `create_react_agent`）

覆盖能力（对应 `XCAGI/kb/absorption/langgraph/absorption_tasks.json`）：

  - 有类型状态 + reducer 合并语义（Typed State + Reducer，lg-absorb-01）
  - 条件路由（Conditional Edges，lg-absorb-02）
  - 确定性并行扇出 + 屏障合并（Parallel Fanout / superstep，lg-absorb-03）
  - checkpoint 断点持久化（lg-absorb-04）
  - 流式状态事件（Streaming state events，lg-absorb-06）
  - 子图组合（Subgraph composition，lg-absorb-08）

运行环境约束：在**干净独立 venv**（核心包 `uv sync` 生成的 vendored 环境）中运行；
不依赖 site-packages 原版、不写入 /tmp、不读取 PYTHONPATH。仅做源码导入锁定，
不产生任何临时目录。本文件同时作为可执行脚本与 pytest 用例使用。
"""

from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, TypedDict

# 显式注入 FHD/packages 下 vendored 兄弟包到 sys.path（置于最前，优先于站点包），
# 保证探针针对锁定 commit 的 vendored 上游副本，而非 PyPI 原版。
_PACKAGES = Path(__file__).resolve().parents[2] / "packages"
_VENDORED_SRC = [
    _PACKAGES / "xcagi_langgraph_core",
    _PACKAGES / "xcagi_langgraph_checkpoint",
    _PACKAGES / "xcagi_langgraph_prebuilt",
]
for _src in _VENDORED_SRC:
    _p = str(_src.resolve())
    if _p not in sys.path:
        sys.path.insert(0, _p)

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph

__all__ = [
    "State",
    "build_upstream_graph",
    "build_counter_subgraph",
    "check_prebuilt",
]


class State(TypedDict):
    """父图状态：`log` 用 `operator.add` 作 reducer（追加合并，非覆盖）；
    `sub_total` 为子图隔离字段，仅子图内部读写。"""

    log: Annotated[list[str], operator.add]
    route: str
    sub_total: int


def _node_start(state: State) -> dict:
    # 仅追加日志，保留调用方传入的路由（route 由条件路由函数读取）
    return {"log": ["start"]}


def _node_pa(state: State) -> dict:
    return {"log": ["pa"]}


def _node_pb(state: State) -> dict:
    return {"log": ["pb"]}


def _node_pc(state: State) -> dict:
    return {"log": ["pc"]}


def _node_join(state: State) -> dict:
    return {"log": ["join"]}


def _node_finish(state: State) -> dict:
    return {"log": ["finish"]}


def _route_parallel(state: State) -> list[str]:
    """依据状态返回下一批节点（superstep 并行扇出）。"""
    return ["pa", "pb", "pc"] if state.get("route") == "parallel" else ["finish"]


def build_counter_subgraph():
    """构造可复用子图：`sub_in → sub_out`，本地状态仅含隔离字段 `sub_total`。

    作为节点接入父图时，子图与父图**状态隔离**：内部对 `sub_total` 的读写
    （先 +1 再 ×2）不影响父图 `log`，父图对 `log` 的写入也不会被子图重放。
    """

    class SubState(TypedDict):
        sub_total: int

    def _sub_in(state: SubState) -> dict:
        return {"sub_total": state.get("sub_total", 0) + 1}

    def _sub_out(state: SubState) -> dict:
        return {"sub_total": state.get("sub_total", 0) * 2}

    builder = StateGraph(SubState)
    builder.add_node("sub_in", _sub_in)
    builder.add_node("sub_out", _sub_out)
    builder.add_edge(START, "sub_in")
    builder.add_edge("sub_in", "sub_out")
    builder.add_edge("sub_out", END)
    return builder.compile()


def build_upstream_graph(checkpointer=None):
    """构造上游图编排探针图（父图）：

        START → start → (route)
            ├─ 非 parallel → finish → END
            └─ parallel ──扇出──→ pa / pb / pc → join → sub(子图) → finish → END

    - `log` 并发写由 reducer (`operator.add`) 追加合并，而非最后写入覆盖；
    - `sub` 为子图节点（`build_counter_subgraph`），子图状态与父图隔离（写 `sub_total`）；
    - 可传入 `InMemorySaver` 等 checkpointer 以验证断点持久化。
    """
    builder = StateGraph(State)
    builder.add_node("start", _node_start)
    builder.add_node("pa", _node_pa)
    builder.add_node("pb", _node_pb)
    builder.add_node("pc", _node_pc)
    builder.add_node("join", _node_join)
    builder.add_node("sub", build_counter_subgraph())  # 子图作为节点
    builder.add_node("finish", _node_finish)
    builder.add_edge(START, "start")
    builder.add_conditional_edges("start", _route_parallel)
    builder.add_edge("pa", "join")
    builder.add_edge("pb", "join")
    builder.add_edge("pc", "join")
    builder.add_edge("join", "sub")
    builder.add_edge("sub", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def check_prebuilt() -> None:
    """验证 vendored prebuilt 包可导入且符号可用（lg-absorb 工具层）。"""
    from langchain_core.tools import tool
    from langgraph.prebuilt import ToolNode, create_react_agent, tools_condition

    assert callable(ToolNode), "ToolNode 不可调用"
    assert callable(tools_condition), "tools_condition 不可调用"
    assert callable(create_react_agent), "create_react_agent 不可调用"

    @tool
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    node = ToolNode([add])
    assert node is not None, "ToolNode 构造失败"
    print("prebuilt ToolNode / tools_condition / create_react_agent ok")


def main() -> None:
    # 1) 有类型状态 + reducer + 并行扇出 + 子图组合（状态隔离）
    graph = build_upstream_graph()
    cfg1 = {"configurable": {"thread_id": "lg-w0-07-main"}}
    result = graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, cfg1)
    assert result["log"][0] == "start", result["log"]
    assert result["log"][-1] == "finish", result["log"]
    # 并行节点 + 屏障汇总全部出现，且无子图重放父节点重复
    assert set(result["log"][1:4]) == {"pa", "pb", "pc"}, result["log"]
    assert result["log"][4] == "join", result["log"]
    assert result["log"].count("start") == 1, result["log"]
    # 子图隔离执行：sub_total 先 +1 再 ×2 → 2；父图 log 不受子图污染
    assert result["sub_total"] == 2, result
    print("1) typed-state + reducer + fanout + subgraph-isolated ok:", result)

    # 2) 条件路由：route=end 跳过扇出与子图，直接收束
    cfg2 = {"configurable": {"thread_id": "lg-w0-07-route-end"}}
    result_end = graph.invoke({"log": [], "route": "end", "sub_total": 0}, cfg2)
    assert result_end["log"] == ["start", "finish"], result_end["log"]
    print("2) conditional-route ok:", result_end["log"])

    # 3) checkpoint 断点持久化：get_state_history 可回放完整状态
    config = {"configurable": {"thread_id": "lg-w0-07"}}
    graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, config)
    history = list(graph.get_state_history(config))
    assert len(history) >= 2, len(history)
    assert history[0].values.get("log")[-1] == "finish", history[0]
    print(f"3) checkpoint durable ok: {len(history)} checkpoints")

    # 4) 流式状态事件：按节点粒度推送
    cfg4 = {"configurable": {"thread_id": "lg-w0-07-stream"}}
    events = [c for c in graph.stream({"log": [], "route": "parallel", "sub_total": 0}, cfg4)]
    node_names = [list(v.keys())[0] for v in events]
    assert node_names[0] == "start", node_names
    assert "join" in node_names and "finish" in node_names
    print("4) streaming state events ok:", node_names)

    # 5) prebuilt 工具层可导入可用
    check_prebuilt()

    print("LG-W0-07 UPSTREAM GRAPH PROBE PASSED (core + checkpoint + prebuilt, clean venv)")


# ---------------------------------------------------------------------------
# pytest 用例
# ---------------------------------------------------------------------------


def test_typed_state_reducer_append_merge() -> None:
    graph = build_upstream_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    result = graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, cfg)
    assert result["log"][0] == "start"
    assert set(result["log"][1:4]) == {"pa", "pb", "pc"}


def test_parallel_fanout_barrier_all_complete() -> None:
    graph = build_upstream_graph()
    cfg = {"configurable": {"thread_id": "t2"}}
    result = graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, cfg)
    for _n in ("pa", "pb", "pc"):
        assert _n in result["log"]
    assert result["log"].index("finish") > result["log"].index("join")


def test_conditional_routing_skips_parallel() -> None:
    graph = build_upstream_graph()
    cfg = {"configurable": {"thread_id": "t3"}}
    result = graph.invoke({"log": [], "route": "end", "sub_total": 0}, cfg)
    assert result["log"] == ["start", "finish"]


def test_subgraph_composition_isolated_state() -> None:
    graph = build_upstream_graph()
    cfg = {"configurable": {"thread_id": "t4"}}
    result = graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, cfg)
    # 子图作为节点接入，隔离执行：sub_total 先 +1 再 ×2 → 2
    assert result["sub_total"] == 2
    # 状态隔离：父图 log 不被子图重放/污染，无重复节点
    assert result["log"].count("start") == 1
    assert result["log"].count("join") == 1


def test_checkpoint_durable_history() -> None:
    graph = build_upstream_graph()
    config = {"configurable": {"thread_id": "lg-w0-07-py"}}
    graph.invoke({"log": [], "route": "parallel", "sub_total": 0}, config)
    history = list(graph.get_state_history(config))
    assert len(history) >= 2
    assert history[0].values.get("log")[-1] == "finish"


def test_streaming_state_events_per_node() -> None:
    graph = build_upstream_graph()
    cfg = {"configurable": {"thread_id": "t6"}}
    events = [c for c in graph.stream({"log": [], "route": "parallel", "sub_total": 0}, cfg)]
    node_names = [list(v.keys())[0] for v in events]
    assert node_names[0] == "start"
    assert "join" in node_names
    assert "finish" in node_names


def test_prebuilt_vendored_importable() -> None:
    check_prebuilt()


if __name__ == "__main__":
    main()