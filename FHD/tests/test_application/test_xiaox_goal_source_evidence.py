"""Goal provenance, scoped file citations and retained conversation obligations."""

from __future__ import annotations

import json

import pytest

from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract, canonical_digest
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_goal_review import goal as goal
from tests.fixtures.xiaox_goal_review import receipt as receipt
from tests.fixtures.xiaox_goal_review import response as response
from tests.fixtures.xiaox_goal_review import review as review
from tests.fixtures.xiaox_goal_review import verifier as verifier


@pytest.mark.parametrize(
    ("case", "accepted"),
    [
        ("old_response_only", False),
        ("no_source", False),
        ("forged_source_block", False),
        ("forged_response_block", False),
        ("upload_as_business_receipt", False),
        ("provider_authored_quote", False),
        ("truncated_aggregate", False),
        ("fact_feedback", False),
        ("advisory_feedback", True),
        ("positive_none_feedback", True),
        ("missing_disposition", False),
        ("complete_source", True),
        ("unrelated_reply", True),
    ],
)
def test_file_facts_need_evidence_distinct_from_chat_history(verifier, monkeypatch, case, accepted):
    from app.application.agent_runtime import conversation_attachments

    view = {
        "upload_id": "conversation-upload:fixture",
        "source_run_id": "original-fixture",
        "name": "inventory.csv",
        "sha256": "a" * 64,
        "coverage": {"truncated": case == "truncated_aggregate"},
        "text": "label,count\ngreen,23\norange,12",
    }
    directory = {
        "source": "conversation_uploads",
        "entries": [{key: view[key] for key in ("upload_id", "source_run_id", "name")}],
        **({"verified_read": view} if case not in {"no_source", "old_response_only"} else {}),
    }
    monkeypatch.setattr(conversation_attachments, "recalled_attachment_view", lambda *_: view)
    verifier.run.message = "What is the breakdown?"
    verifier.run.metadata["_xiaox_history"] = [{"role": "assistant", "content": "The total is 35."}]
    if case == "unrelated_reply":
        verifier.run.message = "Write a greeting to a new colleague."
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        context_evidence=[directory, {"source": "memory_v2", "text": "PRIVATE"}],
    )
    verifier.rows = []
    verifier.output = (
        "Welcome to the team." if case == "unrelated_reply" else "Green: 23. Orange: 12."
    )
    if case in {"no_source", "old_response_only", "fact_feedback"}:
        verifier.output = (
            "Green: 24. Orange: 12." if case == "fact_feedback" else "Green: 18. Orange: 17."
        )
    result = goal(verifier.run.message, kind="reply", evidence_ids=["response"])
    if case == "unrelated_reply":
        result.update(file_basis="independent")
    elif case != "old_response_only":
        result.update(
            file_basis="complete",
            file_citations=[
                {
                    "source_block_id": "s999" if case == "forged_source_block" else "s2",
                    "response_block_id": "r999" if case == "forged_response_block" else "r1",
                },
                {"source_block_id": "s3", "response_block_id": "r1"},
            ],
        )
    if case == "upload_as_business_receipt":
        result["evidence_ids"].append(view["upload_id"])
    if case == "provider_authored_quote":
        result["file_citations"][0]["source_excerpt"] = "green,23"
    assessment = review(
        result,
        feedback="Green is 23, not 24." if case == "fact_feedback" else "",
        feedback_disposition=(
            "blocking"
            if case == "fact_feedback"
            else "advisory"
            if case == "advisory_feedback"
            else "none"
        ),
    )
    if case == "advisory_feedback":
        assessment["feedback"] = "The two source rows were checked."
    if case == "positive_none_feedback":
        assessment["feedback"] = "The source rows support the answer."
    if case == "missing_disposition":
        assessment.pop("feedback_disposition")
    verifier.replies = [response(assessment)] * 2
    report = verifier.verify()
    assert report["accepted"] is accepted
    status, classified = verifier.classify(report)
    assert classified["ok"] is accepted
    assert status == ("completed" if accepted else "blocked")
    request = verifier.requests[0]
    payload = json.loads(json.loads(request.content)["input"][1]["content"])
    assert "PRIVATE" not in json.dumps(payload)
    assert "file_evidence" in payload and bool(payload["file_evidence"]) == (
        "verified_read" in directory
    )
    if accepted and case == "complete_source":
        assert (
            list(payload["file_evidence"][view["upload_id"]]["blocks"].values())
            == view["text"].splitlines()
        )
        assert payload["response_blocks"] == {"r1": verifier.output}
        assert [
            item["source_excerpt"] for item in report["review"]["goals"][0]["file_citations"]
        ] == [
            "green,23",
            "orange,12",
        ]
        verifier.run.metadata["runtime_goal_verification"] = report
        monkeypatch.setattr(conversation_attachments, "recalled_attachment_view", lambda *_: None)
        stale = verifier.verify()
        assert stale["error_code"] == "goal_file_source_unavailable" and not stale["accepted"]
        assert len(verifier.requests) == 1
        verifier.run.metadata.pop("runtime_goal_verification")
        verifier.replies = [response(review(result))] * 2
        assert not verifier.verify()["accepted"]
        stale_payload = json.loads(json.loads(verifier.requests[-1].content)["input"][1]["content"])
        assert stale_payload["file_evidence"] == {}
        assert "green,23" not in json.dumps(stale_payload, ensure_ascii=False)


