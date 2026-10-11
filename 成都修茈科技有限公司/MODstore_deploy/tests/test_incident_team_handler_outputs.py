"""事故小组 handler 输出持久化（脱敏）+ Para completed 时 scout/verify 不再被 llm_md/echo 判失败。"""

from __future__ import annotations

import json

import pytest

import modstore_server.models as models
from modstore_server.customer_issue_delivery_contract import execution_succeeded
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.incident_team_orchestrator import dispatch_incident_team


def _employee_result(outputs, **extra):
    """execute_employee_task 成功路径的真实形状：顶层无 status/ok，结果在 result.outputs。"""
    return {
        "employee_id": "x",
        "result": {
            "task": "t",
            "handlers": [o.get("handler") for o in outputs],
            "outputs": outputs,
        },
        "llm_tokens": 0,
        **extra,
    }


PARA_OK = {"handler": "para_delegate", "ok": True, "status": "completed", "task_id": "p1"}


def test_para_completed_with_informational_rows_is_success():
    # 工单 37/38 的 scout（llm_md, echo, agent）/ verify（llm_md, echo）真实输出形状
    res = _employee_result(
        [PARA_OK, {"handler": "llm_md", "output": ""}, {"handler": "echo", "output": ""}]
    )
    assert execution_succeeded(res) is True


def test_informational_rows_alone_are_not_delivery():
    assert (
        execution_succeeded(_employee_result([{"handler": "llm_md", "output": "看起来修好了"}]))
        is False
    )


def test_informational_row_with_error_still_fails():
    res = _employee_result([PARA_OK, {"handler": "llm_md", "error": "llm failed"}])
    assert execution_succeeded(res) is False


def test_para_failure_is_not_masked():
    res = _employee_result(
        [
            {"handler": "para_delegate", "ok": False, "error": "120s 内未检测到有效代码变更"},
            {"handler": "llm_md", "output": "x"},
        ]
    )
    assert execution_succeeded(res) is False


def test_digest_redacts_secrets_and_drops_raw_payload():
    res = _employee_result(
        [
            {
                **PARA_OK,
                "api_key": "sk-live-should-not-appear-123456",
                "error": "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123 token=abc",
                "tool_fallback_attempts": [
                    {"tool_name": "claude_code", "status": "failed", "error": "not logged in"}
                ],
            },
            {"handler": "llm_md", "output": "长文本" * 100},
        ],
        cognition_error="password=hunter2 timeout",
    )
    digest = handler_output_digest(res)
    blob = json.dumps(digest, ensure_ascii=False)
    for secret in ("sk-live-should-not-appear", "ghp_abcdef", "hunter2", 'abc"'):
        assert secret not in blob
    assert digest["outputs"][0]["ok"] is True
    assert digest["outputs"][0]["tool_fallback_attempts"][0]["tool_name"] == "claude_code"
    assert digest["outputs"][1] == {"handler": "llm_md", "output_chars": 300}
    assert digest["llm_tokens"] == 0


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "team_outputs.sqlite"))
    models.init_db()
    from tests.test_customer_service_api import _make_user

    _make_user("team-outputs-admin", admin=True)
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def test_dispatch_persists_handler_outputs_and_team_ok(fresh_db, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        ev = models.IncidentEvent(
            event_type="on_error",
            source="unit",
            payload_json=json.dumps({"summary": "handler outputs"}),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        event_id = ev.id

    def fake_execute(employee_id, task, env=None, user_id=0, **kwargs):
        if employee_id == "fix-1":
            return _employee_result([PARA_OK])
        return _employee_result(
            [PARA_OK, {"handler": "llm_md", "output": ""}, {"handler": "echo", "output": ""}]
        )

    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.execute_employee_task", fake_execute
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.build_incident_team",
        lambda eid: {
            "candidates": ["scout-1", "fix-1", "verify-1"],
            "code_owner": "",
            "code_owner_match": {},
            "event_id": eid,
            "team": [
                {"employee_id": "scout-1", "role": "scout"},
                {"employee_id": "fix-1", "role": "fix"},
                {"employee_id": "verify-1", "role": "verify"},
            ],
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )

    result = dispatch_incident_team(event_id)
    assert result["ok"] is True
    with sf() as s:
        claim = json.loads(s.get(models.IncidentEvent, event_id).payload_json)["_team_claim"]
    assert claim["ok"] is True
    assert claim["handler_failed_roles"] == []
    scout = next(r for r in claim["team"] if r["role"] == "scout")
    assert [o["handler"] for o in scout["handler_outputs"]["outputs"]] == [
        "para_delegate",
        "llm_md",
        "echo",
    ]
    assert scout["handler_outputs"]["outputs"][0]["status"] == "completed"
