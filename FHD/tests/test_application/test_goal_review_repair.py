"""Report repair preserves the frozen task and every substantive verdict."""

from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.application.agent_runtime.verification_budget import VERIFIER_VERSION
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_evidence_snapshot,
)
from app.infrastructure.xiaox.binding import XiaoxBinding
from tests.fixtures.xiaox_goal_review import goal, receipt, response, review
from tests.fixtures.xiaox_goal_review import verifier as verifier


def _payload(request):
    return json.loads(json.loads(request.content)["input"][1]["content"])


def _complete_review():
    return review(goal(), goal("再查询second", goal_id="second"))


def test_attachment_format_repair_reports_missing_contract_field_without_file_values(verifier):
    verifier.run.message = "读取附件"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        attachments=[
            {
                "name": "note.csv",
                "source": "owned_elt_upload",
                "metadata": {"upload_id": "current-note", "sha256": "c" * 64},
                "preview": {"text": "PRIVATE-FILE-BODY", "coverage": {"truncated": False}},
            }
        ],
    )
    verifier.rows = []
    verifier.output = "尚未完成附件读取"
    corrected = review(goal("读取附件", status="unmet", evidence_ids=[]))
    corrected["goals"][0]["file_basis"] = "complete"
    rejected = copy.deepcopy(corrected)
    rejected["goals"][0].pop("file_basis")
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["status"] == "needs_work" and not report["accepted"]
    assert len(verifier.requests) == 2
    assert report["attempts"][0]["validation_errors"][0] == {
        "path": ["goals", 0],
        "rule": "required",
        "missing": ["file_basis"],
    }
    repair = json.loads(verifier.requests[1].content)["input"][-1]["content"]
    assert "file_basis" in repair and "PRIVATE-FILE-BODY" not in repair


@pytest.mark.parametrize("missing", ["constraint", "history"])
def test_completed_file_goal_without_own_citation_is_repaired_before_final_verdict(
    verifier, missing
):
    verifier.run.message = "查看并完整概述"
    verifier.run.metadata["_xiaox_history"] = [{"role": "user", "content": "查看"}]
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        attachments=[
            {
                "name": "document.docx",
                "source": "owned_elt_upload",
                "metadata": {"upload_id": "current-document", "sha256": "c" * 64},
                "preview": {"text": "ALPHA verified body", "coverage": {"truncated": False}},
            }
        ],
    )
    verifier.rows = []
    verifier.output = "Document contains ALPHA verified body."
    corrected = review(
        goal("查看", kind="reply", evidence_ids=["response"]),
        goal(
            "完整概述" if missing == "constraint" else "查看",
            goal_id="retained",
            kind="constraint" if missing == "constraint" else "reply",
            evidence_ids=["response"],
            source_id="request" if missing == "constraint" else "history:0:user",
        ),
    )
    for item in corrected["goals"]:
        item.update(
            file_basis="complete",
            file_citations=[{"source_block_id": "s1", "response_block_id": "r1"}],
        )
    extra = copy.deepcopy(corrected["goals"][1])
    extra["goal_id"] = "another-retained"
    corrected["goals"].append(extra)
    rejected = copy.deepcopy(corrected)
    rejected["goals"][1]["file_citations"] = []
    rejected["goals"][2]["file_citations"] = []
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["accepted"] and len(verifier.requests) == 2
    assert report["attempts"][0]["validation_errors"][0] == {
        "path": ["goals", 1, "file_citations"],
        "rule": "minItems",
    }
    assert len(report["attempts"][0]["validation_errors"]) == 2
    repair = json.loads(verifier.requests[1].content)["input"][-1]["content"]
    assert '["goals", 1, "file_citations"]' in repair
    assert '["goals", 2, "file_citations"]' in repair
    assert all(json.loads(request.content)["tools"] == [] for request in verifier.requests)