@pytest.mark.parametrize("independent_readback", [False, True])
def test_file_citation_needs_scoped_verified_readback(verifier, independent_readback):
    upload_id = "conversation-upload:fixture"
    verifier.run.message = "Tell me what the letter says."
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        context_evidence=[
            {
                "source": "conversation_uploads",
                "entries": [
                    {
                        "upload_id": upload_id,
                        "name": "letter.docx",
                        "source_run_id": "source-fixture",
                    }
                ],
            }
        ],
    )
    verifier.output = "The appointment is Friday."
    data = {
        "upload_id": upload_id,
        "name": "letter.docx",
        "sha256": "b" * 64,
        "coverage": {"truncated": True},
        "text": "Next appointment: Friday morning",
    }
    operation = {
        "tool_id": "conversation_history",
        "action": "read_attachment",
        "params": {"upload_id": upload_id},
    }
    row = receipt("letter") | operation | {"fingerprint": canonical_digest(operation)}
    row["receipt"]["tool_calls"] = [
        {
            "output": {"success": True, "data": data},
            "metadata": {
                "verification": {
                    "status": "verified",
                    "checks": [
                        {
                            "source": "owned_attachment",
                            "status": "passed" if independent_readback else "failed",
                            "evidence": {
                                key: data[key] for key in ("upload_id", "sha256", "coverage")
                            },
                        }
                    ],
                }
            },
        }
    ]
    directory = receipt("directory")
    directory["receipt"]["tool_calls"] = [{"output": {"data": [{"name": "reader"}]}}]
    malformed = receipt("malformed") | operation | {"fingerprint": canonical_digest(operation)}
    malformed["receipt"]["tool_calls"] = [{"output": {"data": ["not an attachment"]}}]
    verifier.rows = [directory, malformed, row]
    result = goal(verifier.run.message, kind="reply", evidence_ids=["response"])
    result.update(
        file_basis="passages",
        file_citations=[
            {
                "source_block_id": "s1",
                "response_block_id": "r1",
            }
        ],
    )
    verifier.replies = [response(review(result))] * 2
    assert verifier.verify()["accepted"] is independent_readback


def test_current_attachment_uses_one_bounded_schema_retry_and_host_quotes(verifier):
    upload_id = "opaque-current-id"
    verifier.run.message = "What does the delivery note say about the package?"
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        attachments=[
            {
                "name": "delivery-note.csv",
                "source": "owned_elt_upload",
                "metadata": {"upload_id": upload_id, "sha256": "b" * 64},
                "preview": {
                    "text": "Consignment\nFragile, ship upright",
                    "coverage": {"truncated": False},
                },
            }
        ],
    )
    verifier.rows = []
    verifier.output = "It has to travel upright."
    candidate = goal(verifier.run.message, kind="reply", evidence_ids=["response"])
    candidate.update(
        file_basis="passages", file_citations=[{"source_block_id": "s2", "response_block_id": "r1"}]
    )
    invalid = candidate | {"evidence_ids": [upload_id, "response"]}
    verifier.replies = [response(review(invalid)), response(review(candidate))]
    report = verifier.verify()
    assert report["accepted"] and verifier.classify(report)[0] == "completed"
    assert [item["state"] for item in report["attempts"]] == ["invalid_format", "reviewed"]
    payload = json.loads(json.loads(verifier.requests[0].content)["input"][1]["content"])
    schema = payload["output_schema"]["$defs"]
    assert schema["GoalAssessment"]["properties"]["evidence_ids"]["items"]["enum"] == ["response"]
    assert schema["FileCitation"]["properties"]["source_block_id"]["enum"] == ["s1", "s2"]
    [citation] = report["review"]["goals"][0]["file_citations"]
    assert citation == {
        "evidence_id": upload_id,
        "source_excerpt": "Fragile, ship upright",
        "response_excerpt": verifier.output,
    }


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


