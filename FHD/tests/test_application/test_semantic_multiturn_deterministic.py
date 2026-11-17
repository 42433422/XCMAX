"""语义层多轮闭环的确定性验收（不依赖真实模型）。

覆盖真实模型验收里不稳定复现的三条路径：
- S1 追问继承：上一轮用户原话与助手回复必须进入规划 prompt 的 ``recent_messages``。
- S2 候选澄清：「就第二个」必须解析到第二个候选并推进到执行/审批，而不是重复追问。
- S3 参数补充：补齐 missing_required 后原计划续跑，澄清步骤完成、参数落到目标节点。
- S4 审批执行：审批通过（approved_step_id）后真正写库，并完成数据库回查核验。
"""

from __future__ import annotations

import json
from unittest.mock import Mock

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.ai_chat.workflow_session import WorkflowSession
from app.application.workflow.clarification_node import build_clarify_node
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


class _Callbacks:
    """WorkflowSession 只需一个可提供 workflow_planner 的占位回调。"""

    workflow_planner = None


def _plan_with_candidates(
    candidates: list[dict[str, object]],
    *,
    plan_id: str,
    payload: dict[str, object],
) -> PlanGraph:
    clarify = build_clarify_node(
        "检测到多个匹配目标，请选择要操作的对象。",
        ambient={
            "node_id": "update_price_clarify",
            "target_node_id": "update_price",
            "clarification": {
                "reason": "ambiguous_target",
                "node_id": "update_price",
                "field": "id",
                "candidates": candidates,
                "question": "检测到多个匹配目标，请选择要操作的对象。",
            },
        },
    )
    write = WorkflowNode(
        node_id="update_price",
        tool_id="business_db",
        action="write",
        params={"entity": "products", "operation": "update", "payload": payload},
        risk="high",
        idempotent=False,
        description="更新产品价格",
    )
    return PlanGraph(
        plan_id=plan_id,
        intent="business_db_write",
        todo_steps=["选择目标产品", "更新价格"],
        nodes=[clarify, write],
        risk_level="high",
    )


def test_s2_candidate_reply_resolves_second_target_and_reaches_approval(
    trusted_actor, monkeypatch
) -> None:
    from app.db.models.product import Product
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(role="admin")
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        first = Product(tenant_id=actor.tenant_id, name="甲型涂料", model_number="A1", price=10)
        second = Product(tenant_id=actor.tenant_id, name="乙型涂料", model_number="A1", price=20)
        db.add_all([first, second])
        db.flush()
        candidates = [
            {"id": int(first.id), "name": "甲型涂料"},
            {"id": int(second.id), "name": "乙型涂料"},
        ]
        expected_id = int(second.id)

    plan = _plan_with_candidates(
        candidates, plan_id="s2-candidate", payload={"changes": {"price": 99}}
    )
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    runtime_context = {
        **actor.context,
        "session_id": "s2-session",
        "conversation_id": "s2-session",
        "message": "把产品 A1 的价格改成 99 元",
    }
    with tenant_scope(actor.tenant_id):
        run = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message="把产品 A1 的价格改成 99 元",
            plan=plan,
            runtime_context=runtime_context,
        )
        assert run.status == "waiting_user"
        waiting = next(step for step in run.steps if step.status == "waiting_user")
        assert waiting.node_id == "update_price_clarify"

        # 生产解析逻辑：口语序号「就第二个」绑定到第二个候选。
        answer = WorkflowSession({}, _Callbacks())._clarification_answer(run, waiting, "就第二个")
        assert answer is not None
        parameters, confirmed, allowed_fields = answer
        assert parameters == {"payload": {"id": str(expected_id)}}
        assert confirmed is True and allowed_fields == set()

        parameters = {**parameters, "payload": {"id": expected_id}}
        continued = orchestrator.continue_after_clarification(
            run.run_id,
            answered_by=str(actor.user_id),
            clarification_step_id=waiting.step_id,
            parameters=parameters,
            confirmed=True,
            allowed_fields=allowed_fields,
            runtime_context=runtime_context,
        )

    assert continued is not None
    assert continued.status == "waiting_user", continued.error
    clarify_step = next(step for step in continued.steps if step.node_id == "update_price_clarify")
    assert clarify_step.status == "completed"
    write_step = next(step for step in continued.steps if step.node_id == "update_price")
    assert write_step.params["payload"]["id"] == expected_id
    assert write_step.status == "waiting_user"
    assert continued.tool_calls == [], "候选未确认前不得执行业务写入"


