"""Regressions for unknown outcomes, original-task readback, and verification identity."""

from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest

from modstore_server import para_delegate_handler as para
from modstore_server.customer_issue_delivery_contract import (
    execution_pending,
    execution_requires_reconciliation,
    execution_succeeded,
    para_task_succeeded,
    team_succeeded,
)
from modstore_server.incident_team_failure_loop import run_failure_loop
from modstore_server.models import IncidentEvent, get_session_factory
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db


@pytest.mark.parametrize(
    "fields",
    [
        {"accepted": True, "task_id": "original", "status": "para_task_timeout"},
        {"accepted": True, "task_id": "original", "status": "para_task_poll_failed"},
        {
            "queued": True,
            "outbox_path": "/controlled/unknown",
            "status": "para_api_failed_outboxed",
        },
        {
            "outcome": "unknown",
            "requires_reconciliation": True,
            "status": "handler_failed",
        },
    ],
)
def test_outer_recovery_never_replays_unknown_work(fields):
    output = {
        "handler": "para_delegate",
        "ok": False,
        "completed": False,
        "error": "503 ENOENT old CLI log",
        **fields,
    }
    result = {
        "handler_failed": True,
        "status": "handler_failed",
        "error": "503",
        "result": {"outputs": [output]},
    }
    row = {"role": "fix", "employee_id": "fix", "ok": False, "result": result}
    retry = Mock(side_effect=AssertionError("must not create another attempt"))
    followups = run_failure_loop(
        retry_member=retry,
        event_id=1,
        results=[row],
        team_plan={},
        payload={},
        event_type="issue",
        source="test",
        uid=0,
    )
    assert followups[0]["action"] == "reconcile_original_attempt"
    assert row["status"] == "pending" and retry.call_count == 0
    assert execution_requires_reconciliation(result)
    assert execution_pending(result) and not execution_succeeded(result)


def test_general_cli_fallback_ignores_stale_error_logs_for_running_task(monkeypatch):
    once = Mock(
        return_value={
            "handler": "para_delegate",
            "ok": False,
            "accepted": True,
            "completed": False,
            "task_id": "original",
            "status": "para_task_timeout",
            "para_result": {
                "task_status": "running",
                "logs_tail": [{"content": "spawn codex ENOENT"}],
            },
        }
    )
    monkeypatch.setattr(para, "_post_para_api_once", once)
    monkeypatch.setenv("MODSTORE_PARA_TOOL_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_PARA_TOOL_FALLBACK_ORDER", "codex,cursor,trae")
    result = para._post_para_api({"tool_name": "codex"})
    assert once.call_count == 1 and result["task_id"] == "original"


def _api(monkeypatch, transport, devices=None):
    client = httpx.Client
    monkeypatch.setattr(
        para.httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(transport), **kw),
    )
    monkeypatch.setattr(para, "_api_base", lambda: "https://controlled.invalid")
    monkeypatch.setattr(para, "_allow_local_workdir", lambda: True)
    monkeypatch.setattr(
        para,
        "_get_para_token",
        lambda *a: {"token": "controlled-test", "source": "test"},
    )
    monkeypatch.setattr(
        para,
        "_resolve_dispatch_devices",
        lambda *a: (2, devices or [{"id": "device-1", "_selected_tool": "codex"}], ""),
    )
    monkeypatch.setenv("MODSTORE_CREDENTIAL_TASK_GRANTS", "0")
    monkeypatch.setattr(para, "_write_outbox", lambda req: "controlled-outbox")


def test_existing_task_id_is_read_only_and_wrong_identity_never_completes(monkeypatch):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"task": {"id": "different", "status": "completed"}})

    _api(monkeypatch, transport)
    result = para._post_para_api_once(
        {"para_task_id": "original", "request_id": "attempt", "report_only": True}
    )
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/api/tasks/original")]
    assert result["task_id"] == "original" and not result["completed"]
    assert execution_requires_reconciliation(result)