@pytest.mark.parametrize("defect", ["duplicate_id", "unknown_source", "wrong_quote"])
def test_provenance_repair_only_rechecks_the_same_candidate(verifier, defect):
    corrected = _complete_review()
    rejected = copy.deepcopy(corrected)
    broken = rejected["goals"][1]
    if defect == "duplicate_id":
        broken["goal_id"] = "first"
    elif defect == "unknown_source":
        broken["source_id"] = "nonexistent-source"
    else:
        broken["source"] = "查询不存在的目标"
    original_rows = copy.deepcopy(verifier.rows)
    original_contract = copy.deepcopy(verifier.run.metadata["runtime_goal_contract"])
    original_output = verifier.output
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["accepted"] and verifier.classify(report)[0] == "completed"
    assert [attempt["state"] for attempt in report["attempts"]] == [
        "invalid_provenance",
        "reviewed",
    ]
    assert len(verifier.requests) == 2
    first, second = map(_payload, verifier.requests)
    assert "review_repair" not in first
    assert second["review_repair"]["allowed_fields"] == ["goal_id", "source_id", "source"]
    assert second["review_repair"]["review"]["goals"][1]["source"] == broken["source"]
    for key in ("original_request", "source_catalogue", "evidence", "response", "answers"):
        assert second[key] == first[key]
    assert all(json.loads(request.content)["tools"] == [] for request in verifier.requests)
    assert verifier.rows == original_rows
    assert verifier.output == original_output
    assert verifier.run.metadata["runtime_goal_contract"] == original_contract
    assert report["response_digest"] == canonical_digest(original_output)
    assert (
        report["evidence_digest"]
        == goal_evidence_snapshot(original_contract, original_rows, original_output)["digest"]
    )
    assert verifier.run.metadata["xiaox_runtime"]["goal_format_retry_used"] is True


def test_repaired_report_retains_unmet_goal_and_every_gap(verifier):
    corrected = review(
        goal(),
        goal("再查询second", goal_id="second", status="unmet", evidence_ids=[]),
        violations=["成稿遗漏查询范围"],
        feedback="second 的结果还没有交付",
        feedback_disposition="blocking",
    )
    corrected["uncovered_sources"] = ["尚未核对 second 的完整内容"]
    rejected = copy.deepcopy(corrected)
    rejected["goals"][1]["goal_id"] = "first"
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["status"] == "needs_work" and not report["accepted"]
    assert len(verifier.requests) == 2
    assert report["review"]["goals"][1]["status"] == "unmet"
    assert report["review"]["violations"] == corrected["violations"]
    assert report["review"]["uncovered_sources"] == corrected["uncovered_sources"]
    assert report["review"]["feedback"] == corrected["feedback"]
    repair = _payload(verifier.requests[1])["review_repair"]["review"]
    assert repair["goals"][1]["status"] == "unmet"
    assert repair["violations"] == corrected["violations"]
    assert repair["uncovered_sources"] == corrected["uncovered_sources"]


@pytest.mark.parametrize(
    "mutation", ["status", "drop_goal", "reorder", "reason", "violations", "uncovered", "feedback"]
)
def test_repair_cannot_change_substantive_judgments(verifier, mutation):
    rejected = review(
        goal(),
        goal("再查询second", goal_id="first", status="unmet", evidence_ids=[]),
        violations=["成稿遗漏查询范围"],
        feedback="second 的结果还没有交付",
        feedback_disposition="blocking",
    )
    rejected["uncovered_sources"] = ["尚未核对 second 的完整内容"]
    changed = copy.deepcopy(rejected)
    changed["goals"][1]["goal_id"] = "second"
    if mutation == "status":
        changed["goals"][1].update(status="satisfied", evidence_ids=["child-second"])
    elif mutation == "drop_goal":
        changed["goals"].pop()
    elif mutation == "reorder":
        changed["goals"].reverse()
    elif mutation == "reason":
        changed["goals"][1]["reason"] = "不再需要完成"
    elif mutation == "violations":
        changed["violations"] = []
    elif mutation == "uncovered":
        changed["uncovered_sources"] = []
    else:
        changed["feedback"] = "现在已经全部正确"
    verifier.replies = [response(rejected), response(changed)]

    report = verifier.verify()

    assert len(verifier.requests) == 2
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert verifier.classify(report)[0] == "blocked"


