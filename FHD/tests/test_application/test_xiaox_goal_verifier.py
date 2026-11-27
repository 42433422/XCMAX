"""Independent goal decisions bound to original requests and host business receipts."""

from __future__ import annotations

import copy
import json

import pytest

from app.application.agent_runtime.goal_verifier import _review_evidence_view
from app.application.agent_runtime.goal_verifier import verify_runtime_goal as verify_runtime_goal
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_report_coverage,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import goal as goal
from tests.fixtures.xiaox_goal_review import receipt as receipt
from tests.fixtures.xiaox_goal_review import response as response
from tests.fixtures.xiaox_goal_review import review as review
from tests.fixtures.xiaox_goal_review import verifier as verifier


def test_review_evidence_keeps_business_facts_without_duplicate_transport_metadata():
    row = {
        "evidence_id": "child-1",
        "tool_id": "employee",
        "action": "execute",
        "params": {"employee_id": "reader", "input": {"file_path": "owned-file"}},
        "read_only": True,
        "state": "completed",
        "receipt": {
            "success": True,
            "verified": True,
            "status": "completed",
            "message": "已回读",
            "verification": {
                "status": "verified",
                "accepted": True,
                "steps": [
                    {
                        "status": "verified",
                        "accepted": True,
                        "code": "checked",
                        "checks": [
                            {
                                "source": "run_artifact",
                                "status": "passed",
                                "evidence": {"sha256": "a" * 64},
                            }
                        ],
                        "credential_scope_sha256": "private-scope",
                    },
                ],
            },
            "tool_calls": [
                {
                    "tool_id": "employee",
                    "action": "execute",
                    "status": "completed",
                    "params": {"employee_id": "reader", "input": {"file_path": "owned-file"}},
                    "output": {"success": True, "data": {"sheet": "Sales", "cell": "=SUM(A1:A3)"}},
                    "error": "",
                    "metadata": {"credential": "private-token"},
                }
            ],
            "artifacts": [
                {
                    "artifact_id": "artifact-1",
                    "artifact_type": "file",
                    "name": "result.xlsx",
                    "uri": "/api/agent/runs/child-1/artifacts/artifact-1",
                    "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "metadata": {"sha256": "a" * 64, "owner_user_id": "private-owner"},
                }
            ],
        },
    }
    view = _review_evidence_view([row])[0]
    serialized = json.dumps(view, ensure_ascii=False)
    assert "=SUM(A1:A3)" in serialized and "artifact-1" in serialized
    assert '"status": "verified"' in serialized
    assert all(
        secret not in serialized for secret in ("private-token", "private-scope", "private-owner")
    )
    assert len(serialized) < len(json.dumps(row, ensure_ascii=False))


@pytest.mark.parametrize(
    ("deliverable", "kind", "accepted"),
    [
        ("action_plan", "reply", True),
        ("action_plan", "planned_action", False),
        ("action_plan", "read", False),
        ("action_plan", "write", False),
        (None, "planned_action", False),
    ],
)
def test_planned_actions_are_bound_to_the_requested_deliverable(
    verifier, deliverable, kind, accepted
):
    verifier.run.message = "写出库存盘点方案"
    if deliverable:
        verifier.run.metadata["runtime_requested_deliverable"] = deliverable
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.output = "按仓位列清单，逐项记录实点数，比较账面数并复核差异。"
    verifier.rows = []
    verifier.replies = [
        response(review(goal(verifier.run.message, kind=kind, evidence_ids=["response"])))
    ]
    report = verifier.verify()
    assert report["accepted"] is accepted
    assert verifier.classify(report)[1]["business_completed"] is False


