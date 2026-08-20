# mypy: disable-error-code="arg-type"
"""LG-W0-08｜上游持久化 / HITL（Human-in-the-loop）探针.

任务：在 FHD 侧验证 vendored 上游 `langgraph`（tag 1.2.10、锁定 commit
`41341457342327166d72fc11952ab28fb61ec0bf`）的持久化 + HITL 能力，作为后续
NeuroBus 引擎吸收中断/恢复原语的行为基线。

运行环境约束：

  - **无 sys.path 变异、无 PYTHONPATH**：本文件不做任何 `sys.path` 注入；
  - 运行于**包本地锁定 uv 环境**（`tests/langgraph_absorption/.venv`，由
    `pyproject.toml` + `uv.lock` 定义），其中 4 个 vendored 兄弟包以 editable
    方式安装，模块路径解析到 `FHD/packages/xcagi*`：
      * `xcagi_langgraph_core`          → `langgraph.graph` / `langgraph.types` / `langgraph.constants`
      * `xcagi_langgraph_checkpoint`    → `langgraph.checkpoint.memory`（`InMemorySaver`）
      * `checkpoint-sqlite`             → `langgraph.checkpoint.sqlite`（`SqliteSaver`）
      * `xcagi_langgraph_prebuilt`      → `langgraph.prebuilt`（工具层，探针附带验证可导入）
  - 探针断言上述模块源文件路径解析在 `FHD/packages/xcagi*` 目录内；
  - SQLite 探针使用 `tempfile.TemporaryDirectory` 隔离临时库，实现**真实重启**：
    首跑到中断后关闭首个 graph/连接，再对**同一临时库文件**新建连接并编译新 graph，
    `Command(resume)` 续跑必须不重复执行已完成节点。

覆盖能力：

  - `interrupt(...)` 触发中断 → 图暂停，携带可恢复值；
  - `Command(resume=...)` 恢复执行（持久化 + resume）；
  - 恢复后已完成节点不重复执行（幂等续跑，log == [a, ask, b]）；
  - `get_state_history` 回放完整 checkpoint 历史（replay）；
  - `update_state` 从历史 checkpoint fork 实现时间旅行（time-travel）。

本文件同时作为可执行脚本与 pytest 用例使用（共 5 项确定性测试）。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt

__all__ = [
    "State",
    "build_durable_hitl_graph",
    "THREAD_ID",
    "VENDORED_PACKAGES_ROOT",
]


# FHD/packages 根目录：用于断言 vendored 兄弟包模块路径解析位置。
VENDORED_PACKAGES_ROOT = Path(__file__).resolve().parents[2] / "packages"


class State(TypedDict):
    """探针图状态：记录已执行节点与人工输入。"""

    log: list[str]
    human: str | None


THREAD_ID = "lg-w0-08-durable-hitl"


def _step_a(state: State) -> dict:
    return {"log": [*state.get("log", []), "a"]}


def _ask_human(state: State) -> dict:
    # 首个执行此节点时抛出 GraphInterrupt，图暂停；恢复时返回 resume 值。
    answer = interrupt({"prompt": "need human input", "state": state.get("log")})
    return {"human": answer, "log": [*state.get("log", []), "ask"]}


def _step_b(state: State) -> dict:
    return {"log": [*state.get("log", []), "b"]}


def build_durable_hitl_graph(checkpointer=None):
    """构造带 HITL 中断点的图：START → a → ask_human → b → END。

    默认使用 `InMemorySaver`；也可传入 `SqliteSaver` 等持久化 saver。
    """
    builder = StateGraph(State)
    builder.add_node("a", _step_a)
    builder.add_node("ask", _ask_human)
    builder.add_node("b", _step_b)
    builder.add_edge(START, "a")
    builder.add_edge("a", "ask")
    builder.add_edge("ask", "b")
    builder.add_edge("b", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _make_config() -> dict:
    return {"configurable": {"thread_id": THREAD_ID}}


def assert_vendored_module_paths() -> None:
    """断言 4 个 vendored 兄弟包模块源文件路径解析在 FHD/packages/xcagi* 内。

    若任一模块解析到 site-packages / 站点包，则说明未使用 vendored 副本，探针无效。
    """
    import langgraph.checkpoint.memory as _mem
    import langgraph.checkpoint.sqlite as _sq
    import langgraph.graph.state as _core
    import langgraph.prebuilt as _pb
    import langgraph.types as _types

    root_str = str(VENDORED_PACKAGES_ROOT.resolve())
    modules = {
        "core.graph": _core,
        "types": _types,
        "checkpoint.memory": _mem,
        "checkpoint.sqlite": _sq,
        "prebuilt": _pb,
    }
    for name, mod in modules.items():
        f = Path(mod.__file__).resolve()
        assert root_str in str(f), f"{name} 未解析到 FHD/packages: {f}"
        assert "xcagi_langgraph" in str(f) or "checkpoint-" in str(f), f
        print(f"  vendored {name}: {f}")


def assert_prebuilt_importable() -> None:
    """验证 vendored prebuilt 工具层可导入且符号可用。"""
    from langgraph.prebuilt import ToolNode, create_react_agent, tools_condition

    assert callable(ToolNode), "ToolNode 不可调用"
    assert callable(tools_condition), "tools_condition 不可调用"
    assert callable(create_react_agent), "create_react_agent 不可调用"
    print("  prebuilt ToolNode / tools_condition / create_react_agent ok")


def main() -> None:
    print("vendored module paths:")
    assert_vendored_module_paths()
    print("prebuilt import:")
    assert_prebuilt_importable()

    # --- MemorySaver 探针 ---
    mem_graph = build_durable_hitl_graph()
    mem_cfg = _make_config()
    first = mem_graph.invoke({"log": []}, mem_cfg)
    assert "__interrupt__" in first, first
    assert first["log"] == ["a"], first
    resumed = mem_graph.invoke(Command(resume="42"), mem_cfg)
    assert resumed["log"] == ["a", "ask", "b"], resumed
    assert resumed["human"] == "42", resumed
    print("1) MemorySaver interrupt+resume ok:", resumed["log"])

    # replay：get_state_history 完整回放
    history = list(mem_graph.get_state_history(mem_cfg))
    assert len(history) >= 3, len(history)
    assert history[0].values.get("log") == ["a", "ask", "b"], history[0]
    print(f"2) MemorySaver replay ok: {len(history)} checkpoints")

    # time-travel：从最早 checkpoint fork
    snapshot = history[-1]
    fork = mem_graph.update_state(snapshot.config, {"log": ["fork"]}, as_node="a")
    assert fork is not None
    print("3) MemorySaver time-travel/update_state ok")

    # --- SQLite 探针：真实重启（tempfile 隔离，退出自动清理）---
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str((Path(tmpdir) / "ckpt.sqlite").resolve())

        # 首次运行：graph1 + conn1 → 中断
        conn1 = sqlite3.connect(db_path, check_same_thread=False)
        sql_graph1 = build_durable_hitl_graph(checkpointer=SqliteSaver(conn1))
        cfg1 = _make_config()
        s_first = sql_graph1.invoke({"log": []}, cfg1)
        assert "__interrupt__" in s_first, s_first
        assert s_first["log"] == ["a"], s_first
        # 关闭首图形/连接，模拟进程重启
        conn1.close()

        # 重启续跑：新连接 + 新 graph，针对同一临时库文件
        conn2 = sqlite3.connect(db_path, check_same_thread=False)
        sql_graph2 = build_durable_hitl_graph(checkpointer=SqliteSaver(conn2))
        cfg2 = _make_config()
        s_resumed = sql_graph2.invoke(Command(resume="sqlite-input"), cfg2)
        assert s_resumed["log"] == ["a", "ask", "b"], s_resumed
        assert s_resumed["human"] == "sqlite-input", s_resumed
        print("4) SQLite real-restart resume ok:", s_resumed["log"])

        # replay + time-travel on SQLite（重启后）
        sql_history = list(sql_graph2.get_state_history(cfg2))
        assert len(sql_history) >= 3, len(sql_history)
        assert sql_history[0].values.get("log") == ["a", "ask", "b"]
        sql_snapshot = sql_history[-1]
        sql_fork = sql_graph2.update_state(sql_snapshot.config, {"log": ["fork"]}, as_node="a")
        assert sql_fork is not None
        print(f"5) SQLite replay+time-travel ok: {len(sql_history)} checkpoints")

        # 验证临时库文件已落地（持久化写盘）
        assert Path(db_path).exists(), db_path
        conn2.close()

    print("LG-W0-08 DURABLE HITL PROBE PASSED (vendored packages + MemorySaver + SQLite restart)")


# ---------------------------------------------------------------------------
# pytest 用例（共 5 项确定性测试）
# ---------------------------------------------------------------------------


def test_vendored_module_paths_and_prebuilt() -> None:
    """所有 vendored 模块路径解析到 FHD/packages/xcagi*，且 prebuilt 可导入。"""
    assert_vendored_module_paths()
    assert_prebuilt_importable()


def test_interrupt_pauses_and_resume_continues_memory() -> None:
    graph = build_durable_hitl_graph()
    config = _make_config()
    first = graph.invoke({"log": []}, config)
    assert "__interrupt__" in first
    assert first["log"] == ["a"]
    resumed = graph.invoke(Command(resume="42"), config)
    assert resumed["human"] == "42"
    # 恢复后已完成节点（a）不重复执行：log 恰为 a→ask→b 各一次
    assert resumed["log"] == ["a", "ask", "b"]


def test_checkpoint_history_replay_memory() -> None:
    graph = build_durable_hitl_graph()
    config = _make_config()
    graph.invoke({"log": []}, config)
    graph.invoke(Command(resume="x"), config)
    history = list(graph.get_state_history(config))
    assert len(history) >= 3
    assert history[0].values.get("log") == ["a", "ask", "b"]


def test_update_state_time_travel_memory() -> None:
    graph = build_durable_hitl_graph()
    config = _make_config()
    graph.invoke({"log": []}, config)
    snapshot = list(graph.get_state_history(config))[-1]
    fork = graph.update_state(snapshot.config, {"log": ["fork"]}, as_node="a")
    assert fork is not None


def test_sqlite_real_restart_resume() -> None:
    """SQLite 真实重启：关闭首 graph/连接后，对同一库新建连接+新 graph 续跑。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str((Path(tmpdir) / "ckpt.sqlite").resolve())

        conn1 = sqlite3.connect(db_path, check_same_thread=False)
        graph1 = build_durable_hitl_graph(checkpointer=SqliteSaver(conn1))
        config1 = _make_config()
        first = graph1.invoke({"log": []}, config1)
        assert "__interrupt__" in first
        assert first["log"] == ["a"]
        conn1.close()

        conn2 = sqlite3.connect(db_path, check_same_thread=False)
        graph2 = build_durable_hitl_graph(checkpointer=SqliteSaver(conn2))
        config2 = _make_config()
        resumed = graph2.invoke(Command(resume="sqlite-input"), config2)
        assert resumed["log"] == ["a", "ask", "b"]  # 已完成节点不重复执行
        assert resumed["human"] == "sqlite-input"

        history = list(graph2.get_state_history(config2))
        assert len(history) >= 3
        assert history[0].values.get("log") == ["a", "ask", "b"]
        snapshot = history[-1]
        fork = graph2.update_state(snapshot.config, {"log": ["fk"]}, as_node="a")
        assert fork is not None
        assert Path(db_path).exists()
        conn2.close()


if __name__ == "__main__":
    main()
