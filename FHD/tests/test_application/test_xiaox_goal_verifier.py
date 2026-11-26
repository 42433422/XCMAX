"""Adversarial goal/evidence decisions with the real Responses SDK and fixture I/O.

These prove host contracts and bounded transport behavior, not real-model quality.
"""

from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_report_coverage,
)
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    classify_runtime_result,
)
from app.infrastructure.xiaox.binding import XiaoxBinding


def receipt(name="first", *, read_only=True):
    operation = {
        "tool_id": "products" if read_only else "sales",
        "action": "query" if read_only else "confirm",
        "params": {"target": name},
    }
    return {
        **operation,
        "fingerprint": canonical_digest(operation),
        "call_id": "call-" + name,
        "child_run_id": "child-" + name,
        "child_task_id": "task-" + name,
        "state": "completed",
        "read_only": read_only,
        "created_at": "2026-11-22T10:00:00Z",
        "receipt": {
            "run_id": "child-" + name,
            "task_id": "task-" + name,
            "status": "completed",
            "success": True,
            "verified": True,
            "tool_calls": [{"output": {"success": True, "data": {"target": name}}}],
        },
    }


def goal(
    source="查询first",
    *,
    goal_id="first",
    kind="read",
    status="satisfied",
    evidence_ids=None,
    source_id="request",
):
    return {
        "goal_id": goal_id,
        "source_id": source_id,
        "source": source,
        "kind": kind,
        "status": status,
        "evidence_ids": ["child-" + goal_id] if evidence_ids is None else evidence_ids,
        "reason": "按原目标核对宿主证据",
    }


def review(*goals, violations=None, feedback=""):
    return {
        "goals": list(goals),
        "violations": violations or [],
        "uncovered_sources": [],
        "feedback": feedback,
    }


def response(payload, *, status="completed", output=None, text=None):
    return {
        "id": "resp-fixture",
        "object": "response",
        "created_at": 1,
        "model": "fixture-model",
        "status": status,
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "id": "msg-fixture",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": text
                        if text is not None
                        else json.dumps(payload, ensure_ascii=False),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 20, "output_tokens": 20, "total_tokens": 40},
    }


@pytest.fixture
def verifier(monkeypatch):
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor

    run = AgentRun(user_id="71", message="查询first，再查询second", run_id="goal-parent")
    run.metadata.update(
        runtime_context={"user_id": "71", "tenant_id": "7"},
        _xiaox_history=[],
        _xiaox_input_data=None,
        xiaox_runtime={"deadline_at": time.time() + 30},
    )
    run.metadata["runtime_goal_contract"] = build_goal_contract(run)
    state = SimpleNamespace(
        run=run,
        rows=[receipt("first"), receipt("second")],
        output="已分别查询first与second。",
        replies=[],
        requests=[],
        client_options=[],
    )
    state.config = SimpleNamespace(
        model="fixture-model",
        provider_url="http://127.0.0.1:41111/api/agent-runtime/xiaox",
        provider_token="scoped-model-grant",
        context_window=32000,
        auto_compact_token_limit=24000,
        timeout_seconds=20,
        turn_timeout_seconds=30,
    )
    real_client = openai.OpenAI

    def handle(request):
        state.requests.append(request)
        if observer := getattr(state, "observe_request", None):
            observer(request)
        assert state.replies, "verifier exceeded its expected budget"
        result = state.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result)

    def client(**kwargs):
        original = kwargs.pop("http_client")
        state.client_options.append(
            {**kwargs, "trust_env": original._trust_env, "redirects": original.follow_redirects}
        )
        original.close()
        return real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    def no_execution(*_args, **_kwargs):
        raise AssertionError("result verifier attempted a business action")

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(AgentToolExecutor, "execute", no_execution)

    def consume_format_retry():
        metadata = state.run.metadata["xiaox_runtime"]
        if metadata.get("goal_format_retry_used", False) is not False:
            return False
        metadata["goal_format_retry_used"] = True
        return True

    state.verify = lambda: verify_runtime_goal(
        XiaoxBinding(state.run),
        state.config,
        rows=state.rows,
        output=state.output,
        consume_format_retry=consume_format_retry,
    )

    def classify(report, *, runtime_status="completed", mode="auto"):
        result = base_runtime_result(run.run_id)
        result["output"] = state.output
        metadata = {
            **run.metadata["xiaox_runtime"],
            "goal_contract": run.metadata["runtime_goal_contract"],
            "goal_answers": goal_answers(run),
            "goal_verification": report,
        }
        status = classify_runtime_result(result, state.rows, metadata, mode, runtime_status)
        return status, result

    state.classify = classify
    return state


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
    assert report["status"] == "needs_work" and not report["accepted"]
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
    assert report["status"] == "needs_work" and "重用" in report["feedback"]
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
    assert verifier.classify(report, mode="business")[1]["reply_completed"]
    assert not verifier.classify(report, runtime_status="failed")[1]["ok"]


