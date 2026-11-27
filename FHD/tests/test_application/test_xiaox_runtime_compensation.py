"""Approved proposals and missing-goal compensation without repeating completed writes."""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import xiaox_runtime as runtime
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract, canonical_digest
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import goal, review
from tests.fixtures.xiaox_goal_review import verifier as verifier
from tests.fixtures.xiaox_runtime import Bridge as Bridge
from tests.fixtures.xiaox_runtime import Store as Store
from tests.fixtures.xiaox_runtime import Transport as Transport
from tests.fixtures.xiaox_runtime import completed as completed
from tests.fixtures.xiaox_runtime import event as event
from tests.fixtures.xiaox_runtime import receipt as receipt
from tests.fixtures.xiaox_runtime import setup_runtime as setup_runtime


def test_write_goal_without_any_action_requires_business_action(setup_runtime):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "write"
    feedback = "原任务要求的写入尚无任何业务回执。"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback=feedback,
        )
    ] * 3
    transport = Transport(store, completed("已按要求改好工作簿。"))
    public_events = []
    result = asyncio.run(
        invoke(
            store,
            transport,
            completion_mode="business",
            on_event=public_events.append,
            tool_bridge=Bridge(),
        )
    )
    assert len(transport.inputs) == 3
    assert [json.loads(item)["feedback"] for item in transport.inputs[1:]] == [feedback, feedback]
    assert all(json.loads(item)["remaining_goals"] for item in transport.inputs[1:])
    assert transport.schemas[0] is None and all(schema for schema in transport.schemas[1:])
    assert transport.schemas[1]["properties"]["capability"]["enum"] == ["employee.execute"]
    assert result["ok"] is False and result["business_completed"] is False
    assert result["failure_kind"] == "business_action_required"
    assert store.run.status == "blocked"
    assert "已完成" not in repr(public_events)


@pytest.mark.parametrize("previous_read", [False, True])
def test_write_goal_proposal_is_submitted_once_through_mcp_entry(setup_runtime, previous_read):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()] if previous_read else [])
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要实际写入。",
        )
    ] * 3
    bridge = Bridge()
    proposal = '{"capability": "employee.execute", "params": {"employee_id": "x"}}'
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    names = [name for _, name, _ in bridge.calls]
    assert names == [
        "capability_search",
        "capability_search",
        "capability_describe",
        "execute_action",
    ]
    assert bridge.calls[1][2]["offset"] == 30
    _, _, execute_args = bridge.calls[-1]
    assert (execute_args["tool_id"], execute_args["action"]) == ("employee", "execute")
    assert execute_args["schema_digest"] == "digest-live"
    assert execute_args["call_id"].startswith("host-")
    assert execute_args["params"] == {"employee_id": "x"}
    events = [event.event_type for event in store.run.events]
    assert events.count("runtime.action.proposed") == 1
    assert result["ok"] is False
    # Proposals are internal: they must never become the public reply.
    assert "tool_id" not in str(result.get("output") or "")