@pytest.mark.parametrize("retry_reserved", [False, True])
def test_invalid_source_is_bounded_and_never_requests_task_compensation(verifier, retry_reserved):
    rejected = _complete_review()
    rejected["goals"][1]["source"] = "来源中没有的文字"
    verifier.run.metadata["xiaox_runtime"]["goal_format_retry_used"] = retry_reserved
    verifier.replies = [response(rejected), response(rejected)]

    report = verifier.verify()

    assert len(verifier.requests) == (1 if retry_reserved else 2)
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert verifier.classify(report)[0] == "blocked"


def test_provenance_repair_cannot_mask_an_invalid_business_receipt(verifier):
    rejected = _complete_review()
    rejected["goals"][1]["goal_id"] = "first"
    verifier.rows = verifier.rows[:1]
    verifier.replies = [response(rejected), response(_complete_review())]

    report = verifier.verify()

    assert len(verifier.requests) == 1
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert not verifier.run.metadata["xiaox_runtime"].get("goal_format_retry_used")


def test_repair_of_mixed_task_keeps_the_original_verified_write(verifier):
    verifier.run.message = "确认first，再给我三句说明"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = [receipt("first", read_only=False)]
    verifier.output = "订单已确认。库存随订单更新。可查看原订单。"
    corrected = review(
        goal("确认first", kind="write"),
        goal("再给我三句说明", goal_id="text", kind="reply", evidence_ids=["response"]),
    )
    rejected = copy.deepcopy(corrected)
    rejected["goals"][1]["source_id"] = "unavailable-source"
    frozen = copy.deepcopy(verifier.rows)
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["accepted"] and report["mode"] == "business"
    assert len(verifier.requests) == 2 and verifier.rows == frozen
    assert report["review"]["goals"][0]["evidence_ids"] == ["child-first"]


def test_report_repair_requires_the_original_retry_reservation(verifier):
    rejected = _complete_review()
    rejected["goals"][1]["goal_id"] = "first"
    verifier.replies = [response(rejected), response(_complete_review())]

    report = verify_runtime_goal(
        XiaoxBinding(verifier.run), verifier.config, rows=verifier.rows, output=verifier.output
    )

    assert len(verifier.requests) == 1
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"


def test_corrected_history_source_still_cannot_authorize_business(verifier):
    verifier.run.message = "查询first"
    verifier.run.metadata["_xiaox_history"] = [{"role": "user", "content": "再查询second"}]
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    rejected = _complete_review()
    rejected["goals"][1]["source_id"] = "missing-source"
    corrected = copy.deepcopy(rejected)
    corrected["goals"][1]["source_id"] = "history:0:user"
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert len(verifier.requests) == 2
    assert report["status"] == "unavailable" and not report["accepted"]
    assert "goal_history_scope_invalid:" in report["feedback"]
    assert verifier.classify(report)[0] == "blocked"


def test_settled_invalid_report_replays_before_one_reserved_correction(verifier):
    rejected = _complete_review()
    rejected["goals"][1]["goal_id"] = "first"
    settled = response(rejected)
    contract = verifier.run.metadata["runtime_goal_contract"]
    replay = {
        "state": "response_received",
        "verifier_version": VERIFIER_VERSION,
        "input": {
            "goal_digest": contract["digest"],
            "evidence_digest": goal_evidence_snapshot(contract, verifier.rows, verifier.output)[
                "digest"
            ],
            "response_digest": canonical_digest(verifier.output),
        },
        "response": settled,
        "response_digest": canonical_digest(settled),
    }
    reservations = []
    verifier.replies = [response(_complete_review())]

    def reserve():
        reservations.append(True)
        return len(reservations) == 1

    report = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        consume_format_retry=reserve,
        replay_response=replay,
    )

    assert report["accepted"] and len(verifier.requests) == 1
    assert report["attempts"][0]["replayed_settled_response"] is True
    assert len(reservations) == 1