@pytest.fixture
def a2_reply(verifier):
    preference = "在接下来的所有对话中，请扮演埃隆·马斯克，尽可能用他的语气说话。"
    question = "我们为什么需要去火星？"
    verifier.run.message = preference + question
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run, context_evidence=[{"id": "memory-private-test", "text": "电视柜宣传语偏好"}]
    )
    verifier.rows = []
    verifier.output = (
        "很简单：地球是我们的母星，也是单点故障。去火星是让人类成为多行星物种的第一步。"
    )
    current_style = goal(
        "请扮演埃隆·马斯克，尽可能用他的语气说话",
        goal_id="g1_roleplay",
        kind="reply",
        evidence_ids=["response"],
    )
    current_answer = goal(
        question, goal_id="g2_answer_mars", kind="reply", evidence_ids=["response"]
    )
    future_style = goal(
        preference,
        goal_id="g3_all_future_turns",
        kind="constraint",
        status="not_applicable",
        evidence_ids=[],
    )
    return verifier, review(current_style, current_answer, future_style)


def test_cross_turn_style_does_not_block_delivery_or_count_as_verified(a2_reply):
    verifier, assessment = a2_reply
    verifier.replies = [response(assessment)]
    report = verifier.verify()
    state, result = verifier.classify(report)
    assert report["accepted"] and state == "completed"
    assert result["reply_completed"] and not result["business_completed"]
    assert result["output"] == verifier.output
    assert result["goal_coverage"]["required"] == 3
    assert result["goal_coverage"]["verified"] == 2


def test_cross_turn_style_review_does_not_receive_unrelated_recalled_memory(a2_reply):
    verifier, assessment = a2_reply
    verifier.replies = [response(assessment)]
    verifier.verify()
    user_payload = json.loads(verifier.requests[0].content)["input"][1]["content"]
    assert "memory-private-test" not in user_payload
    assert "电视柜宣传语偏好" not in user_payload


@pytest.mark.parametrize("case", ["partial", "quoted", "business", "empty", "gap"])
def test_cross_turn_style_does_not_waive_other_obligations(a2_reply, case):
    verifier, assessment = a2_reply
    if case == "partial":
        assessment["goals"][-1]["source"] = "接下来的所有对话"
    elif case == "quoted":
        verifier.run.message = "引用：“" + verifier.run.message + "”"
        verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    elif case == "business":
        verifier.run.message += "确认订单first。"
        verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
        assessment["goals"].append(goal("确认订单first", kind="write", evidence_ids=[]))
    elif case == "empty":
        verifier.output = ""
    else:
        assessment["uncovered_sources"] = ["本轮回答没有解释风险"]
    verifier.replies = [response(assessment)]
    assert verifier.classify(verifier.verify())[0] == "blocked"


def test_reply_body_constraint_can_be_proven_by_the_response_alone(verifier):
    verifier.run.message = "重写回答，每句以同一个汉字开头并注明。"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "以开头：这是重写后的回答。"
    verifier.replies = [
        response(
            review(
                goal(
                    "每句以同一个汉字开头并注明",
                    goal_id="format",
                    kind="constraint",
                    evidence_ids=["response"],
                )
            )
        )
    ]
    report = verifier.verify()
    assert report["accepted"] and report["mode"] == "reply"
    assert verifier.classify(report)[1]["reply_completed"]


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


