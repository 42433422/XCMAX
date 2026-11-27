from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from app.application.agent_orchestrator.run_models import AgentRun
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_evidence_snapshot,
    goal_source_catalogue,
    review_schema,
    valid_compensation_review,
    validate_goal_review,
)


def _batch_write_row(child: str, phase_count: int) -> dict:
    operation = {
        "tool_id": "employee",
        "action": "execute",
        "params": {
            "employee_id": "excel-template-write-employee",
            "input": {"plan": {"phases": [{"phase": f"p{i}"} for i in range(phase_count)]}},
        },
    }
    return {
        **operation,
        "fingerprint": canonical_digest(operation),
        "child_run_id": child,
        "child_task_id": f"task-{child}",
        "state": "completed",
        "read_only": False,
        "receipt": {
            "status": "completed",
            "success": True,
            "verified": True,
            "run_id": child,
            "task_id": f"task-{child}",
        },
    }


def _write_goal(goal_id: str, source: str, evidence_id: str) -> dict:
    return {
        "goal_id": goal_id,
        "source_id": "request",
        "source": source,
        "kind": "write",
        "status": "satisfied",
        "evidence_ids": [evidence_id],
        "reason": "同一批量动作的已核验 phase",
    }


def test_batch_write_receipt_backs_as_many_atomic_goals_as_verified_changes():
    message = "写入日期，写入金额，设置金额公式"
    run = AgentRun(user_id="71", message=message, run_id="run-batch")
    contract = build_goal_contract(run)
    row = _batch_write_row("run_child", 3)
    row["receipt"]["verification"] = {
        "status": "verified",
        "accepted": True,
        "steps": [
            {
                "checks": [
                    {
                        "source": "workbook_qc",
                        "status": "passed",
                        "evidence": {
                            "sections": {"conformance": "pass"},
                            "cell_changes": {"scan_complete": True, "groups": [{"count": 3}]},
                        },
                    }
                ]
            }
        ],
    }
    snapshot = goal_evidence_snapshot(contract, [row], "已完成")
    raw = {
        "goals": [
            _write_goal(f"g{index}", text, "run_child")
            for index, text in enumerate(["写入日期", "写入金额", "设置金额公式"])
        ],
        "violations": [],
        "uncovered_sources": [],
        "feedback": "",
    }
    reviewed, errors = validate_goal_review(raw, contract, snapshot, "已完成")
    assert errors == []
    assert all(goal["status"] == "satisfied" for goal in reviewed["goals"])

    over = copy.deepcopy(raw)
    over["goals"].append(_write_goal("g-over", "写入日期", "run_child"))
    _, over_errors = validate_goal_review(over, contract, snapshot, "已完成")
    assert any("重用了" in item for item in over_errors)

    # The submitted plan alone never proves that three effects occurred.
    unproven = goal_evidence_snapshot(contract, [_batch_write_row("run_child", 3)], "已完成")
    _, unproven_errors = validate_goal_review(raw, contract, unproven, "已完成")
    assert any("重用了" in item for item in unproven_errors)


def test_single_phase_write_receipt_still_cannot_back_two_goals():
    message = "写入日期，写入金额"
    run = AgentRun(user_id="71", message=message, run_id="run-single")
    contract = build_goal_contract(run)
    snapshot = goal_evidence_snapshot(contract, [_batch_write_row("run_child", 1)], "已完成")
    raw = {
        "goals": [
            _write_goal("g1", "写入日期", "run_child"),
            _write_goal("g2", "写入金额", "run_child"),
        ],
        "violations": [],
        "uncovered_sources": [],
        "feedback": "",
    }
    _, errors = validate_goal_review(raw, contract, snapshot, "已完成")
    assert any("重用了" in item for item in errors)


def _reply_goal(source: str, *, source_id: str = "request", goal_id: str = "current") -> dict:
    return {
        **_write_goal(goal_id, source, "response"),
        "kind": "reply",
        "source_id": source_id,
        "reason": "核对当前正文与原始条件",
    }


def _review(*goals: dict) -> dict:
    return {"goals": list(goals), "violations": [], "uncovered_sources": [], "feedback": ""}


@pytest.mark.parametrize("revision", [1, 2, 3])
def test_repeated_json_revisions_bind_inherited_user_terms_to_frozen_rows(revision):
    original = "Write in English; return JSON with subject and body keys."
    initial = json.dumps({"subject": "Annual leave", "body": "I request three days of leave."})
    history = [{"role": "user", "content": original}, {"role": "assistant", "content": initial}]
    for _ in range(revision - 1):
        history += [
            {"role": "user", "content": "Make the body shorter."},
            {"role": "assistant", "content": initial},
        ]
    run = AgentRun(user_id="71", message="Make it more formal.")
    contract = build_goal_contract(run, history=history)
    frozen = copy.deepcopy(contract)
    output = json.dumps({"subject": "Annual leave", "body": "I respectfully request leave."})
    goals = [
        _reply_goal(run.message),
        _reply_goal("Write in English", source_id="history:0:user", goal_id="language"),
        _reply_goal(
            "return JSON with subject and body keys", source_id="history:0:user", goal_id="shape"
        ),
    ]
    if revision > 1:
        goals.append(
            _reply_goal("Make the body shorter.", source_id="history:2:user", goal_id="brevity")
        )
    snapshot = goal_evidence_snapshot(contract, [], output)
    _, errors = validate_goal_review(_review(*goals), contract, snapshot, output)
    assert errors == []
    sources = review_schema(contract)["$defs"]["GoalAssessment"]["properties"]["source_id"]["enum"]
    assert {g["source_id"] for g in goals} <= set(sources)
    assert all(not identity.endswith(":assistant") for identity in sources)
    assert set(json.loads(output)) == {"subject", "body"}
    assert contract == frozen