@pytest.mark.parametrize(
    "boundary",
    [
        "separate_goal",
        "same_goal",
        "unbound_goal",
        "uncovered_write",
        "violation",
        "unverified_write",
    ],
)
def test_compensation_preserves_a_completed_write_and_only_proposes_a_clear_missing_goal(
    setup_runtime,
    boundary,
):
    invoke, _ = setup_runtime
    row = receipt(verified=boundary != "unverified_write")
    row.update(action="create", read_only=False)
    row["receipt"]["tool_calls"][0]["action"] = "create"
    row["fingerprint"] = canonical_digest({"tool_id": "sales", "action": "create", "params": {}})
    store = Store(rows=[row])
    store.run.message = "建立销售登记并通知财务复核"
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    completed_goal = goal(
        "建立销售登记",
        goal_id="registered",
        kind="write",
        evidence_ids=[row["child_run_id"]],
    )
    missing_goal = goal(
        "通知财务复核",
        goal_id="notify",
        kind="write",
        status="unmet",
        evidence_ids=[],
    )
    if boundary == "same_goal":
        missing_goal["source"] = completed_goal["source"]
    elif boundary == "unbound_goal":
        missing_goal["source"] = "批准新的付款"
    if boundary == "uncovered_write":
        completed_goal.update(status="unmet", evidence_ids=[])
    raw = review(completed_goal, missing_goal, feedback="保留销售登记，只补财务通知。")
    if boundary == "violation":
        raw["violations"] = ["原权限范围尚未核对"]
    store.reviews = [copy.deepcopy(raw) for _ in range(3)]
    bridge = Bridge()
    proposal = json.dumps(
        {
            "capability": "employee.execute",
            "params": {"employee_id": "finance", "task": "通知财务复核"},
        }
    )
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, tool_bridge=bridge))
    executions = [args for _, name, args in bridge.calls if name == "execute_action"]
    if boundary == "separate_goal":
        assert len(executions) == 1
        assert executions[0]["params"]["task"] == "通知财务复核"
        feedback = json.loads(transport.inputs[1])
        assert feedback["completed_goal_ids"] == ["registered"]
        assert [item["goal_id"] for item in feedback["remaining_goals"]] == ["notify"]
    else:
        assert executions == []
    assert store.rows == [row]
    assert not result["ok"]  # A pending approval is still not a completed write.


@pytest.mark.parametrize("prior_effect", ["none", "read", "write"])
@pytest.mark.parametrize("defect", ["new_goal", "source_id", "evidence"])
def test_invalid_original_gap_stops_before_another_sdk_turn_or_proposal(
    setup_runtime,
    prior_effect,
    defect,
):
    invoke, _ = setup_runtime
    rows = [] if prior_effect == "none" else [receipt()]
    if prior_effect == "write":
        rows[0].update(action="create", read_only=False)
        rows[0]["receipt"]["tool_calls"][0]["action"] = "create"
        rows[0]["fingerprint"] = canonical_digest(
            {"tool_id": "sales", "action": "create", "params": {}}
        )
    store = Store(rows=rows)
    store.run.message = "整理销售数据并通知财务复核"
    contract = build_goal_contract(store.run)
    store.run.metadata.update(
        runtime_goal_contract=contract, runtime_goal_digest=contract["digest"]
    )
    original = copy.deepcopy(store.rows)
    completed_goals = (
        []
        if not rows
        else [
            goal(
                "整理销售数据",
                goal_id="completed",
                kind=prior_effect,
                evidence_ids=[rows[0]["child_run_id"]],
            )
        ]
    )
    missing = goal(
        "通知财务复核",
        goal_id="remaining",
        kind="write",
        status="unmet",
        evidence_ids=[],
    )
    if defect == "new_goal":
        missing["source"] = "批准新增付款"
    elif defect == "source_id":
        missing["source_id"] = "history"
    else:
        missing["evidence_ids"] = ["another-task-receipt"]
    # Deliberately retain the legacy verifier's needs_work verdict. The host
    # must validate old reports too, even when their digest is internally valid.
    raw = review(*completed_goals, missing, feedback="执行缺失动作。")
    store.reviews = [copy.deepcopy(raw) for _ in range(3)]
    bridge = Bridge()
    proposal = json.dumps(
        {
            "capability": "employee.execute",
            "params": {"employee_id": "finance", "task": missing["source"]},
        }
    )
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, tool_bridge=bridge))
    assert len(transport.inputs) == 1 and bridge.calls == []
    assert not result["ok"] and not result["retryable"]
    assert result["exit_status"] == "goal_verification_invalid_gap"
    assert result["verification_state"] == "blocked"
    assert store.run.status == "blocked"
    assert store.rows == original and store.run.metadata["runtime_goal_contract"] == contract
    job = store.run.metadata["runtime_goal_verification_task"]
    assert job["terminal_code"] == "goal_verification_invalid_gap"
    assert [item["goal_id"] for item in job["gaps"]] == ["remaining"]


