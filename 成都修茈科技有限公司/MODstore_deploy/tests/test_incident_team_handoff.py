"""Handoffs bound optional context without dropping receipt identity or leaking raw data."""

import json

from modstore_server.incident_team_handoff import format_role_handoff, role_handoff


def test_long_handoff_is_valid_json_with_identity_and_real_references():
    result = {
        "ok": True,
        "status": "completed",
        "attempt_id": "attempt-7",
        "event_id": 7,
        "summary": "修复原因与边界" * 5000,
        "raw_payload": {"password": "must-never-appear"},
        "result": {
            "outputs": [
                {
                    "handler": "para_delegate",
                    "ok": True,
                    "accepted": True,
                    "completed": True,
                    "task_id": "original-para-task",
                    "change_request_id": 17,
                    "pull_request_url": "https://github.com/example/project/pull/17",
                    "summary": "真正完成并提交了变更",
                }
            ]
        },
    }
    text = format_role_handoff(result, "fix", max_chars=1600)
    handoff = json.loads(text)
    assert len(text) <= 1600
    assert handoff["identity"]["attempt_id"] == "attempt-7"
    assert handoff["references"][0]["task_id"] == "original-para-task"
    assert handoff["references"][0]["change_request_id"] == "17"
    assert handoff["succeeded"] is True
    assert "must-never-appear" not in text


def test_pending_or_error_never_becomes_success_in_handoff():
    for receipt in (
        {"ok": True, "accepted": True, "completed": False, "status": "pending"},
        {"ok": True, "status": "completed", "error": "execution failed"},
        None,
        {
            "ok": True,
            "status": "completed",
            "handler_outputs": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "ok": True,
                        "accepted": True,
                        "completed": False,
                        "task_id": "still-running",
                    }
                ]
            },
        },
    ):
        assert role_handoff(receipt, "scout")["succeeded"] is False


def test_persisted_digest_keeps_redacted_blockers_and_next_action():
    handoff = role_handoff(
        {
            "status": "failed",
            "attempt_id": "attempt-9",
            "handler_outputs": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "task_id": "task-9",
                        "error": "Authorization: Bearer synthetic-secret-value",
                        "next_step": "回读 task-9 原始任务",
                    }
                ]
            },
        },
        "scout",
    )
    encoded = json.dumps(handoff, ensure_ascii=False)
    assert "synthetic-secret-value" not in encoded
    assert handoff["next_actions"] == ["回读 task-9 原始任务"]
    assert handoff["references"][0]["task_id"] == "task-9"
