"""事故小组 handler 输出持久化（脱敏）+ Para completed 时 scout/verify 不再被 llm_md/echo 判失败。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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


PARA_OK = {
    "handler": "para_delegate",
    "ok": True,
    "accepted": True,
    "completed": True,
    "status": "para_task_completed",
    "para_result": {"task_id": "p1", "merge_commit_sha": "a" * 40},
}


@pytest.mark.parametrize(
    "outputs,expected",
    [
        (
            [
                PARA_OK,
                {"handler": "llm_md", "output": ""},
                {"handler": "echo", "output": ""},
            ],
            True,
        ),
        ([{"handler": "llm_md", "output": "看起来修好了"}], False),
        ([PARA_OK, {"handler": "llm_md", "error": "llm failed"}], False),
        (
            [
                {"handler": "para_delegate", "ok": False, "error": "120s 内无代码变更"},
                {"handler": "llm_md", "output": "x"},
            ],
            False,
        ),
    ],
)
def test_handler_execution_contract(outputs, expected):
    assert execution_succeeded(_employee_result(outputs)) is expected


@pytest.mark.parametrize(
    "completed,accepted,expected",
    [
        (True, True, []),
        (False, True, ["para_not_completed"]),
        (True, False, ["para_not_completed"]),
    ],
)
@pytest.mark.parametrize("snapshot", [{"task_id": "p1"}, {"id": "p1"}, {"task": {"id": "p1"}}])
def test_real_ledger_accepts_digest_evidence(tmp_path, completed, accepted, expected, snapshot):
    checker = (
        Path(__file__).resolve().parents[3] / "FHD/scripts/release/ticket_loop_ledger_check.py"
    )
    spec = importlib.util.spec_from_file_location("ticket_ledger", checker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    digest = handler_output_digest(
        _employee_result(
            [{**PARA_OK, "para_result": snapshot, "completed": completed, "accepted": accepted}]
        )
    )
    (tmp_path / "handlers.json").write_text(json.dumps(digest))
    errors = module.check_para_processing(
        "resolved",
        {"para_task_id": "p1", "handler_outputs_evidence": "handlers.json"},
        {},
        tmp_path,
    )
    assert [e["code"] for e in errors] == expected


def test_digest_redacts_secrets_and_drops_raw_payload():
    res = _employee_result(
        [
            {
                **PARA_OK,
                "api_key": "sk-live-should-not-appear-123456",
                "output": {"summary": "处理说明 token=abc"},
                "error": "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123 token=abc",
                "tool_fallback_attempts": [
                    {
                        "tool_name": "claude_code",
                        "status": "failed",
                        "error": "not logged in",
                    }
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
    assert digest["outputs"][0]["summary"] == "处理说明 token=[redacted]"
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
            [
                PARA_OK,
                {"handler": "llm_md", "output": ""},
                {"handler": "echo", "output": ""},
            ]
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
    assert scout["status"] == "completed"
    assert scout["handler_outputs"]["outputs"][0]["completed"] is True