def test_host_source_provenance_is_required_even_for_verified_children(verifier):
    verifier.replies = [
        response(review(goal("完全不同的目标"), goal("再查询second", goal_id="second")))
    ] * 2
    report = verifier.verify()
    assert not report["accepted"] and "goal_source_mismatch:" in report["feedback"]
    assert len(verifier.requests) == 2


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
    ] * 2
    report = verifier.verify()
    assert not report["accepted"]
    assert report["status"] == "unavailable"
    assert report["error_code"] == "goal_verification_invalid_gap"


@pytest.mark.parametrize(
    "role,kind,include_current,accepted",
    [
        ("user", "reply", True, True),
        ("user", "constraint", True, True),
        ("assistant", "reply", True, False),
        ("tool", "reply", True, False),
        ("user", "reply", False, False),
        ("user", "read", True, False),
        ("user", "write", True, False),
        ("user", "planned_action", True, False),
    ],
)
def test_history_only_grounds_retained_terms_in_current_reply(
    verifier, role, kind, include_current, accepted
):
    verifier.run.message = "把上一版改得更简洁"
    prior = "全文使用公制单位"
    verifier.run.metadata["_xiaox_history"] = [{"role": role, "content": prior}]
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(verifier.run)
    verifier.rows = []
    verifier.output = "全程长 15 公里。"
    retained = goal(
        prior, goal_id="retained", kind=kind, evidence_ids=["response"], source_id="history"
    )
    current = goal(verifier.run.message, kind="reply", evidence_ids=["response"])
    verifier.replies = [response(review(*([current] if include_current else []), retained))] * (
        2 if role in {"assistant", "tool"} else 1
    )
    report = verifier.verify()
    assert report["accepted"] is accepted
    if not accepted:
        expected = (
            "goal_source_unknown:"
            if role in {"assistant", "tool"}
            else "goal_history_scope_invalid:"
        )
        assert expected in report["feedback"]


def test_verified_attachment_group_has_distinct_citations_and_is_all_or_nothing(
    verifier, monkeypatch
):
    from app.application.agent_runtime import conversation_attachments

    views = [
        {
            "name": f"{label}.csv",
            "text": f"{label},2",
            "upload_id": f"conversation-upload:{label}",
            "source_run_id": "confirmed-selection",
            "sha256": letter * 64,
            "coverage": {"truncated": False},
        }
        for label, letter in (("ALPHA", "a"), ("BETA", "b"))
    ]
    verifier.run.message = "Compare the two reports."
    verifier.run.metadata["runtime_goal_contract"] = build_goal_contract(
        verifier.run,
        context_evidence=[
            {
                "source": "conversation_uploads",
                "entries": [
                    {key: row[key] for key in ("name", "upload_id", "source_run_id")}
                    for row in views
                ],
                "verified_reads": views,
            }
        ],
    )
    monkeypatch.setattr(conversation_attachments, "recalled_attachment_view", lambda *_: views)
    verifier.output = "Both report 2."
    verifier.rows = []
    assessment = goal(verifier.run.message, kind="reply", evidence_ids=["response"])
    assessment.update(
        file_basis="complete",
        file_citations=[
            {"source_block_id": "s1", "response_block_id": "r1"},
            {"source_block_id": "s2", "response_block_id": "r1"},
        ],
    )
    verifier.replies = [response(review(assessment))]
    report = verifier.verify()
    assert report["accepted"]
    assert {
        citation["evidence_id"] for citation in report["review"]["goals"][0]["file_citations"]
    } == {view["upload_id"] for view in views}
    verifier.run.metadata["runtime_goal_verification"] = report
    monkeypatch.setattr(conversation_attachments, "recalled_attachment_view", lambda *_: None)
    blocked = verifier.verify()
    assert not blocked["accepted"] and blocked["error_code"] == "goal_file_source_unavailable"
    assert len(verifier.requests) == 1