@pytest.mark.parametrize("defect", ["duplicate_id", "unknown_source"])
def test_attachment_report_repair_retains_wire_block_references(verifier, defect):
    verifier.run.message = "Summarize the shipment and state the handling requirement."
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        attachments=[
            {
                "name": "note.csv",
                "source": "owned_elt_upload",
                "metadata": {"upload_id": "current-note", "sha256": "c" * 64},
                "preview": {
                    "text": "Shipment\nFragile, ship upright",
                    "coverage": {"truncated": False},
                },
            }
        ],
    )
    verifier.rows = []
    verifier.output = "The shipment is fragile and must remain upright."
    corrected = review(
        goal("Summarize the shipment", kind="reply", evidence_ids=["response"]),
        goal(
            "state the handling requirement",
            goal_id="handling",
            kind="reply",
            evidence_ids=["response"],
        ),
    )
    for item in corrected["goals"]:
        item.update(
            file_basis="passages",
            file_citations=[{"source_block_id": "s2", "response_block_id": "r1"}],
        )
    rejected = copy.deepcopy(corrected)
    rejected["goals"][1]["goal_id" if defect == "duplicate_id" else "source_id"] = (
        "first" if defect == "duplicate_id" else "missing-source"
    )
    verifier.replies = [response(rejected), response(corrected)]

    report = verifier.verify()

    assert report["accepted"] and len(verifier.requests) == 2
    payload = _payload(verifier.requests[1])
    repair = payload["review_repair"]["review"]
    assert repair == rejected
    repaired_wire = copy.deepcopy(repair)
    repaired_wire["goals"][1]["goal_id"] = "handling"
    repaired_wire["goals"][1]["source_id"] = "request"
    assert Draft202012Validator(payload["output_schema"]).is_valid(repaired_wire)
    assert report["review"]["goals"][1]["file_citations"] == [
        {
            "evidence_id": "current-note",
            "source_excerpt": "Fragile, ship upright",
            "response_excerpt": verifier.output,
        }
    ]


def _change_review_input(verifier, mutation):
    if mutation == "receipt":
        verifier.rows[0]["receipt"]["tool_calls"][0]["output"]["data"] = {"target": "other"}
    elif mutation == "history":
        verifier.run.metadata["_xiaox_history"].append(
            {"role": "user", "content": "本轮范围已改变"}
        )
    else:
        verifier.run.add_event(
            "runtime.input_answered", "补答", {"question": "范围", "answer": "只查询first"}
        )


@pytest.mark.parametrize("mutation", ["receipt", "history", "answer"])
def test_changed_host_evidence_aborts_report_repair(verifier, mutation):
    rejected = _complete_review()
    rejected["goals"][1]["goal_id"] = "first"
    verifier.replies = [response(rejected), response(_complete_review())]

    def change_after_request(_request):
        if len(verifier.requests) == 1:
            _change_review_input(verifier, mutation)

    verifier.observe_request = change_after_request
    report = verifier.verify()

    assert len(verifier.requests) == 1
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_evidence_changed"
    assert verifier.classify(report)[0] == "blocked"


@pytest.mark.parametrize("mutation", ["receipt", "history", "answer"])
def test_input_changed_during_retry_reservation_prevents_second_request(verifier, mutation):
    rejected = _complete_review()
    rejected["goals"][1]["goal_id"] = "first"
    verifier.replies = [response(rejected), response(_complete_review())]
    reservations = []

    def reserve():
        reservations.append(True)
        _change_review_input(verifier, mutation)
        return True

    report = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        consume_format_retry=reserve,
    )

    assert reservations == [True]
    assert len(verifier.requests) == 1 and len(verifier.replies) == 1
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_evidence_changed"
    assert verifier.classify(report)[0] == "blocked"


@pytest.mark.parametrize("defect", ["duplicate_id", "unknown_source"])
def test_identifier_repair_preserves_already_grounded_requirement(verifier, defect):
    rejected = _complete_review()
    if defect == "duplicate_id":
        rejected["goals"][1]["goal_id"] = "first"
    else:
        rejected["goals"][1]["source_id"] = "missing-source"
    changed = _complete_review()
    changed["goals"][1]["source"] = "查询first"
    verifier.replies = [response(rejected), response(changed)]

    report = verifier.verify()

    assert len(verifier.requests) == 2
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"


