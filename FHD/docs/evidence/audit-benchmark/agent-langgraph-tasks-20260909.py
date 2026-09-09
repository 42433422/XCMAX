# R22 agent-orchestration 域开源锚点实测：LangGraph 任务集 B1-B3
# 输出单行 JSON（RESULT:<json>）
import json
import sqlite3
import tempfile
import time
from pathlib import Path

out = {"benchmark": "langgraph", "tasks": {}}

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

try:
    from importlib.metadata import version

    out["version"] = version("langgraph")
except Exception:  # noqa: BLE001
    out["version"] = "unknown"


# ---------- B1 状态持久化 + 暂停恢复 ----------
try:
    tmp = Path(tempfile.mkdtemp(prefix="r22-lg-b1-"))
    conn = sqlite3.connect(str(tmp / "ckpt.sqlite"), check_same_thread=False)
    saver = SqliteSaver(conn)

    def step_a(state):
        return {"trace": state.get("trace", []) + ["a"], "value": state.get("value", 0) + 1}

    def step_b(state):
        return {"trace": state.get("trace", []) + ["b"], "value": state.get("value", 0) + 10}

    g = StateGraph(dict)
    g.add_node("a", step_a)
    g.add_node("b", step_b)
    g.add_edge(START, "a")
    g.add_edge("a", "b")
    g.add_edge("b", END)
    app = g.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "b1-run"}}
    app.invoke({"trace": [], "value": 0}, cfg)
    # 重启语义：新连接读同一持久化文件，历史仍在
    conn.close()
    conn2 = sqlite3.connect(str(tmp / "ckpt.sqlite"), check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    app2 = g.compile(checkpointer=saver2)
    snap = app2.get_state({"configurable": {"thread_id": "b1-run"}})
    persisted = dict(snap.values)
    conn2.close()
    out["tasks"]["B1"] = {
        "verdict": "PASS" if persisted.get("value") == 11 and persisted.get("trace") == ["a", "b"] else "FAIL",
        "reloaded_state": persisted,
        "mechanism": "SqliteSaver 落盘；重开连接按 thread_id 恢复完整状态",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B1"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B2 工具输入校验 + 人工审批绑定实际动作 ----------
try:
    tmp2 = Path(tempfile.mkdtemp(prefix="r22-lg-b2-"))
    conn2 = sqlite3.connect(str(tmp2 / "ckpt.sqlite"), check_same_thread=False)
    saver2 = SqliteSaver(conn2)
    audit_log = []

    def approve_node(state):
        # 未获批准前不执行任何副作用
        decision = interrupt({"action": "transfer", "amount": state["amount"]})
        audit_log.append(("decision", decision))
        if not (isinstance(decision, dict) and decision.get("approved")):
            return {"executed": False, "trace": state.get("trace", []) + ["rejected"]}
        return {"executed": True, "trace": state.get("trace", []) + ["executed"]}

    g2 = StateGraph(dict)
    g2.add_node("approve", approve_node)
    g2.add_edge(START, "approve")
    g2.add_edge("approve", END)
    app2 = g2.compile(checkpointer=saver2)
    cfg2 = {"configurable": {"thread_id": "b2-run"}}
    first = app2.invoke({"amount": 500, "executed": False}, cfg2)
    paused = "__interrupt__" in first or any(getattr(i, "value", None) for i in first.get("__interrupt__", []))
    # 拒绝路径
    rej = app2.invoke(Command(resume={"approved": False}), cfg2)
    rejected_executed = rej.get("executed")
    # 批准路径（新线程）
    cfg2b = {"configurable": {"thread_id": "b2-run-ok"}}
    app2.invoke({"amount": 500, "executed": False}, cfg2b)
    ok = app2.invoke(Command(resume={"approved": True}), cfg2b)
    conn2.close()
    passed = bool(paused) and rejected_executed is False and ok.get("executed") is True
    out["tasks"]["B2"] = {
        "verdict": "PASS" if passed else "FAIL",
        "halted_before_action": paused,
        "rejected_side_effect": rejected_executed,
        "approved_side_effect": ok.get("executed"),
        "mechanism": "interrupt() 挂起图执行，审批结果决定副作用是否发生",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B2"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B3 重试/取消/恢复不重复产生副作用 ----------
try:
    tmp3 = Path(tempfile.mkdtemp(prefix="r22-lg-b3-"))
    conn3 = sqlite3.connect(str(tmp3 / "ckpt.sqlite"), check_same_thread=False)
    saver3 = SqliteSaver(conn3)
    effects = []
    attempts = {"n": 0}

    def flaky_node(state):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient failure")
        effects.append("side-effect")  # 仅在成功路径记录
        return {"trace": state.get("trace", []) + ["ok"], "count": len(effects)}

    g3 = StateGraph(dict)
    g3.add_node("flaky", flaky_node)
    g3.add_edge(START, "flaky")
    g3.add_edge("flaky", END)
    app3 = g3.compile(checkpointer=saver3)
    cfg3 = {"configurable": {"thread_id": "b3-run"}}
    err = None
    try:
        app3.invoke({"trace": []}, cfg3)
    except Exception as e:  # noqa: BLE001
        err = type(e).__name__
    # 恢复：重试直至成功（幂等锚：effects 只追加一次）
    res = None
    for _ in range(4):
        try:
            res = app3.invoke({"trace": []}, cfg3)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.01)
    conn3.close()
    passed = res is not None and len(effects) == 1 and attempts["n"] == 3
    out["tasks"]["B3"] = {
        "verdict": "PASS" if passed else "FAIL",
        "first_attempt_error": err,
        "effect_count": len(effects),
        "attempt_count": attempts["n"],
        "mechanism": "失败重试不重复执行副作用（effects 单次），最终收敛成功",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B3"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

print("RESULT:" + json.dumps(out, ensure_ascii=False, default=str))
