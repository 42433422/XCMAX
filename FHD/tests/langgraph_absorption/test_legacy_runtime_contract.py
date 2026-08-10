"""LG-W0-06 — 冻结 `app/application/workflow/engine.py`（+ schemas/checkpointer）的当前运行时契约。

本文件只读当前产品代码，把关键行为固化为可回放的"契约测试"：
编译 / 校验 / 顺序 / 条件 / 并行扇出 / reducer / 重试与错误 / 中断与审批 / checkpoint 与续跑 /
流式事件 / 序列化，共 11 类、>=32 个确定性用例。

约束（本任务）
- 只改本文件与 `fixtures/legacy_contract.json`；不改产品代码、不放宽断言。
- fixture 必须字节可复现（byte-reproducible），且不含绝对路径 / 时间戳 / 随机 ID。
- 不触碰根依赖 / 共享 .venv，不做 rm -rf。

验收方式
- 显式跑本文件两次均绿。
- `regenerate_fixture()` 生成 fixture；重复生成字节恒等（见 `_canonical_json`）。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

import pytest

from app.application.workflow.engine import DEFAULT_STATE_SCHEMA, WorkflowEngine
from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.types import (
    ApprovalStatus,
    Branch,
    PlanGraph,
    StateSchema,
    WorkflowNode,
    apply_state_schema,
    plan_from_dict,
    plan_to_dict,
    validate_plan_graph,
)

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_FIXTURE_PATH = _FIXTURE_DIR / "legacy_contract.json"

# ---------------------------------------------------------------------------
# 确定性构造辅助
# ---------------------------------------------------------------------------


def _dispatch_ok(tool_id, action, params):
    """确定性成功 dispatcher：返回仅依赖入参的稳定 dict。"""
    return {"success": True, "tool_id": tool_id, "action": action}


def _make_engine(dispatch=None):
    return WorkflowEngine(tool_dispatcher=dispatch or _dispatch_ok)


def _sequential_plan(n: int = 3, plan_id: str = "p_ct") -> PlanGraph:
    """n 个顺序节点（n_i 依赖 n_{i-1}），tool_id/action 唯一。"""
    nodes = [
        WorkflowNode(
            node_id=f"n{i}",
            tool_id=f"t{i}",
            action=f"a{i}",
            params={"k": i},
            risk="low",
            idempotent=True,
            depends_on=[] if i == 1 else [f"n{i - 1}"],
        )
        for i in range(1, n + 1)
    ]
    return PlanGraph(plan_id=plan_id, intent="contract", todo_steps=[f"s{i}" for i in range(1, n + 1)], nodes=nodes)


def _executed_nodes(result) -> list[str]:
    return sorted(result.final_context["workflow_status"]["executed_nodes"])


# ---------------------------------------------------------------------------
# 归一化：去掉时间戳 / 耗时 / checkpoint 唯一 ID 等易变字段，保证字节可复现
# ---------------------------------------------------------------------------

_TRACE_KEYS = ("node_id", "tool_id", "action", "success", "retries", "retryable", "error", "recovery_hint")


def _normalize_node_result(r) -> dict:
    return {
        "node_id": r.node_id,
        "tool_id": r.tool_id,
        "action": r.action,
        "success": bool(r.success),
        "retries": int(r.retries),
        "retryable": bool(r.retryable),
        "error": str(r.error),
        "recovery_hint": str(r.recovery_hint),
        "params": r.params,
        "output": r.output,
    }


def _normalize_context(ctx: dict) -> dict:
    out: dict = {}
    if "node_outputs" in ctx:
        out["node_outputs"] = ctx["node_outputs"]
    if "workflow_trace" in ctx:
        out["workflow_trace"] = [
            {k: tr[k] for k in _TRACE_KEYS if k in tr} for tr in ctx["workflow_trace"]
        ]
    if "workflow_status" in ctx:
        ws = dict(ctx["workflow_status"])
        if "executed_nodes" in ws:
            ws["executed_nodes"] = sorted(ws["executed_nodes"])
        if "unresolved_nodes" in ws:
            ws["unresolved_nodes"] = sorted(ws["unresolved_nodes"])
        out["workflow_status"] = ws
    if "message" in ctx:
        out["message"] = ctx["message"]
    return out


def _plan_signature(plan: PlanGraph) -> dict:
    return {
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "node_ids": [n.node_id for n in plan.nodes],
        "deps": {n.node_id: sorted(n.depends_on) for n in plan.nodes},
    }


def _reducer_golden() -> dict:
    schema = (
        StateSchema()
        .declare("count", type=int, merge="set")
        .declare("tags", type=list, merge="append")
        .declare("meta", type=dict, merge="merge_dict")
    )
    ctx = apply_state_schema({}, schema, writes={"count": 5})
    ctx = apply_state_schema(ctx, schema, writes={"tags": "a"})
    ctx = apply_state_schema(ctx, schema, writes={"tags": "b"})
    ctx = apply_state_schema(ctx, schema, writes={"meta": {"a": 1}})
    ctx = apply_state_schema(ctx, schema, writes={"meta": {"b": 2}})
    return {"count": ctx["count"], "tags": ctx["tags"], "meta": ctx["meta"]}


def _serialization_golden() -> dict:
    plan = _sequential_plan()
    d = plan_to_dict(plan)
    restored = plan_from_dict(d)
    return {
        "plan_to_dict_keys": sorted(d.keys()),
        "node_ids_after_roundtrip": [n.node_id for n in restored.nodes],
        "roundtrip_identical": _plan_signature(restored) == _plan_signature(plan),
    }


def _checkpoint_shape_golden() -> dict:
    cp = WorkflowCheckpointer()
    cid = cp.save_checkpoint("shape", 1, {"node_outputs": {"n1": {"ok": True}}}, ["n1"])
    ck = cp.get_checkpoint("shape", cid)
    return {
        "keys": sorted(ck.keys()),
        "plan_id": ck["plan_id"],
        "step_index": ck["step_index"],
        "executed_nodes": ck["executed_nodes"],
        "blocked": ck["blocked"],
        "runtime_context": ck["runtime_context"],
    }


def _build_contract_golden() -> dict:
    """从当前引擎计算一份确定性契约快照（归一化掉易变字段）。"""
    engine = _make_engine()
    plan = _sequential_plan()
    result = engine.run(plan, runtime_context={"message": "契约"})
    return {
        "spec": "LG-W0-06",
        "spec_title": "legacy workflow runtime contract freeze",
        "target": "app/application/workflow/engine.py + types.py (schemas) + checkpointer.py",
        "scope": [
            "FHD/tests/langgraph_absorption/test_legacy_runtime_contract.py",
            "FHD/tests/langgraph_absorption/fixtures/legacy_contract.json",
        ],
        "deterministic": True,
        "canonical_run": {
            "plan_id": plan.plan_id,
            "success": bool(result.success),
            "message": str(result.message),
            "executed_nodes": _executed_nodes(result),
            "node_results": [_normalize_node_result(r) for r in result.node_results],
            "final_context": _normalize_context(result.final_context),
        },
        "reducer_golden": _reducer_golden(),
        "serialization": _serialization_golden(),
        "checkpoint_shape": _checkpoint_shape_golden(),
    }


def _canonical_json(golden: dict) -> str:
    return json.dumps(golden, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def regenerate_fixture() -> Path:
    """把当前引擎行为写入 fixture（幂等：重复调用字节恒等）。"""
    _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(_build_contract_golden())
    _FIXTURE_PATH.write_text(payload, encoding="utf-8")
    return _FIXTURE_PATH


# ===========================================================================
# A. compile —— 引擎 / 图 "编译"（构造 + 结构契约）
# ===========================================================================


class TestCompile:
    def test_engine_constructs_with_dispatch(self):
        engine = _make_engine()
        assert engine._dispatch is not None
        assert engine._default_state_schema is DEFAULT_STATE_SCHEMA

    def test_default_state_schema_covers_common_keys(self):
        for key in ("node_outputs", "workflow_trace", "workflow_status", "message", "agent_history"):
            assert key in DEFAULT_STATE_SCHEMA.fields

    def test_workflownode_dataclass_defaults(self):
        node = WorkflowNode(node_id="n1", tool_id="t", action="a")
        assert node.risk == "low"
        assert node.idempotent is False
        assert node.depends_on == []
        assert node.branches == []
        assert node.next is None

    def test_plan_graph_dataclass_defaults(self):
        plan = PlanGraph(plan_id="p", intent="i")
        assert plan.risk_level == "low"
        assert plan.nodes == []
        assert plan.todo_steps == []


# ===========================================================================
# B. validation —— 图校验
# ===========================================================================


class TestValidation:
    def test_valid_plan_passes(self):
        assert validate_plan_graph(_sequential_plan()) is None

    def test_missing_plan_id(self):
        plan = PlanGraph(plan_id="", intent="x", nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a")])
        assert validate_plan_graph(plan) == "plan_id 不能为空"

    def test_duplicate_node_id(self):
        plan = PlanGraph(
            plan_id="p", intent="x",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="t1", action="a1"),
                WorkflowNode(node_id="n1", tool_id="t2", action="a2"),
            ],
        )
        assert validate_plan_graph(plan) == "node_id 不能重复"

    def test_dangling_dependency(self):
        plan = PlanGraph(
            plan_id="p", intent="x",
            nodes=[WorkflowNode(node_id="n1", tool_id="t", action="a", depends_on=["ghost"])],
        )
        assert validate_plan_graph(plan) == "节点 n1 依赖不存在: ghost"

    def test_conditional_cycle_detected(self):
        plan = PlanGraph(
            plan_id="p", intent="x",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="t1", action="a1", next="n2"),
                WorkflowNode(node_id="n2", tool_id="t2", action="a2", branches=[Branch(target="n1", condition={"key": "x", "equals": 1})]),
            ],
        )
        assert "环" in validate_plan_graph(plan)


# ===========================================================================
# C. sequential —— 顺序执行
# ===========================================================================


class TestSequential:
    def test_runs_all_nodes_in_topological_order(self):
        result = _make_engine().run(_sequential_plan())
        assert result.success is True
        assert [r.node_id for r in result.node_results] == ["n1", "n2", "n3"]

    def test_dependency_gates_downstream(self):
        calls: list[str] = []
        engine = _make_engine(lambda tool_id, action, params: calls.append(tool_id) or {"success": True})
        engine.run(_sequential_plan())
        assert calls == ["t1", "t2", "t3"]

    def test_node_outputs_recorded(self):
        result = _make_engine().run(_sequential_plan())
        assert set(result.final_context["node_outputs"]) == {"n1", "n2", "n3"}

    def test_workflow_status_completed(self):
        result = _make_engine().run(_sequential_plan())
        assert result.final_context["workflow_status"]["state"] == "completed"
        assert _executed_nodes(result) == ["n1", "n2", "n3"]

    def test_unresolvable_dependency_blocks_run(self):
        plan = PlanGraph(
            plan_id="p", intent="x",
            nodes=[
                WorkflowNode(node_id="n1", tool_id="t1", action="a1", depends_on=["n2"]),
                WorkflowNode(node_id="n2", tool_id="t2", action="a2", depends_on=["n1"]),
            ],
        )
        result = _make_engine().run(plan)
        assert result.success is False
        assert "依赖无法继续解析" in result.message


# ===========================================================================
# D. conditional —— 条件路由
# ===========================================================================


def _conditional_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p_cond", intent="conditional",
        nodes=[
            WorkflowNode(
                node_id="check", tool_id="inventory", action="check_stock", risk="low", idempotent=True,
                branches=[Branch(target="buy", condition={"key": "low_stock", "equals": True})],
                next="normal",
            ),
            WorkflowNode(node_id="buy", tool_id="purchase", action="advice", risk="low", idempotent=True, depends_on=["check"]),
            WorkflowNode(node_id="normal", tool_id="inventory", action="normal_advice", risk="low", idempotent=True, depends_on=["check"]),
        ],
    )


class TestConditional:
    def test_condition_match_routes_to_branch(self):
        engine = _make_engine(lambda tool_id, action, params: {"success": True, "low_stock": True})
        result = engine.run(_conditional_plan())
        assert _executed_nodes(result) == ["buy", "check"]

    def test_no_match_falls_back_to_next(self):
        engine = _make_engine(lambda tool_id, action, params: {"success": True, "low_stock": False})
        result = engine.run(_conditional_plan())
        assert _executed_nodes(result) == ["check", "normal"]

    def test_no_match_and_no_next_ends_normally(self):
        plan = PlanGraph(
            plan_id="p", intent="x",
            nodes=[
                WorkflowNode(node_id="gate", tool_id="x", action="y", risk="low", idempotent=True,
                             branches=[Branch(target="target", condition={"key": "flag", "equals": True})]),
                WorkflowNode(node_id="target", tool_id="z", action="w", risk="low", idempotent=True, depends_on=["gate"]),
            ],
        )
        engine = _make_engine(lambda tool_id, action, params: {"success": True, "flag": False})
        result = engine.run(plan)
        assert result.success is True
        assert _executed_nodes(result) == ["gate"]

    def test_unselected_branch_is_blocked(self):
        engine = _make_engine(lambda tool_id, action, params: {"success": True, "low_stock": True})
        result = engine.run(_conditional_plan())
        assert "normal" not in result.final_context["node_outputs"]


# ===========================================================================
# E. parallel fanout —— 并行扇出
# ===========================================================================


def _parallel_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p_par", intent="parallel",
        nodes=[
            WorkflowNode(node_id="p1", tool_id="products", action="query", params={}, risk="low", idempotent=True),
            WorkflowNode(node_id="p2", tool_id="customers", action="query", params={}, risk="low", idempotent=True),
            WorkflowNode(node_id="p3", tool_id="orders", action="query", params={}, risk="low", idempotent=True),
        ],
    )


class TestParallel:
    def test_independent_read_nodes_run_concurrently(self):
        barrier = threading.Barrier(3, timeout=5)
        seen: list[int] = []

        def dispatch(tool_id, action, params):
            seen.append(threading.get_ident())
            barrier.wait()
            return {"success": True, "tool_id": tool_id}

        result = _make_engine(dispatch).run(_parallel_plan(), runtime_context={"max_parallel_workers": 3})
        assert result.success is True
        assert len(set(seen)) == 3  # 三个独立只读节点确实并发执行

    def test_parallel_batch_metadata_recorded(self):
        result = _make_engine().run(_parallel_plan(), runtime_context={"max_parallel_workers": 3})
        batches = result.final_context["parallel_batches"]
        assert len(batches) == 1
        assert sorted(batches[0]["node_ids"]) == ["p1", "p2", "p3"]

    def test_high_risk_write_node_serialized(self):
        nodes = [
            WorkflowNode(node_id="w1", tool_id="sales", action="write", params={}, risk="high", idempotent=False),
            WorkflowNode(node_id="w2", tool_id="sales", action="write", params={}, risk="high", idempotent=False),
        ]
        plan = PlanGraph(plan_id="p", intent="x", nodes=nodes)
        seen: list[int] = []

        def dispatch(tool_id, action, params):
            seen.append(threading.get_ident())
            return {"success": True}

        result = _make_engine(dispatch).run(plan, runtime_context={"max_parallel_workers": 2})
        assert result.success is True
        # 写/高风险节点走串行路径（主线程），不进入并行线程池。
        assert len(set(seen)) == 1


# ===========================================================================
# F. reducers —— 状态合并语义
# ===========================================================================


class TestReducers:
    def test_append_reducer_accumulates_list(self):
        schema = StateSchema().declare("history", type=list, merge="append")
        ctx = apply_state_schema({}, schema, writes={"history": "first"})
        ctx = apply_state_schema(ctx, schema, writes={"history": "second"})
        assert ctx["history"] == ["first", "second"]

    def test_set_reducer_overwrites(self):
        schema = StateSchema().declare("value", type=str, merge="set")
        ctx = apply_state_schema({}, schema, writes={"value": "a"})
        ctx = apply_state_schema(ctx, schema, writes={"value": "b"})
        assert ctx["value"] == "b"

    def test_merge_dict_reducer_updates_in_place(self):
        schema = StateSchema().declare("meta", type=dict, merge="merge_dict")
        ctx = apply_state_schema({}, schema, writes={"meta": {"a": 1}})
        ctx = apply_state_schema(ctx, schema, writes={"meta": {"b": 2}})
        assert ctx["meta"] == {"a": 1, "b": 2}

    def test_type_mismatch_raises_valueerror(self):
        schema = StateSchema().declare("count", type=int, merge="set")
        with pytest.raises(ValueError) as exc:
            apply_state_schema({}, schema, writes={"count": "not-an-int"})
        assert "count" in str(exc.value) and "类型不符" in str(exc.value)

    def test_bool_vs_int_distinguished(self):
        schema = StateSchema().declare("flag", type=bool, merge="set")
        assert apply_state_schema({}, schema, writes={"flag": True})["flag"] is True
        with pytest.raises(ValueError):
            apply_state_schema({}, schema, writes={"flag": 1})


# ===========================================================================
# G. retry/error —— 重试与错误
# ===========================================================================


class TestRetry:
    def test_success_first_try_no_retry(self):
        result = _make_engine()._run_node(_sequential_plan(1).nodes[0], {}, max_retries=2)
        assert result.success is True
        assert result.retries == 0

    def test_retry_on_transient_failure(self):
        calls = {"n": 0}

        def dispatch(tool_id, action, params):
            calls["n"] += 1
            if calls["n"] <= 1:
                return {"success": False, "message": "temp"}
            return {"success": True}

        result = _make_engine(dispatch)._run_node(_sequential_plan(1).nodes[0], {}, max_retries=2)
        assert result.success is True
        assert result.retries == 1

    def test_retries_exhausted_marks_node_failed(self):
        def dispatch(tool_id, action, params):
            return {"success": False, "message": "permanent"}

        result = _make_engine(dispatch)._run_node(_sequential_plan(1).nodes[0], {}, max_retries=1)
        assert result.success is False
        assert result.error == "permanent"
        assert result.retries == 1

    def test_non_retryable_high_risk_node_no_retry(self):
        node = WorkflowNode(node_id="n1", tool_id="t", action="a", risk="high", idempotent=False)
        calls = {"n": 0}

        def dispatch(tool_id, action, params):
            calls["n"] += 1
            return {"success": False, "message": "boom"}

        result = _make_engine(dispatch)._run_node(node, {}, max_retries=5)
        assert result.success is False
        assert calls["n"] == 1  # 高风险非幂等节点不允许自动重试
        assert result.retries == 0

    def test_recoverable_exception_is_captured(self):
        def dispatch(tool_id, action, params):
            raise ValueError("boom")

        result = _make_engine(dispatch)._run_node(_sequential_plan(1).nodes[0], {}, max_retries=0)
        assert result.success is False
        assert "boom" in result.error


# ===========================================================================
# H. interrupt/approval —— 中断与审批
# ===========================================================================


def _clarify_plan() -> PlanGraph:
    return PlanGraph(
        plan_id="p_clarify", intent="confirm",
        nodes=[
            WorkflowNode(
                node_id="c1", tool_id="clarify", action="ask",
                params={"question": "确认执行?", "target_node_id": "op", "answer_key": "confirmed"},
                branches=[Branch(target="op", condition={"key": "answer_confirmed", "equals": True})],
            ),
            WorkflowNode(node_id="op", tool_id="ops", action="run", risk="low", idempotent=True, depends_on=["c1"]),
        ],
    )


class TestInterruptApproval:
    def test_clarify_node_pauses_with_requires_confirmation(self):
        calls: list[str] = []
        engine = _make_engine(lambda t, a, p: calls.append(t) or {"success": True})
        result = engine.run(_clarify_plan())
        assert result.success is True
        clarify_out = next(r.output for r in result.node_results if r.tool_id == "clarify")
        assert clarify_out["requires_confirmation"] is True
        assert calls == []  # 业务节点被屏蔽，未执行

    def test_confirmed_answer_resumes_to_target(self):
        engine = _make_engine()
        result = engine.run(_clarify_plan(), runtime_context={"_clarify_answers": {"c1": {"confirmed": True}}})
        assert result.success is True
        assert "op" in set(result.final_context["node_outputs"])
        clarify_out = next(r.output for r in result.node_results if r.tool_id == "clarify")
        assert clarify_out["answer_confirmed"] is True

    def test_approval_gated_pending_blocks_execution(self):
        from app.application.workflow.approval_gated_engine import ApprovalGatedEngine, GatedPlanDecision
        from app.application.workflow.types import ApprovalRequest

        class FakeApproval:
            def __init__(self):
                self.requests: dict[str, ApprovalRequest] = {}

            def create_approval_request(self, plan_id, node, runtime_context=None, plan=None):
                req = ApprovalRequest(
                    request_id="req-1", plan_id=plan_id, node_id=node.node_id,
                    tool_id=node.tool_id, action=node.action, params=node.params,
                    status=ApprovalStatus.PENDING, created_at=datetime(2026, 1, 1),
                )
                self.requests[req.request_id] = req
                return req

            def approve(self, request_id, comment=""):
                self.requests[request_id].status = ApprovalStatus.APPROVED
                return True

            def reject(self, request_id, comment=""):
                self.requests[request_id].status = ApprovalStatus.REJECTED
                return True

        calls: list[str] = []
        engine = _make_engine(lambda t, a, p: calls.append(t) or {"success": True})
        approval = FakeApproval()

        class FakeRisk:
            def evaluate(self, plan, context):
                fake = GatedPlanDecision(plan_id=plan.plan_id, risk_decision=None)
                return type("RD", (), {
                    "requires_confirmation": True, "reason": "test",
                    "blocking_nodes": ["op"], "denied_nodes": [],
                })()

        gated = ApprovalGatedEngine(engine, risk_gate=FakeRisk(), approval_service=approval)
        decision, run_result = gated.run(_clarify_plan(), strategy="interactive")
        assert decision.pending_approval is True
        assert run_result is None
        assert calls == []  # 待审批 → 不执行


# ===========================================================================
# I. checkpoint/resume —— 断点续跑与重放
# ===========================================================================


def _checkpoint_plan() -> PlanGraph:
    return _sequential_plan(5, plan_id="p_cp")


class TestCheckpointResume:
    def test_checkpoint_saved_per_step(self):
        cp = WorkflowCheckpointer()
        engine = _make_engine(lambda tool_id, action, params: {"success": False, "message": "fail at " + tool_id} if tool_id == "t4" else {"success": True})
        engine.run(_checkpoint_plan(), checkpointer=cp)
        cps = cp.list_checkpoints("p_cp")
        assert [c["step_index"] for c in cps] == [1, 2, 3]

    def test_resume_skips_already_done_nodes(self):
        cp = WorkflowCheckpointer()
        first_calls: list[str] = []
        engine = _make_engine(lambda tool_id, action, params: {"success": False, "message": "fail"} if tool_id == "t4" else (first_calls.append(tool_id) or {"success": True}))
        plan = _checkpoint_plan()
        assert engine.run(plan, checkpointer=cp).success is False
        resume_ckpt = cp.list_checkpoints("p_cp")[-1]

        resume_calls: list[str] = []
        resumer = _make_engine(lambda tool_id, action, params: resume_calls.append(tool_id) or {"success": True})
        result = resumer.resume_run(plan, resume_ckpt["checkpoint_id"], checkpointer=cp)
        assert result.success is True
        assert _executed_nodes(result) == ["n1", "n2", "n3", "n4", "n5"]
        assert "t1" not in resume_calls and "t3" not in resume_calls  # 已完成节点不重复执行
        assert "t4" in resume_calls and "t5" in resume_calls

    def test_replay_matches_original_run(self):
        cp = WorkflowCheckpointer()
        engine = _make_engine()
        plan = _checkpoint_plan()
        original = engine.run(plan, checkpointer=cp)
        assert original.success is True
        replay = engine.replay_run(plan.plan_id, checkpointer=cp)
        assert replay.success is True
        assert [r.node_id for r in replay.node_results] == [r.node_id for r in original.node_results]
        assert replay.final_context["node_outputs"] == original.final_context["node_outputs"]

    def test_resume_missing_checkpoint_fails(self):
        cp = WorkflowCheckpointer()
        result = _make_engine().resume_run(_checkpoint_plan(), "cp-none", checkpointer=cp)
        assert result.success is False
        assert "不存在" in result.message


# ===========================================================================
# J. streaming/events —— 流式状态事件
# ===========================================================================


class TestStreamingEvents:
    def test_state_event_callback_emits_per_node(self):
        events: list[dict] = []
        engine = _make_engine()
        engine.run(_sequential_plan(3), state_event_callback=events.append)
        assert [e["type"] for e in events] == ["state.update"] * 3
        assert [e["node_id"] for e in events] == ["n1", "n2", "n3"]
        assert all(e["status"] == "succeeded" for e in events)

    def test_callback_failure_does_not_break_run(self):
        def bad_callback(_event):
            raise RuntimeError("callback boom")

        engine = _make_engine()
        result = engine.run(_sequential_plan(3), state_event_callback=bad_callback)
        assert result.success is True  # 回调异常不影响主流程


# ===========================================================================
# K. serialization —— 序列化
# ===========================================================================


class TestSerialization:
    def test_plan_to_dict_roundtrip(self):
        plan = _sequential_plan()
        restored = plan_from_dict(plan_to_dict(plan))
        assert _plan_signature(restored) == _plan_signature(plan)

    def test_plan_from_dict_none_on_empty(self):
        assert plan_from_dict(None) is None
        assert plan_from_dict({}) is None

    def test_node_outputs_json_serializable(self):
        result = _make_engine().run(_sequential_plan(3))
        json.dumps(result.final_context["node_outputs"], ensure_ascii=False)  # 不抛异常即可


# ===========================================================================
# Fixture 冻结契约
# ===========================================================================


class TestFixtureFreeze:
    def test_fixture_matches_current_engine_behavior(self):
        assert _FIXTURE_PATH.exists(), "fixture 缺失，请先运行 regenerate_fixture()"
        canonical = _canonical_json(_build_contract_golden())
        assert _FIXTURE_PATH.read_text(encoding="utf-8") == canonical, (
            "当前引擎行为与 fixture 不一致 —— 契约被破坏，禁止放宽断言或修改产品行为"
        )

    def test_fixture_has_no_volatile_fields(self):
        assert _FIXTURE_PATH.exists()
        text = _FIXTURE_PATH.read_text(encoding="utf-8")
        # 无绝对路径（/Users、/private、/opt 等）
        assert not re.search(r'/(Users|private|opt|tmp|var)/', text)
        # 无 ISO 时间戳
        assert re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', text) is None
        # 无 checkpoint 时间戳式 ID（cp-YYYYMMDD...）
        assert re.search(r'cp-\d{14}', text) is None
        # 无 32 位十六进制随机 ID
        assert re.search(r'\b[0-9a-f]{32}\b', text) is None

    def test_fixture_is_valid_deterministic_json(self):
        assert _FIXTURE_PATH.exists()
        data = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        assert data["spec"] == "LG-W0-06"
        assert data["deterministic"] is True
        assert data["canonical_run"]["success"] is True
        assert data["canonical_run"]["executed_nodes"] == ["n1", "n2", "n3"]