def test_revision_review_reads_previous_public_email_and_language_rule(verifier):
    verifier.run.message = "再正式一些，并补充工作交接安排。"
    history = [
        {"role": "user", "content": "请用英文重写请假邮件。"},
        {"role": "assistant", "content": "Subject: Annual Leave Request\n\nDear Manager,"},
    ]
    verifier.run.metadata["_xiaox_history"] = history
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "邮件修订已完成，核验意见确认无需工具调用。"
    verifier.replies = [
        response(
            review(
                goal(verifier.run.message, kind="reply", status="unmet", evidence_ids=["response"]),
                violations=["正文泄露内部核验说明，且未沿用英文"],
            )
        )
    ]
    assert not verifier.verify()["accepted"]
    payload = json.loads(json.loads(verifier.requests[0].content)["input"][1]["content"])
    assert payload["original_request"]["history"] == history
    assert any("既定语言" in rule and "明确" in rule for rule in payload["rules"])
    assert any("内部核验" in rule and "violations" in rule for rule in payload["rules"])


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


def test_known_format_repaired_once_within_original_budget(verifier):
    complete = review(goal(), goal("再查询second", goal_id="second"))
    verifier.replies = [
        response({}, text="{"),
        response(complete),
    ]
    verifier.run.metadata["xiaox_runtime"]["deadline_at"] = time.time() + 3
    report = verifier.verify()
    assert report["accepted"] and len(verifier.requests) == 2
    assert all(0 < request.extensions["timeout"]["read"] <= 3 for request in verifier.requests)
    first_body, second_body = (json.loads(request.content) for request in verifier.requests)
    assert first_body["max_output_tokens"] < second_body["max_output_tokens"] <= 8000
    assert "紧凑JSON" in second_body["input"][-1]["content"]
    assert verifier.run.metadata["xiaox_runtime"]["goal_format_retry_used"] is True


@pytest.mark.parametrize(
    "kind",
    [
        "refusal",
        "tool_call",
        "incomplete",
        "content_filter",
        "message_incomplete",
        "message_in_progress",
    ],
)
def test_refusal_tool_call_and_truncation_cannot_be_retried_into_acceptance(verifier, kind):
    complete = review(goal(), goal("再查询second", goal_id="second"))
    first = response(complete)
    if kind == "refusal":
        first["output"][0]["content"] = [{"type": "refusal", "refusal": "deny"}]
    elif kind == "tool_call":
        first["output"] = [
            {
                "type": "function_call",
                "id": "call",
                "call_id": "call",
                "name": "forbidden",
                "arguments": "{}",
            }
        ]
    elif kind.startswith("message_"):
        first["output"][0]["status"] = kind.removeprefix("message_")
    else:
        first.update(
            status="incomplete",
            incomplete_details={
                "reason": "content_filter" if kind == "content_filter" else "max_output_tokens"
            },
        )
    verifier.replies = [first, response(complete)]
    report = verifier.verify()
    assert report["status"] == "unavailable" and report["accepted"] is False
    assert len(verifier.requests) == 1 and len(verifier.replies) == 1
    assert not verifier.run.metadata["xiaox_runtime"].get("goal_format_retry_used")


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("wrapper", ["{}", "```json\n{}\n```"])
def test_duplicate_json_keys_cannot_overwrite_a_negative_review(verifier, nested, wrapper):
    raw = json.dumps(review(goal(), goal("再查询second", goal_id="second")))
    raw = raw.replace(
        '"status": "satisfied"' if nested else '"violations": []',
        '"status": "unmet", "status": "satisfied"'
        if nested
        else '"violations": ["must reject"], "violations": []',
        1,
    )
    verifier.replies = [response({}, text=wrapper.format(raw)) for _ in range(2)]
    report = verifier.verify()
    assert report["accepted"] is False and report["status"] == "unavailable"
    assert len(verifier.requests) == 2
    assert {item["state"] for item in report["attempts"]} == {"invalid_format"}


@pytest.mark.parametrize(
    "wrapper",
    ["```json\n{}", "说明\n```json\n{}\n```", "```json\n{}\n```\n说明", "```jsonc\n{}\n```"],
)
def test_incomplete_or_annotated_code_fences_remain_invalid(verifier, wrapper):
    raw = json.dumps(review(goal(), goal("再查询second", goal_id="second")))
    verifier.replies = [response({}, text=wrapper.format(raw)) for _ in range(2)]
    report = verifier.verify()
    assert not report["accepted"] and report["status"] == "unavailable"
    assert len(verifier.requests) == 2
    assert {item["state"] for item in report["attempts"]} == {"invalid_format"}