@pytest.mark.parametrize(
    ("state", "read_only", "verified", "blocked"),
    [
        ("completed", False, True, True),
        ("completed", None, True, True),
        ("completed", True, False, True),
        ("unknown", True, False, True),
        ("waiting_approval", False, False, True),
        ("failed", True, False, False),
        ("blocked", False, False, True),
    ],
)
def test_write_recovery_preserves_receipt_safety_boundary(state, read_only, verified, blocked):
    row = receipt(status=state, verified=verified, success=state == "completed")
    assert runtime._has_blocking_receipt([{**row, "read_only": read_only}]) is blocked


@pytest.mark.parametrize(
    "schema_violation",
    [None, {"path": "$.params.input", "validator": "required", "missing": ["plan"]}],
)
def test_denied_proposal_returns_error_and_real_write_capabilities(setup_runtime, schema_violation):
    invoke, _ = setup_runtime
    store = Store()
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要实际写入。",
        )
    ] * 3

    class DenialBridge(Bridge):
        def invoke(self, token, name, arguments):
            result = super().invoke(token, name, arguments)
            if name == "execute_action":
                return {
                    "status": "not_started",
                    "error_code": "schema_validation_failed",
                    "schema_violation": schema_violation,
                }
            return result

    bridge = DenialBridge()
    capability = "employee.execute" if schema_violation else "employee.execute.run_excel_job"
    proposal = json.dumps({"capability": capability, "params": {}})
    transport = Transport(store, completed(proposal))
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    methods = {name for _, name, _ in bridge.calls}
    error = {"status": "not_started", "error_code": "proposal_capability_unavailable"}
    if schema_violation:
        assert methods == {"capability_search", "capability_describe", "execute_action"}
        error.update(error_code="schema_validation_failed", schema_violation=schema_violation)
    else:
        assert methods == {"capability_search"}
    assert json.loads(transport.inputs[1])["feedback"] == "需要实际写入。"
    denied = json.loads(transport.inputs[2])
    assert json.loads(denied["feedback"])["feedback"] == "需要实际写入。"
    assert denied["proposal_error"] == error
    capabilities = transport.schemas[2]["properties"]["capability"]["enum"]
    assert "employee.execute" in capabilities and "excel_analysis.structure" not in capabilities
    # 被拒绝的提案不得被当作已提交，也不得据此发布“已完成”。
    assert "tool_id" not in str(result.get("output") or "")
    assert result["ok"] is False and store.run.status == "blocked"


@pytest.mark.parametrize("mode", ["execute", "plan"])
def test_proposal_preserves_registered_action_arguments(setup_runtime, mode):
    invoke, _ = setup_runtime
    store = Store()
    store.run.metadata["runtime_execution_mode"] = mode
    store.review_kind = "write"
    store.reviews = [
        review(goal(store.run.message, kind="write", status="unmet", evidence_ids=[]))
    ] * 3
    bridge = Bridge()
    params = {
        "employee_id": "registered-employee",
        "task": store.run.message,
        "input": {"upload_id": "owned-upload"},
    }
    transport = Transport(
        store, completed(json.dumps({"capability": "employee.execute", "params": params}))
    )
    asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    if mode == "plan":
        assert not bridge.calls and transport.schemas == [None] * 3
        return
    searches = [args for _, name, args in bridge.calls if name == "capability_search"]
    assert [(args["query"], args["offset"]) for args in searches] == [("", 0), ("", 30)]
    assert transport.schemas[1]["required"] == ["capability", "params"]
    (execute,) = [args for _, name, args in bridge.calls if name == "execute_action"]
    assert (execute["tool_id"], execute["action"], execute["schema_digest"]) == (
        "employee",
        "execute",
        "digest-live",
    )
    assert execute["params"] == params


def test_proposal_repair_uses_only_the_selected_catalog_contract():
    from jsonschema import Draft202012Validator

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    assert (spec := get_tool_action_spec("employee", "execute")) is not None
    options = {
        "employee.execute": ("employee", "execute"),
        "products.create": ("products", "create"),
    }
    calls = []

    def invoke(token, method, params):
        calls.append((token, method, params))
        return {"capability": {"input_schema": spec.input_schema}}

    bridge = SimpleNamespace(invoke=invoke)
    denial = {"tool_id": "employee", "action": "execute", "schema_violation": {"path": "$"}}
    schema = runtime._proposal_contract(bridge, "token", options, denial)
    assert calls == [("token", "capability_describe", {"tool_id": "employee", "action": "execute"})]
    assert schema["then"]["properties"]["params"] == spec.input_schema
    validate = Draft202012Validator(schema).is_valid
    assert not validate({"capability": "employee.execute", "params": {"input": {}}})
    assert validate({"capability": "products.create", "params": {}})
    assert not validate({"capability": "employee.execute", "workbook": {}})
    assert not validate({"capability": "products.delete", "params": {}})