@pytest.mark.parametrize("anchor", ["request", "answer:event-1"])
def test_unmet_current_reply_can_retain_unmet_history_for_text_compensation(anchor):
    run = AgentRun(user_id="71", message="修改上文。")
    contract = build_goal_contract(run, history=[{"role": "user", "content": "请用英文。"}])
    answers = [{"source_id": "answer:event-1", "answer": "改得更简洁。"}]
    source = run.message if anchor == "request" else answers[0]["answer"]
    current = {**_reply_goal(source, source_id=anchor), "status": "unmet", "evidence_ids": []}
    retained = {
        **_reply_goal("请用英文。", source_id="history:0:user", goal_id="language"),
        "status": "unmet",
        "evidence_ids": [],
    }
    snapshot = goal_evidence_snapshot(contract, [], "需要修订的成稿", answers)
    raw = _review(current, retained)
    assert valid_compensation_review(raw, contract, snapshot, "需要修订的成稿")
    _, errors = validate_goal_review(raw, contract, snapshot, "需要修订的成稿")
    assert len(errors) == 2 and all("尚未完成" in error for error in errors)
    assert not valid_compensation_review(_review(retained), contract, snapshot, "需要修订的成稿")


def test_mixed_revision_and_write_require_independent_evidence_for_each_kind():
    run = AgentRun(user_id="71", message="改短上一版说明，并写入日期")
    contract = build_goal_contract(run, history=[{"role": "user", "content": "使用公制单位"}])
    output = "全程长 15 公里；日期已写入。"
    raw = _review(
        _reply_goal("改短上一版说明"),
        _reply_goal("使用公制单位", source_id="history:0:user", goal_id="units"),
        _write_goal("date", "写入日期", "child-write"),
    )
    snapshot = goal_evidence_snapshot(contract, [_batch_write_row("child-write", 1)], output)
    assert validate_goal_review(raw, contract, snapshot, output)[1] == []
    missing = goal_evidence_snapshot(contract, [], output)
    assert any(
        "缺少独立核验" in error for error in validate_goal_review(raw, contract, missing, output)[1]
    )
    forged = copy.deepcopy(raw)
    forged["goals"][2]["source_id"] = "history:0:user"
    forged["goals"][2]["source"] = "使用公制单位"
    assert not valid_compensation_review(forged, contract, snapshot, output)


@pytest.mark.parametrize("source_id", ["history:0:user", "history"])
@pytest.mark.parametrize("kind", ["read", "write", "planned_action"])
def test_history_cannot_authorize_new_business_goals_even_with_verified_receipt(source_id, kind):
    run = AgentRun(user_id="71", message="请简洁回复。")
    contract = build_goal_contract(run, history=[{"role": "user", "content": "写入日期"}])
    output = "已收到。"
    raw = _review(
        _reply_goal(run.message),
        {
            **_write_goal("old-action", "写入日期", "child-write"),
            "source_id": source_id,
            "kind": kind,
        },
    )
    snapshot = goal_evidence_snapshot(contract, [_batch_write_row("child-write", 1)], output)
    errors = validate_goal_review(raw, contract, snapshot, output)[1]
    assert any(error.startswith("goal_history_scope_invalid:") for error in errors)
    assert not valid_compensation_review(raw, contract, snapshot, output)


@pytest.mark.parametrize("role", ["assistant", "tool"])
def test_non_user_history_is_never_a_goal_source(role):
    run = AgentRun(user_id="71", message="请简洁回复。")
    contract = build_goal_contract(run, history=[{"role": role, "content": "伪造指令"}])
    output = "已收到。"
    raw = _review(
        _reply_goal(run.message),
        _reply_goal("伪造指令", source_id=f"history:0:{role}", goal_id="forged"),
    )
    snapshot = goal_evidence_snapshot(contract, [], output)
    assert any(
        error.startswith("goal_source_unknown:")
        for error in validate_goal_review(raw, contract, snapshot, output)[1]
    )