@pytest.mark.parametrize("variant", ["visible", "different_path", "unknown_id", "read"])
def test_manual_plan_routes_are_bound_to_frozen_display_context(verifier, variant):
    verifier.run.message = "给我查看待办列表的能力方案"
    verifier.run.metadata["runtime_requested_deliverable"] = "action_plan"
    entry = {"id": "pending", "kind": "page", "label": "待办", "breadcrumb": ["工作台"]}
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run, context_evidence=[{"source": "desktop_navigation", "entries": [entry]}]
    )
    path = "设置 → 待办" if variant == "different_path" else "工作台 → 待办"
    verifier.output = f"从「{path}」查看当前账号的待办列表。只读，无需审批。"
    verifier.rows = []
    reference = {
        **goal(
            verifier.run.message,
            kind="read" if variant == "read" else "planned_action",
            evidence_ids=["response"],
        ),
        "planned_navigation": [
            {
                "navigation_id": "foreign" if variant == "unknown_id" else "pending",
                "response_excerpt": path,
            }
        ],
    }
    verifier.replies = [response(review(reference))]
    report = verifier.verify()
    assert report["accepted"] is (variant == "visible"), report["feedback"]
    body = json.loads(verifier.requests[0].content)
    evidence = json.loads(body["input"][1]["content"])
    schema = evidence["output_schema"]["$defs"]
    assert evidence["desktop_navigation"] == [entry]
    assert "read" not in schema["GoalAssessment"]["properties"]["kind"]["enum"]
    assert schema["PlannedNavigation"]["properties"]["navigation_id"]["enum"] == ["pending"]
    assert not report.get("plan_capabilities")
    assert verifier.classify(report)[1]["business_completed"] is False


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "unknown",
        "denied",
        "tenant",
        "params",
        "approval",
        "quote",
        "cycle",
        "wrong_adapter",
        "ambiguous_adapter",
    ],
)
def test_business_plan_validates_current_contract_without_executing(
    verifier, trusted_actor, monkeypatch, failure
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(permissions=["customer.view", "customer.edit"])
    verifier.run.user_id = str(actor.user_id)
    verifier.run.message = "给出查询并创建客户的工具方案"
    verifier.run.metadata.update(
        runtime_context=actor.context, runtime_requested_deliverable="action_plan"
    )
    if failure == "tenant":
        verifier.run.metadata["runtime_context"] = {**actor.context, "tenant_id": 999999}
    if failure == "denied":
        verifier.run.metadata["xiaox_runtime"]["allowed_actions"] = ["customers.query"]
        verifier.run.metadata["runtime_allowed_actions"] = ["customers.query"]
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    source = {
        **goal(verifier.run.message, kind="planned_action", evidence_ids=["response"]),
        "planned_calls": [
            {
                "node_id": "find",
                "tool_id": "customers",
                "action": "query",
                "params": {"keyword": "fixture"},
                "response_excerpt": "customers.query",
                "depends_on": ["create"] if failure == "cycle" else [],
                "approval_required": False,
            },
            {
                "node_id": "create",
                "tool_id": "customers",
                "action": "create",
                "params": {}
                if failure == "params"
                else {"unit_name": "{{find.data[0].unit_name}}"},
                "response_excerpt": "customers.create",
                "depends_on": ["find"],
                "approval_required": failure != "approval",
            },
        ],
    }
    quoted = "`mcp__xcmax__execute_action`，`tool_id=customers`、`action=query`"
    if failure == "wrong_adapter":
        quoted = quoted.replace("execute_action", "capability_describe")
    if failure == "ambiguous_adapter":
        quoted += "，另一个 action=create"
    source["planned_calls"][0]["response_excerpt"] = quoted
    verifier.output = f"先 {quoted} 查重，再 customers.create 创建，需审批。"
    if failure == "unknown":
        verifier.output = verifier.output.replace("customers.create", "customers.new_fixture")
        source["planned_calls"][1].update(
            action="new_fixture", response_excerpt="customers.new_fixture"
        )
    if failure == "quote":
        verifier.output = verifier.output.replace("customers.create", "customers.creates")
    verifier.replies = [response(review(source))]
    report = verifier.verify()
    assert report["accepted"] is (not failure), report["feedback"]
    if failure == "denied":
        envelope = json.loads(verifier.requests[0].content)
        schema = json.loads(envelope["input"][1]["content"])["output_schema"]
        assert schema["$defs"]["PlannedToolCall"]["oneOf"] == [
            {"properties": {"tool_id": {"const": "customers"}, "action": {"enum": ["query"]}}}
        ]
    status, result = verifier.classify(report)
    assert status == ("blocked" if failure else "completed")
    assert result["business_completed"] is False
    assert verifier.run.metadata["xiaox_runtime"].get("calls", {}) == {}
    if not failure:
        assert len(report["plan_capabilities"]) == 2
        verifier.run.metadata["runtime_goal_verification"] = copy.deepcopy(report)
        verifier.run.metadata["xiaox_runtime"]["allowed_actions"] = ["customers.query"]
        verifier.replies = [response(review(source))]
        assert verifier.verify()["accepted"] is False
        report.pop("plan_capabilities")
        report["report_digest"] = canonical_digest(
            {key: value for key, value in report.items() if key != "report_digest"}
        )
        assert verifier.classify(report)[0] == "blocked"


def test_all_original_goals_need_independent_receipts(verifier):
    verifier.rows = verifier.rows[:1]
    verifier.replies = [
        response(
            review(
                goal(),
                goal("再查询second", goal_id="second", status="unmet", evidence_ids=[]),
                feedback="还没有second的查询回执",
            )
        )
    ]
    report = verifier.verify()
    assert report["status"] == "needs_work" and not report["accepted"]
    state, result = verifier.classify(report)
    assert state == "blocked" and not result["business_completed"]
    assert "second" in result["verification_feedback"]
    assert not verifier.classify(None)[1]["ok"]


@pytest.mark.parametrize(
    "wrapper", ["{}", "```json\n{}\n```", "```\n{}\n```", " \n```JSON\n{}\n```\n "]
)
def test_verified_report_binds_all_goals_and_uses_only_scoped_gateway(verifier, wrapper):
    raw = json.dumps(review(goal(), goal("再查询second", goal_id="second")))
    verifier.replies = [response({}, text=wrapper.format(raw))]
    report = verifier.verify()
    state, result = verifier.classify(report)
    assert state == "completed" and result["business_completed"]
    assert report["accepted"] and len(report["review"]["goals"]) == 2
    request = verifier.requests[0]
    assert str(request.url).endswith("/api/agent-runtime/xiaox/responses")
    assert request.headers["authorization"] == "Bearer scoped-model-grant"
    body = json.loads(request.content)
    assert body["tools"] == [] and body["store"] is False
    assert body["max_output_tokens"] <= 8000
    assert verifier.client_options[0]["max_retries"] == 0
    assert verifier.client_options[0]["trust_env"] is False
    assert verifier.client_options[0]["redirects"] is False


@pytest.mark.parametrize("mutation", ["params", "receipt", "child", "answer", "output", "report"])
def test_old_report_cannot_cover_changed_evidence_or_answer(verifier, mutation):
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    report = verifier.verify()
    if mutation == "params":
        verifier.rows[0]["params"]["target"] = "other"
    elif mutation == "receipt":
        verifier.rows[0]["receipt"]["tool_calls"][0]["output"]["data"] = {"target": "other"}
    elif mutation == "child":
        verifier.rows[0]["child_run_id"] = "different-parent-child"
    elif mutation == "answer":
        verifier.run.add_event(
            "runtime.input_answered", "补答", {"question": "范围", "answer": "只查询first"}
        )
    elif mutation == "output":
        verifier.output = "另一个未经核验的结论"
    else:
        report["accepted"] = False
    assert verifier.classify(report)[0] == "blocked"


@pytest.mark.parametrize("state", ["unknown", "waiting_user", "running"])
def test_unknown_approval_and_active_receipts_preempt_model_verification(verifier, state):
    verifier.rows[0]["state"] = state
    verifier.rows[0]["receipt"]["status"] = state
    report = verifier.verify()
    assert not report["accepted"] and not verifier.requests
    status, result = verifier.classify(report)
    assert (
        status
        == {"unknown": "blocked", "waiting_user": "waiting_user", "running": "running"}[state]
    )
    assert not result["ok"]


def test_unsettled_model_charge_cannot_be_overridden_by_review(verifier):
    verifier.run.metadata["xiaox_runtime"]["model_requests"] = {"pending": {"state": "unknown"}}
    report = verifier.verify()
    assert not verifier.requests
    assert verifier.classify(report)[1]["exit_status"] == "unknown"


def test_conflicting_aliases_are_not_multiple_goal_proof(verifier):
    alias = copy.deepcopy(verifier.rows[0])
    alias["params"]["target"] = "second"
    verifier.rows.append(alias)
    report = verifier.verify()
    assert report["error_code"] == "goal_evidence_conflict" and not verifier.requests


@pytest.mark.parametrize(
    "missing", ["fingerprint", "receipt_run_id", "receipt_task_id", "receipt_type"]
)
def test_unbound_child_receipt_is_never_accepted_as_goal_evidence(verifier, missing):
    row = verifier.rows[0]
    if missing == "fingerprint":
        row.pop("fingerprint")
    elif missing == "receipt_run_id":
        row["receipt"].pop("run_id")
    elif missing == "receipt_task_id":
        row["receipt"].pop("task_id")
    else:
        row["receipt"] = ["malformed"]

    report = verifier.verify()
    assert not report["accepted"] and not verifier.requests
    assert report["error_code"] == (
        "goal_evidence_pending" if missing == "receipt_type" else "goal_evidence_conflict"
    )
    status, result = verifier.classify(report)
    assert status == "blocked" and result["business_completed"] is False


def test_claimed_verified_receipt_cannot_override_rejected_host_verification(verifier):
    verifier.rows[0]["receipt"]["verification"] = {
        "protocol": "xcagi.result-verification.v1",
        "status": "inconclusive",
        "accepted": False,
    }
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    report = verifier.verify()
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert "缺少独立核验" in report["feedback"]
    status, result = verifier.classify(report)
    assert status == "blocked" and not result["business_completed"]
    assert result["tool_calls"][0]["success"] is True
    assert result["tool_calls"][0]["verified"] is False
    assert result["verified_operations"] is False


def test_unknown_effect_inside_completed_receipt_blocks_goal_success(verifier):
    verifier.rows[0]["receipt"]["execution"] = {"outcome": "unknown", "committed": True}
    report = verifier.verify()
    assert not report["accepted"] and not verifier.requests
    status, result = verifier.classify(report)
    assert status == "blocked" and result["exit_status"] == "unknown"
    assert result["reconciliation_required"] is True


def test_one_write_receipt_cannot_complete_two_distinct_effects(verifier):
    verifier.run.message = "确认first，再确认second"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = [receipt("first", read_only=False)]
    verifier.replies = [
        response(
            review(
                goal("确认first", kind="write"),
                goal("再确认second", goal_id="second", kind="write", evidence_ids=["child-first"]),
            )
        )
    ]
    report = verifier.verify()
    assert report["status"] == "unavailable" and "重用" in report["feedback"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert verifier.classify(report)[0] == "blocked"


def test_query_cannot_be_write_completion_and_extra_write_is_not_ignored(verifier):
    verifier.run.message = "确认first"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = [receipt("first")]
    verifier.replies = [response(review(goal("确认first", kind="write")))]
    assert not verifier.verify()["accepted"]
    verifier.rows = [receipt("first", read_only=False), receipt("second", read_only=False)]
    verifier.replies = [response(review(goal("确认first", kind="write")))]
    assert "未被原始目标覆盖" in verifier.verify()["feedback"]


def test_known_failed_exploration_can_be_followed_by_verified_success(verifier):
    failed = receipt("failed")
    failed.update(state="failed")
    failed["receipt"].update(status="failed", success=False, verified=False)
    verifier.rows.insert(0, failed)
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    assert verifier.classify(verifier.verify())[0] == "completed"


def test_pure_reply_needs_no_tool_but_does_need_complete_review(verifier):
    verifier.run.message = "解释库存是什么意思"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "库存是当前持有的货物数量。"
    verifier.replies = [
        response(review(goal(verifier.run.message, kind="reply", evidence_ids=["response"])))
    ]
    report = verifier.verify()
    assert report["mode"] == "reply" and report["accepted"]
    (request,) = verifier.requests
    payload = json.loads(json.loads(request.content)["input"][1]["content"])
    assert payload["original_request"]["text"] == verifier.run.message
    assert payload["response"] == verifier.output
    assert verifier.classify(report, mode="business")[1]["reply_completed"]
    assert not verifier.classify(report, runtime_status="failed")[1]["ok"]


def test_verifier_tells_model_to_merge_alternative_wording_into_one_reply_goal(verifier):
    verifier.run.message = "每句以A开头；若用中文，可改为每句以同一汉字开头并注明。"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "以中文作答：以开头。"
    verifier.replies = [
        response(review(goal(verifier.run.message, kind="reply", evidence_ids=["response"])))
    ]
    assert verifier.verify()["accepted"]
    rules = json.loads(json.loads(verifier.requests[0].content)["input"][1]["content"])["rules"]
    assert any("替代" in rule for rule in rules)


def test_verifier_treats_code_answer_without_file_request_as_reply(verifier):
    verifier.run.message = (
        "编写一个 Python 程序，读取某个目录下的所有文本文件，并返回出现次数最多的前 5 个单词。"
    )
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "```python\nfrom collections import Counter\n```"
    verifier.replies = [
        response(review(goal(verifier.run.message, kind="reply", evidence_ids=["response"])))
    ]
    assert verifier.verify()["accepted"]
    rules = json.loads(json.loads(verifier.requests[0].content)["input"][1]["content"])["rules"]
    assert any("代码块本身就是交付" in rule for rule in rules)


def test_unmet_goal_is_named_in_verification_feedback(verifier):
    verifier.rows = []
    verifier.replies = [
        response(review(goal("查询first", kind="reply", status="unmet", evidence_ids=[])))
    ]
    report = verifier.verify()
    assert not report["accepted"]
    assert "first" in report["feedback"]


def test_blocked_goal_review_diagnostics_are_not_chat_copy(verifier):
    from app.application.agent_runtime.chat import runtime_chat_payload

    verifier.replies = [
        response(review(goal(status="unmet", evidence_ids=[]), feedback="memory-private-test"))
    ]
    status, result = verifier.classify(verifier.verify())
    assert status == "blocked"
    assert "memory-private-test" in result["verification_feedback"]
    result["failure_reason"] = result["verification_feedback"]
    public = runtime_chat_payload(result)
    assert public["data"]["error_code"] == "goal_verification_required"
    serialized = json.dumps(public, ensure_ascii=False)
    assert "memory-private-test" not in serialized and verifier.output not in serialized


def test_verifier_instructs_model_to_treat_text_requirements_as_reply_goals(verifier):
    verifier.run.message = "解释库存。每段以同一个字开头。"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "库：库存是当前持有的货物数量。\n\n库：入库会增加库存。"

    def evaluate_instructions(request):
        messages = json.loads(request.content)["input"]
        rules = json.loads(messages[1]["content"])["rules"]
        is_reply_constraint = any("仅约束回复正文" in rule for rule in rules)
        verifier.replies.append(
            response(
                review(
                    goal("解释库存", kind="reply", evidence_ids=["response"]),
                    goal(
                        "每段以同一个字开头",
                        goal_id="format",
                        kind="reply" if is_reply_constraint else "constraint",
                        evidence_ids=["response"],
                    ),
                )
            )
        )

    verifier.observe_request = evaluate_instructions
    assert verifier.verify()["accepted"]


@pytest.mark.parametrize("kind", [None, "reply", "constraint"])
def test_bound_business_objective_cannot_pass_without_receipt(verifier, kind):
    objective = "观察原订单状态"
    verifier.run.metadata["runtime_context"]["_runtime_goal_constraints"] = {
        "objective": objective,
        "entity_type": "sales_order",
        "entity_id": "original",
        "requires_approval": True,
    }
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    assessments = [goal("查询first", kind="reply", evidence_ids=["response"])]
    if kind is not None:
        assessments.append(
            goal(
                objective,
                goal_id="bound-objective",
                kind=kind,
                source_id="objective",
                evidence_ids=["response"] if kind == "reply" else [],
            )
        )
    verifier.replies = [response(review(*assessments))]
    assert not verifier.verify()["accepted"]


def test_report_revalidation_rejects_tampered_verdict(verifier):
    verifier.replies = [
        response(
            review(goal(), goal("再查询second", goal_id="second", status="unmet", evidence_ids=[]))
        )
    ]
    report = verifier.verify()
    report["status"], report["accepted"] = "verified", True
    report["report_digest"] = canonical_digest(
        {key: value for key, value in report.items() if key != "report_digest"}
    )
    coverage = goal_report_coverage(
        verifier.run.metadata["runtime_goal_contract"], verifier.rows, verifier.output, [], report
    )
    assert not coverage["completed"]


def test_optional_reply_branches_are_one_goal_not_two_required_operations(verifier):
    verifier.run.message = "用英文解释库存；若用中文作答，可改为给出中文定义"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "Inventory is the goods held by a business."
    verifier.replies = [
        response(review(goal(verifier.run.message, kind="reply", evidence_ids=["response"])))
    ]
    report = verifier.verify()
    assert report["accepted"] and report["mode"] == "reply"
    payload = json.loads(json.loads(verifier.requests[0].content)["input"][1]["content"])
    assert any("二选一" in rule and "任一" in rule for rule in payload["rules"])


@pytest.mark.parametrize(
    "failure",
    [
        "receipt_missing",
        "late_success_after_timeout",
        "late_success_after_cancel",
        "contradictory_terminal",
        "state_missing",
    ],
)
def test_terminal_receipt_negative_controls_never_mark_completed(verifier, failure):
    from app.domain.task_lifecycle.agent_runtime_results import receipt_state, receipt_verified

    row = verifier.rows[0]
    if failure == "receipt_missing":
        row.pop("receipt")
    elif failure == "late_success_after_timeout":
        row["state"] = "timed_out"
    elif failure == "late_success_after_cancel":
        row["state"] = "cancelled"
    elif failure == "contradictory_terminal":
        row["receipt"]["status"] = "failed"
    else:
        row.pop("state")
    assert receipt_state(row) == "unknown"
    assert receipt_verified(row) is False

    # Even if another child is genuinely complete, the parent must preserve
    # the original uncertain side effect rather than resubmit either action.
    state, result = verifier.classify(None)
    assert state == "blocked"
    assert result["execution_state"] == "unknown"
    assert result["exit_status"] == "unknown"
    assert result["reconciliation_required"] is True
    assert result["needs_verification"] is True
    assert result["retryable"] is False
    assert result["business_completed"] is False
    assert result["verified_operations"] is False
    assert result["ok"] is False


def test_late_success_cannot_overwrite_an_older_unknown_execution_receipt(verifier):
    from app.domain.task_lifecycle.agent_runtime_results import receipt_state

    original = verifier.rows[0]
    original["state"] = "unknown"
    original["receipt"]["status"] = "completed"
    original["receipt"]["success"] = True
    original["receipt"]["verified"] = True
    assert receipt_state(original) == "unknown"
    assert verifier.classify(None)[0] == "blocked"