def test_failed_write_without_no_effect_proof_does_not_resume_execution(setup_runtime):
    invoke, _ = setup_runtime
    operation = {"tool_id": "employee", "action": "execute", "params": {}}
    failed = receipt(status="failed", verified=False, success=False)
    failed.update(**operation, read_only=False, fingerprint=canonical_digest(operation))
    failed["receipt"].update(retryable=True, message="非法 Excel 表格名称：'销售明细表'")
    store = Store(rows=[failed])
    store.review_kind = "write"
    store.reviews = [
        review(
            goal(store.run.message, kind="write", status="unmet", evidence_ids=[]),
            feedback="需要写入。",
        )
    ] * 2
    transport = Transport(store, completed("已改好。"))
    bridge = Bridge()
    result = asyncio.run(invoke(store, transport, completion_mode="business", tool_bridge=bridge))
    assert len(transport.inputs) == 1 and transport.schemas == [None]
    assert not bridge.calls
    assert store.rows == [failed]
    assert "非法 Excel 表格名称" in store.rows[0]["receipt"]["message"]
    assert result["ok"] is False


def test_verified_operations_do_not_satisfy_a_missing_original_goal(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    store.review_missing = True
    store.run.metadata.update(
        runtime_failure_kind="rate_limit", runtime_failure_reason="已恢复的先前限流"
    )
    result = asyncio.run(invoke(store, Transport(store, completed("已全部完成"))))
    assert result["verified_operations"] is True and result["business_completed"] is False
    assert result["exit_status"] == "goal_verification_required"
    assert result["output"] == (
        "本轮未通过完整性核验，原任务与回执已保留，请核对后重试。整体目标尚未核验完成。"
    )
    assert all(message["role"] == "user" for message in result["session_messages"])
    assert store.run.status == "blocked"


def test_verifier_feedback_completes_missing_work_in_same_thread(setup_runtime):
    invoke, _ = setup_runtime
    store = Store(rows=[receipt()])
    store.review_missing = True
    store.run.metadata.update(
        runtime_failure_kind="rate_limit", runtime_failure_reason="已恢复的先前限流"
    )
    original = copy.deepcopy(store.run.metadata["runtime_goal_contract"])

    class CorrectingTransport(Transport):
        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            if not self.inputs:
                assert text and goal_feedback is None
                assert "继续核对原始目标" not in text
            else:
                assert text is None
                assert "继续核对原始目标" in goal_feedback
                # The second SDK turn supplies only the missing read; the first
                # call keeps its original persisted receipt and identity.
                missing = receipt(child_run_id="second-child", child_task_id="second-task")
                missing["call_id"] = "missing-read"
                missing["receipt"]["tool_calls"][0]["call_id"] = "second-child-call"
                store.rows.append(missing)
                store.review_missing = False
            async for item in super().stream_turn(text, goal_feedback=goal_feedback):
                yield item

    transport = CorrectingTransport(store)
    result = asyncio.run(invoke(store, transport))
    assert result["business_completed"] is True and result["ok"] is True, result
    assert len(transport.inputs) == 2 and len(transport.started) == 1
    assert transport.resumed == []
    assert store.run.metadata["runtime_goal_contract"] == original
    assert store.run.metadata["xiaox_runtime"]["generation"] == 1
    assert result["failure_kind"] == ""
    assert "runtime_failure_kind" not in store.run.metadata
    assert [row["call_id"] for row in store.rows] == ["model-call", "missing-read"]
    assert [
        item.data["status"]
        for item in store.run.events
        if item.event_type == "runtime.goal.verified"
    ] == ["needs_work", "verified"]