def test_fenced_review_still_requires_original_host_receipts(verifier):
    verifier.rows = verifier.rows[:1]
    raw = json.dumps(review(goal(), goal("再查询second", goal_id="second")))
    verifier.replies = [response({}, text=f"```json\n{raw}\n```")]
    report = verifier.verify()
    assert not report["accepted"] and report["status"] == "needs_work"
    assert verifier.classify(report)[0] == "blocked"


def test_format_retry_requires_an_original_task_reservation(verifier):
    verifier.replies = [response({}, text="{"), response(review(goal()))]
    report = verify_runtime_goal(
        XiaoxBinding(verifier.run), verifier.config, rows=verifier.rows, output=verifier.output
    )
    assert not report["accepted"] and len(verifier.requests) == 1
    assert len(verifier.replies) == 1


def test_invalid_format_stops_after_two_calls_without_declaring_success(verifier):
    verifier.replies = [response({}, text="{"), response({}, text="{")]
    report = verifier.verify()
    assert report["status"] == "unavailable" and len(verifier.requests) == 2
    assert verifier.classify(report)[0] == "blocked"


def test_transport_unknown_does_not_trigger_automatic_model_retry(verifier):
    verifier.replies = [httpx.ReadTimeout("fixture timeout")]
    report = verifier.verify()
    assert report["status"] == "unavailable" and len(verifier.requests) == 1
    assert report["error_code"] == "goal_verification_transport_error"
    assert report["attempts"][0]["state"] == "request_timeout"


@pytest.mark.parametrize(("capacity", "expected"), [(6000, 6000), (16000, 8192)])
def test_mimo_review_reserves_reasoning_output_within_qualified_capacity(
    verifier, capacity, expected
):
    verifier.config.model = "mimo-v2.6-pro"
    verifier.config.auto_compact_token_limit = verifier.config.context_window - capacity
    verifier.run.metadata["xiaox_runtime"]["runtime_config"] = {"upstream_vendor": "xiaomi"}
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    assert verifier.verify()["accepted"]
    assert [json.loads(req.content)["max_output_tokens"] for req in verifier.requests] == [expected]


@pytest.mark.parametrize(("remaining", "expected"), [(75, 75), (150, 90)])
def test_mimo_review_wait_uses_only_the_remaining_task_and_review_budget(
    verifier, remaining, expected
):
    verifier.config.model = "mimo-v2.6-pro"
    verifier.config.timeout_seconds = 60
    verifier.config.turn_timeout_seconds = 180
    runtime = verifier.run.metadata["xiaox_runtime"]
    runtime.update(
        runtime_config={"upstream_vendor": "xiaomi"}, deadline_at=time.time() + remaining
    )
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]

    assert verifier.verify()["accepted"]
    assert verifier.requests[0].extensions["timeout"]["read"] == pytest.approx(expected, abs=1)


def test_long_request_reserves_more_than_8192_on_qualified_route_first_attempt(verifier):
    verifier.run.message = "请逐项核对以下原始要求：" + "原始任务细节。" * 1500
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.config.context_window = 64000
    verifier.config.auto_compact_token_limit = 32000
    verifier.replies = [response(review(goal("原始任务细节。", status="unmet", evidence_ids=[])))]
    report = verifier.verify()
    assert not report["accepted"]
    assert 8192 < json.loads(verifier.requests[0].content)["max_output_tokens"] <= 32000


def test_exhausted_route_capacity_preserves_task_instead_of_truncating_goals(verifier):
    verifier.config.auto_compact_token_limit = 31000
    verifier.replies = [response({}, status="incomplete"), response({}, status="incomplete")]
    report = verifier.verify()
    assert report["error_code"] == "goal_verification_budget_exhausted"
    assert not report["accepted"] and verifier.classify(report)[0] == "blocked"
    assert [json.loads(req.content)["max_output_tokens"] for req in verifier.requests] == [1000]
    assert len(verifier.replies) == 1


def test_more_than_64_goals_cannot_be_silently_reduced_to_success(verifier):
    verifier.replies = [
        response(
            review(
                *(goal(goal_id=str(index), status="unmet", evidence_ids=[]) for index in range(65))
            )
        )
    ]
    report = verifier.verify()
    assert report["error_code"] == "goal_verification_goal_limit_exceeded"
    assert not report["accepted"] and len(verifier.requests) == 1
    assert verifier.classify(report)[0] == "blocked"