def test_s3_missing_required_answer_resumes_beyond_clarification() -> None:
    params = {"items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
    clarify = build_clarify_node(
        "请提供客户名称",
        ambient={
            "node_id": "quote_clarify",
            "target_node_id": "quote",
            "clarification": {"reason": "missing_required", "missing_fields": ["customer_name"]},
        },
    )
    quote = WorkflowNode(
        node_id="quote",
        tool_id="sales",
        action="quote",
        params=params,
        risk="high",
        idempotent=False,
    )
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="报价",
        plan=PlanGraph(
            plan_id="s3-missing-required",
            intent="sales",
            nodes=[clarify, quote],
        ),
    )
    assert run.status == "waiting_user"

    orchestrator.stage_clarification_answer(
        run.run_id,
        step_id=run.steps[0].step_id,
        parameters={"customer_name": "客户甲"},
        requested_by="owner",
    )
    continued = orchestrator.execute_dispatched_run(run.run_id)

    clarify_step = next(step for step in continued.steps if step.node_id == "quote_clarify")
    quote_step = next(step for step in continued.steps if step.node_id == "quote")
    # 补齐后不再停在澄清；目标节点已经拿到完整参数并进入审批边界。
    assert clarify_step.status == "completed"
    assert quote_step.params == {**params, "customer_name": "客户甲"}
    assert continued.status == "waiting_user"
    assert continued.tool_calls == []
    assert continued.final_output.get("clarification", {}).get("step_id") != clarify_step.step_id


def test_s4_approved_step_writes_database_and_verifies_readback(trusted_actor) -> None:
    from app.db.models.product import Product
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(role="admin")
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        first = Product(tenant_id=actor.tenant_id, name="甲型涂料", model_number="A1", price=10)
        second = Product(tenant_id=actor.tenant_id, name="乙型涂料", model_number="A1", price=20)
        db.add_all([first, second])
        db.flush()
        expected_id = int(second.id)
        other_id = int(first.id)
        candidates = [
            {"id": other_id, "name": "甲型涂料"},
            {"id": expected_id, "name": "乙型涂料"},
        ]

    plan = _plan_with_candidates(
        candidates, plan_id="s4-approved-write", payload={"changes": {"price": 99}}
    )
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    runtime_context = {
        **actor.context,
        "session_id": "s4-session",
        "conversation_id": "s4-session",
        "message": "把产品 A1 的价格改成 99 元",
    }
    with tenant_scope(actor.tenant_id):
        run = orchestrator.start_run_from_plan(
            user_id=str(actor.user_id),
            message="把产品 A1 的价格改成 99 元",
            plan=plan,
            runtime_context=runtime_context,
        )
        waiting = next(step for step in run.steps if step.status == "waiting_user")
        orchestrator.continue_after_clarification(
            run.run_id,
            answered_by=str(actor.user_id),
            clarification_step_id=waiting.step_id,
            parameters={"payload": {"id": expected_id}},
            confirmed=True,
            runtime_context=runtime_context,
        )
        write_step = next(step for step in run.steps if step.node_id == "update_price")
        executed = orchestrator.continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            approved_step_id=write_step.step_id,
            runtime_context=runtime_context,
        )

    assert executed is not None
    write_step = next(step for step in executed.steps if step.node_id == "update_price")
    assert write_step.status == "completed", write_step.error
    verification = (write_step.output or {}).get("business_verification") or {}
    assert verification.get("verified") is True, write_step.output
    assert verification.get("entity") == "products"

    from app.db.session import get_db

    with tenant_scope(actor.tenant_id):
        with get_db() as db:
            product = db.get(Product, expected_id)
            assert product is not None
            assert int(product.price) == 99
            other = db.get(Product, other_id)
            assert int(other.price) == 10, "未选中的候选不应被修改"


def test_s1_recent_turns_reach_planner_prompt(monkeypatch, tmp_path) -> None:
    from app.application.ai_chat.dialogue_memory import (
        prepare_chat_turn,
        recent_conversation_messages,
        settle_chat_turn,
    )
    from app.application.workflow.llm_plan_generation import LlmPlanGeneration
    from app.application.workflow_registry_app import get_workflow_tool_registry

    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path / "dialogue-memory"))
    base = {"actor_id": "42", "tenant_id": 7, "session_id": "s1", "conversation_id": "s1"}
    first_turn = {**base, "turn_id": "s1:t1"}
    assert prepare_chat_turn("帮我查一下客户张三的资料", first_turn) is None
    settle_chat_turn(
        "帮我查一下客户张三的资料",
        first_turn,
        {"response": "张三：客户编号 12，联系电话 13800000000"},
        "completed",
    )

    second_turn = {**base, "turn_id": "s1:t2"}
    history = recent_conversation_messages(second_turn, limit=6)
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert "张三" in history[0]["content"]

    captured: dict[str, object] = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"mode": "reply", "reply": "张三目前有一笔订单。"},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    conversation = Mock(get_context=Mock(return_value=None))
    generation = LlmPlanGeneration(conversation, completion, lambda: Mock())
    generation.generate(
        plan_id="s1-inherit",
        user_id="42",
        message="那他的订单呢",
        tool_registry=get_workflow_tool_registry(),
        context=second_turn,
    )

    messages = captured.get("messages")
    assert isinstance(messages, list) and len(messages) == 2
    prompt = json.loads(messages[1]["content"])
    recent = prompt.get("recent_messages") or []
    assert [item["role"] for item in recent] == ["user", "assistant"]
    assert "张三" in recent[0]["content"]
    assert "客户编号 12" in recent[1]["content"]