@pytest.mark.parametrize(
    "source_type,kind,status",
    [
        ("history", "read", "satisfied"),
        ("history", "read", "unmet"),
        ("history", "write", "unmet"),
        ("objective", "reply", "satisfied"),
    ],
)
def test_file_schema_cannot_launder_authority_errors_through_format_retry(
    verifier, source_type, kind, status
):
    verifier.run.message = "Explain the note."
    verifier.run.metadata["_xiaox_history"] = [{"role": "user", "content": "查询first"}]
    if source_type == "objective":
        verifier.run.metadata["runtime_context"]["_runtime_goal_constraints"] = {
            "objective": "查询first"
        }
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        attachments=[
            {
                "name": "note.csv",
                "source": "owned_elt_upload",
                "metadata": {"upload_id": "current-note", "sha256": "c" * 64},
                "preview": {
                    "text": "Fragile, ship upright",
                    "coverage": {"truncated": False},
                },
            }
        ],
    )
    verifier.output = "The shipment is fragile and must remain upright."
    current = goal(verifier.run.message, goal_id="current", kind="reply", evidence_ids=["response"])
    current.update(
        file_basis="passages",
        file_citations=[{"source_block_id": "s1", "response_block_id": "r1"}],
    )
    untrusted = goal(
        "查询first",
        source_id="history:0:user" if source_type == "history" else "objective",
        kind=kind,
        status=status,
        evidence_ids=[]
        if status == "unmet"
        else ["child-first"]
        if source_type == "history"
        else ["response"],
    )
    untrusted["file_basis"] = "independent"
    rewritten = copy.deepcopy(untrusted)
    rewritten.update(
        kind="reply" if source_type == "history" else "read",
        evidence_ids=[]
        if status == "unmet"
        else ["response"]
        if source_type == "history"
        else ["child-first"],
    )
    verifier.replies = [response(review(current, untrusted)), response(review(current, rewritten))]

    report = verifier.verify()

    assert len(verifier.requests) == 1
    assert report["status"] == "unavailable" and not report["accepted"]
    assert report["error_code"] == "goal_verification_invalid_gap"
    assert not verifier.run.metadata["xiaox_runtime"].get("goal_format_retry_used")
    if source_type == "history":
        assert "goal_history_scope_invalid:" in report["feedback"]


def test_three_successive_json_revisions_keep_the_public_draft_and_user_terms(verifier):
    original = "Write in English; return JSON with subject and body keys."
    previous = {"subject": "Annual leave", "body": "I would like to request three days of leave."}
    history = [
        {"role": "user", "content": original},
        {"role": "assistant", "content": json.dumps(previous)},
    ]
    verifier.rows = []
    changes = ["再正式一些", "正文更简洁", "增加交接安排"]
    for index, change in enumerate(changes, start=1):
        verifier.run.message = change
        verifier.run.metadata["_xiaox_history"] = copy.deepcopy(history)
        verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
        verifier.output = json.dumps(
            {
                "subject": "Annual leave",
                "body": "I respectfully request leave and will arrange a handover.",
            }
        )
        verifier.replies = [
            response(
                review(
                    goal(change, goal_id="revision", kind="reply", evidence_ids=["response"]),
                    goal(
                        "Write in English",
                        goal_id="language",
                        kind="reply",
                        evidence_ids=["response"],
                        source_id="history:0:user",
                    ),
                    goal(
                        "return JSON with subject and body keys",
                        goal_id="shape",
                        kind="reply",
                        evidence_ids=["response"],
                        source_id="history:0:user",
                    ),
                )
            )
        ]

        report = verifier.verify()

        assert report["accepted"] and report["mode"] == "reply"
        assert len(verifier.requests) == index
        payload = _payload(verifier.requests[-1])
        assert payload["original_request"]["history"] == history
        assert payload["source_catalogue"]["history:0:user"]["text"] == original
        assert all(not key.endswith(":assistant") for key in payload["source_catalogue"])
        assert json.loads(verifier.output).keys() == previous.keys()
        history.extend(
            [
                {"role": "user", "content": change},
                {"role": "assistant", "content": verifier.output},
            ]
        )