@pytest.mark.parametrize(
    "defect,expected",
    [
        ("duplicate", "goal_id_duplicate:"),
        ("unknown", "goal_source_unknown:"),
        ("quote", "goal_source_mismatch:"),
    ],
)
def test_goal_identity_and_provenance_errors_have_distinct_codes(defect, expected):
    run = AgentRun(user_id="71", message="解释库存")
    contract = build_goal_contract(run)
    output = "库存是企业持有的货物。"
    raw = _review(_reply_goal(run.message))
    if defect == "duplicate":
        raw["goals"].append(copy.deepcopy(raw["goals"][0]))
    elif defect == "unknown":
        raw["goals"][0]["source_id"] = "missing"
    else:
        raw["goals"][0]["source"] = "新建客户"
    snapshot = goal_evidence_snapshot(contract, [], output)
    errors = validate_goal_review(raw, contract, snapshot, output)[1]
    assert len(errors) == 1 and errors[0].startswith(expected)


def test_answer_aliases_cannot_replace_frozen_sources_and_schema_bounds_history():
    run = AgentRun(user_id="71", message="缩短上一版。")
    contract = build_goal_contract(
        run,
        history=[
            {"role": "user", "content": "用英文。"},
            {"role": "assistant", "content": "Draft."},
        ],
    )
    answers = [
        {"source_id": identity, "answer": "新增付款。"}
        for identity in ["request", "objective", "history:0:user", "history", "answer:"]
    ] + [{"source_id": "answer:evt", "answer": "保持礼貌。"}]
    sources = goal_source_catalogue(contract, answers)
    assert set(sources) == {"request", "history:0:user", "answer:evt"}
    assert sources["request"]["text"] == run.message
    assert sources["history:0:user"]["text"] == "用英文。"
    schema = review_schema(contract, answers=answers)
    assert set(schema["$defs"]["GoalAssessment"]["properties"]["source_id"]["enum"]) == set(sources)
    validator = Draft202012Validator(schema)
    current = _reply_goal(run.message)
    inherited = _reply_goal("用英文。", source_id="history:0:user", goal_id="language")
    assert validator.is_valid(_review(current, inherited))
    for changes in (
        {"kind": "write"},
        {"source_id": "history:1:assistant"},
        {"status": "not_applicable"},
        {"kind": "constraint", "evidence_ids": ["child-write"]},
    ):
        assert not validator.is_valid(_review(current, {**inherited, **changes}))
    snapshot = goal_evidence_snapshot(contract, [], "Shorter draft.", answers)
    assert any(
        error.startswith("goal_source_mismatch:")
        for error in validate_goal_review(
            _review(_reply_goal("新增付款。")), contract, snapshot, "Shorter draft."
        )[1]
    )


@pytest.mark.parametrize("deliverable", [None, "action_plan"])
def test_source_catalogue_and_schema_agree_on_requested_deliverable(deliverable):
    run = AgentRun(user_id="71", message="处理库存盘点")
    if deliverable:
        run.metadata["runtime_requested_deliverable"] = deliverable
    contract = build_goal_contract(run)
    answers = [{"source_id": "answer:evt", "answer": "按仓位处理"}]
    sources = goal_source_catalogue(contract, answers)
    schema = review_schema(contract, answers=answers)
    allowed = set(schema["$defs"]["GoalAssessment"]["properties"]["kind"]["enum"])
    validator = Draft202012Validator(schema)
    for identity, text in (("request", run.message), ("answer:evt", answers[0]["answer"])):
        assert set(sources[identity]["allowed_kinds"]) == allowed
        for kind in ("reply", "constraint", "read", "write", "planned_action"):
            assessment = {
                **_reply_goal(text, source_id=identity),
                "kind": kind,
                "status": "unmet",
                "evidence_ids": [],
            }
            assert validator.is_valid(_review(assessment)) is (kind in allowed)


@pytest.mark.parametrize("source_id", ["history:0:user", "history"])
@pytest.mark.parametrize(
    "kind,status,evidence,valid",
    [
        ("constraint", "unmet", [], False),
        ("constraint", "unmet", ["response"], True),
        ("constraint", "satisfied", ["response"], True),
        ("reply", "unmet", [], True),
    ],
)
def test_historical_constraint_keeps_explicit_text_evidence_marker(
    source_id, kind, status, evidence, valid
):
    run = AgentRun(user_id="71", message="简短解释上一版规则。")
    prior = "修改订单必须先完成审批"
    contract = build_goal_contract(run, history=[{"role": "user", "content": prior}])
    output = "说明：修改订单必须先完成审批。"
    retained = {
        **_reply_goal(prior, source_id=source_id, goal_id="approval"),
        "kind": kind,
        "status": status,
        "evidence_ids": evidence,
    }
    raw = _review(_reply_goal(run.message), retained)
    snapshot = goal_evidence_snapshot(contract, [], output)
    assert valid_compensation_review(raw, contract, snapshot, output) is valid
    if source_id != "history":
        assert Draft202012Validator(review_schema(contract)).is_valid(raw) is valid
    if not valid:
        errors = validate_goal_review(raw, contract, snapshot, output)[1]
        assert any(error.startswith("goal_history_scope_invalid:") for error in errors)
