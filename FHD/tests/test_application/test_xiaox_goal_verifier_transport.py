"""Bounded review transport, strict response schema and original request budgets."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox.binding import XiaoxBinding
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import goal as goal
from tests.fixtures.xiaox_goal_review import receipt as receipt
from tests.fixtures.xiaox_goal_review import response as response
from tests.fixtures.xiaox_goal_review import review as review
from tests.fixtures.xiaox_goal_review import verifier as verifier


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
    assert not report["accepted"] and report["status"] == "unavailable"
    assert report["error_code"] == "goal_verification_invalid_gap"
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