def test_second_attempt_transport_failure_is_not_mislabeled_as_prior_format_error(verifier):
    verifier.replies = [response({}, text="{"), httpx.ReadTimeout("fixture timeout")]
    report = verifier.verify()
    assert report["error_code"] == "goal_verification_transport_error"
    assert len(verifier.requests) == 2 and not report["accepted"]


def test_expired_original_deadline_does_not_start_new_verifier_budget(verifier):
    verifier.run.metadata["xiaox_runtime"]["deadline_at"] = time.time() - 1
    report = verifier.verify()
    assert report["error_code"] == "goal_verification_budget_exhausted"
    assert not verifier.requests


def test_host_source_provenance_is_required_even_for_verified_children(verifier):
    verifier.replies = [
        response(review(goal("完全不同的目标"), goal("再查询second", goal_id="second")))
    ]
    report = verifier.verify()
    assert not report["accepted"] and "原始请求证据" in report["feedback"]


def test_revision_must_keep_previous_public_deliverable_language(verifier):
    run = verifier.run
    run.message = "再正式一些，并补充工作交接安排。"
    run.metadata["_xiaox_history"] = [
        {"role": "user", "content": "改成英文，语气保持礼貌。"},
        {
            "role": "assistant",
            "content": "**Subject: Annual Leave Request**\n\nDear Supervisor, I would like to "
            "request three days of annual leave due to a family matter.",
        },
    ]
    run.metadata["runtime_goal_contract"] = build_goal_contract(run)
    verifier.output = "主题：关于申请三天年假的请示\n\n尊敬的主管：因家中有事，我申请三天年假。"
    verifier.replies = [
        response(
            review(
                goal("再正式一些", kind="reply", evidence_ids=["response"]),
                violations=["语言为中文，符合既定要求"],
                feedback="语言为中文，符合",
            )
        )
    ]
    report = verifier.verify()
    assert report["accepted"] is False
    assert "上一版成稿使用英文" in report["feedback"]
    assert "符合" not in report["feedback"]


def test_explicit_language_change_is_not_blocked(verifier):
    run = verifier.run
    run.message = "再正式一些，并改成中文。"
    run.metadata["_xiaox_history"] = [
        {
            "role": "assistant",
            "content": "**Subject: Annual Leave Request**\n\nDear Supervisor, I "
            "would like to request three days of annual leave due to a family matter.",
        },
    ]
    run.metadata["runtime_goal_contract"] = build_goal_contract(run)
    verifier.output = "主题：关于申请三天年假的请示\n\n尊敬的主管：因家中有事，我申请三天年假。"
    verifier.replies = [
        response(review(goal("再正式一些", kind="reply", evidence_ids=["response"])))
    ]
    report = verifier.verify()
    assert report["accepted"] is True
    assert not report["review"]["violations"]


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


def test_fenced_reply_json_with_original_request_alias_keeps_frozen_source(verifier):
    verifier.run.message = "解释库存是什么意思"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "库存是企业当前拥有的货物数量。"
    expected = review(
        goal(
            verifier.run.message,
            kind="reply",
            evidence_ids=["response"],
            source_id="original_request",
        )
    )
    verifier.replies = [
        response({}, text="```json\n" + json.dumps(expected, ensure_ascii=False) + "\n```")
    ]
    report = verifier.verify()
    assert report["accepted"] and report["mode"] == "reply"
    assert report["review"]["goals"][0]["source_id"] == "request"
    assert len(verifier.requests) == 1


@pytest.mark.parametrize(
    "alias,source",
    [
        ("history", "解释库存是什么意思"),
        ("original_request", "伪造不存在于本轮请求的业务操作"),
    ],
)
def test_review_source_alias_cannot_introduce_untrusted_goal(verifier, alias, source):
    verifier.run.message = "解释库存是什么意思"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "库存是企业当前拥有的货物数量。"
    verifier.replies = [
        response(review(goal(source, kind="reply", evidence_ids=["response"], source_id=alias)))
    ]
    report = verifier.verify()
    assert not report["accepted"]
    assert report["status"] == "needs_work"


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