@pytest.mark.parametrize(
    "state,expected",
    [
        ("running", "para_task_accepted"),
        ("queued", "para_task_accepted"),
        ("accepted", "para_task_accepted"),
        ("completed", "para_task_completed"),
        ("merged", "para_task_merged"),
        ("failed", "para_task_failed"),
        ("merge_conflict", "para_task_merge_conflict"),
        ("wrong_identity", "para_task_identity_mismatch"),
        ("missing_child", "para_task_incomplete"),
        ("failed_child", "para_task_incomplete"),
        ("wrong_device", "para_task_incomplete"),
    ],
)
def test_existing_task_nonblocking_readback_preserves_real_state(monkeypatch, state, expected):
    requests = []
    child = {"id": "child-1", "device_id": "device-1", "status": "completed"}
    task = {"id": "original", "status": state, "subTasks": [child]}
    if state in {"wrong_identity", "missing_child", "failed_child", "wrong_device"}:
        task["status"] = "completed"
    if state == "wrong_identity":
        task["id"] = "different"
    elif state == "missing_child":
        task["subTasks"] = []
    elif state == "failed_child":
        child["status"] = "failed"
    elif state == "wrong_device":
        task["subTasks"].append({"id": "child-2", "device_id": "different", "status": "completed"})

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"task": task})

    _api(monkeypatch, transport)
    monkeypatch.setattr(para.time, "sleep", lambda _: pytest.fail("Nonblocking readback slept"))
    result = para._post_para_api_once(
        {
            "para_task_id": "original",
            "request_id": "attempt",
            "report_only": True,
            "wait_for_para": False,
            "required_subtask_ids": ["child-1"],
            "planned_devices": (
                ["device-1", "device-2"] if state == "wrong_device" else ["device-1"]
            ),
        }
    )
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/api/tasks/original")]
    assert result["task_id"] == "original" and result["status"] == expected
    assert result["para_result"]["task_status"] == task["status"]
    assert result["completed"] is (state in {"completed", "merged"})
    assert execution_succeeded(result) is (state in {"completed", "merged"})
    assert execution_requires_reconciliation(result) is (
        state not in {"completed", "merged", "failed", "merge_conflict"}
    )


@pytest.mark.parametrize("wait_flag", [True, None])
def test_existing_task_explicit_or_default_wait_still_polls_to_completion(monkeypatch, wait_flag):
    requests = []
    monkeypatch.setenv("MODSTORE_PARA_WAIT_FOR_COMPLETION", "1")

    def transport(request):
        requests.append(request)
        status = "running" if len(requests) == 1 else "completed"
        return httpx.Response(200, json={"task": {"id": "original", "status": status}})

    _api(monkeypatch, transport)
    sleep = Mock()
    monkeypatch.setattr(para.time, "sleep", sleep)
    result = para._post_para_api_once(
        {"para_task_id": "original", "report_only": True, "wait_for_para": wait_flag}
    )
    assert result["completed"] and result["status"] == "para_task_completed"
    assert [(r.method, r.url.path) for r in requests] == [("GET", "/api/tasks/original")] * 2
    sleep.assert_called_once()


def test_post_response_loss_retains_unknown_and_never_falls_back(monkeypatch):
    posts = []

    def transport(request):
        posts.append(request)
        raise httpx.ReadTimeout("POST response lost", request=request)

    _api(monkeypatch, transport)
    result = para._post_para_api(
        {"report_only": True, "request_id": "same-attempt", "tool_name": "codex"}
    )
    assert len(posts) == 1 and posts[0].method == "POST"
    assert result["requires_reconciliation"] and result["retryable"] is False


def test_fleet_rejection_remains_partial_and_keeps_required_children(monkeypatch):
    posts = []

    def transport(request):
        if request.method == "POST":
            posts.append(json.loads(request.content))
            if len(posts) == 2:
                return httpx.Response(409, json={"error": "second device refused"})
            return httpx.Response(
                200, json={"task": {"id": "original"}, "subtask": {"id": "child-1"}}
            )
        return httpx.Response(
            200,
            json={
                "task": {
                    "id": "original",
                    "status": "completed",
                    "subTasks": [{"id": "child-1", "status": "completed"}],
                }
            },
        )

    _api(monkeypatch, transport, devices=[{"id": "device-1"}, {"id": "device-2"}])
    result = para._post_para_api_once(
        {"report_only": True, "request_id": "attempt", "wait_for_para": True}
    )
    assert len(posts) == 2 and result["partial"] and not result["completed"]
    assert result["planned_devices"] == ["device-1", "device-2"]
    assert result["required_subtask_ids"] == ["child-1"]
    assert result["dispatch_failures"][0]["device_id"] == "device-2"
    assert not execution_succeeded(result)


@pytest.mark.parametrize(
    "task",
    [
        {"id": "other", "status": "completed"},
        {
            "id": "original",
            "status": "completed",
            "subTasks": [{"id": "child", "status": "failed"}],
        },
        {"id": "original", "status": "completed", "subTasks": []},
    ],
)
def test_required_child_and_task_identity_cannot_be_invented(task):
    assert not para_task_succeeded(task, "original", ["child"])


def test_empty_webhook_200_is_not_execution_success(monkeypatch):
    monkeypatch.setattr(para, "_webhook_url", lambda: "https://controlled.invalid/webhook")
    monkeypatch.setattr(para.httpx, "post", lambda *a, **kw: httpx.Response(200, json={}))
    result = para._post_webhook({"request_id": "attempt"})
    assert not result["ok"] and not execution_succeeded(result)
    assert result["requires_reconciliation"]


def test_new_fix_always_invalidates_old_successful_verify(monkeypatch):
    calls = []

    def retry(**kw):
        role = kw["member"]["role"]
        calls.append(role)
        return (
            {"status": "success", "attempt_id": "new-fix"}
            if role == "fix"
            else {"ok": False, "status": "failed", "error": "new version failed"}
        )

    rows = [
        {
            "role": "scout",
            "employee_id": "scout",
            "ok": True,
            "result": {"status": "success"},
        },
        {
            "role": "fix",
            "employee_id": "fix",
            "ok": False,
            "attempt_id": "old-fix",
            "result": {"handler_failed": True, "error": "SyntaxError"},
        },
        {
            "role": "verify",
            "employee_id": "verify",
            "ok": True,
            "verified_fix_attempt_id": "old-fix",
            "result": {"status": "success"},
        },
    ]
    run_failure_loop(
        retry_member=retry,
        event_id=1,
        results=rows,
        team_plan={},
        payload={},
        event_type="issue",
        source="test",
        uid=0,
    )
    assert calls == ["fix", "verify"]
    assert not rows[2]["ok"] and not team_succeeded(rows)
    rows[2].update(ok=True, verified_fix_attempt_id="old-fix")
    assert not team_succeeded(rows)


def test_dispatch_intent_survives_unknown_exception_and_restart(fresh_db, monkeypatch):
    from modstore_server import incident_team_orchestrator as orchestrator
    from modstore_server.node_coordinator import current_claim

    sf = get_session_factory()
    with sf() as db:
        event = IncidentEvent(event_type="on_error", source="controlled", payload_json="{}")
        db.add(event)
        db.commit()
        event_id = event.id
    monkeypatch.setattr(
        orchestrator,
        "build_incident_team",
        lambda eid: {
            "team": [{"role": role, "employee_id": role} for role in ("scout", "fix", "verify")]
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {},
    )
    calls = []

    def lost_receipt(*a, **kw):
        assert current_claim()["event_id"] == event_id
        with sf() as db:
            persisted = json.loads(db.get(IncidentEvent, event_id).payload_json)["_team_claim"][
                "team"
            ][0]
            assert persisted["status"] == "dispatching" and persisted["attempt_id"]
        calls.append(a)
        raise RuntimeError("execution receipt lost")

    monkeypatch.setattr(orchestrator, "execute_employee_task", lost_receipt)
    result = orchestrator.dispatch_incident_team(event_id)
    assert result["requires_reconciliation"]
    orchestrator.dispatch_incident_team(event_id)
    assert len(calls) == 1


def test_late_receipt_updates_only_original_attempt(fresh_db):
    from modstore_server.incident_team_completion import persist_late_role_result

    sf = get_session_factory()
    with sf() as db:
        event = IncidentEvent(
            event_type="on_error",
            source="controlled",
            payload_json=json.dumps(
                {
                    "_team_claim": {
                        "team": [
                            {
                                "role": "fix",
                                "attempt_id": "original",
                                "status": "dispatching",
                                "ok": False,
                            }
                        ]
                    }
                }
            ),
        )
        db.add(event)
        db.commit()
        event_id = event.id
    persist_late_role_result(event_id, "fix", "fix", "original", {"status": "success"})
    with sf() as db:
        row = json.loads(db.get(IncidentEvent, event_id).payload_json)["_team_claim"]["team"][0]
        assert row["ok"] and row["attempt_id"] == "original"
    persist_late_role_result(event_id, "fix", "fix", "superseded", {"status": "failed"})
    with sf() as db:
        row = json.loads(db.get(IncidentEvent, event_id).payload_json)["_team_claim"]["team"][0]
        assert row["ok"] and row["attempt_id"] == "original"


def test_missing_second_post_receipt_requires_device_bound_readback():
    first = {"id": "child-1", "status": "completed", "device_id": "device-1"}
    task = {"id": "original", "status": "completed", "subTasks": [first]}
    assert not para_task_succeeded(task, "original", ["child-1"], ["device-1", "device-2"])
    task["subTasks"].append({"id": "child-2", "status": "completed", "device_id": "wrong-device"})
    assert not para_task_succeeded(task, "original", ["child-1"], ["device-1", "device-2"])
    task["subTasks"][1]["device_id"] = "device-2"
    assert para_task_succeeded(task, "original", ["child-1"], ["device-1", "device-2"])
