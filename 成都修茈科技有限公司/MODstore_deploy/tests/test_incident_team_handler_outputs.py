"""事故小组 handler 输出持久化（脱敏）+ Para completed 时 scout/verify 不再被 llm_md/echo 判失败。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import modstore_server.models as models
from modstore_server.customer_issue_delivery_contract import execution_pending, execution_succeeded
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.incident_team_orchestrator import dispatch_incident_team
from tests.test_para_first_no_planning_llm import fresh_db as fresh_db


def _employee_result(outputs, **extra):
    """真实执行结果的嵌套形状，成功不依赖顶层 status/ok。"""
    return {
        "result": {"handlers": [o.get("handler") for o in outputs], "outputs": outputs},
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


INFO = [{"handler": h, "output": ""} for h in ("llm_md", "echo")]


@pytest.mark.parametrize(
    "outputs,expected",
    [
        ([PARA_OK, *INFO], True),
        ([{"handler": "llm_md", "output": "看起来修好了"}], False),
        ([PARA_OK, {"handler": "llm_md", "error": "llm failed"}], False),
        ([{**PARA_OK, "completed": False, "status": "para_task_accepted"}, INFO[0]], False),
        ([{**PARA_OK, "accepted": False}], False),
        ([{**PARA_OK, "para_result": {}}], False),
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


@pytest.mark.parametrize(
    "completed,terminal",
    [
        (True, "completed"),
        (False, "completed"),
        (False, "failed"),
        (False, "missing"),
        (False, "closed"),
        (False, "reopened"),
    ],
)
def test_dispatch_persists_handler_outputs_and_team_ok(fresh_db, monkeypatch, completed, terminal):
    from modstore_server.models_cs import (
        CustomerServiceAction,
        CustomerServiceMessage,
        CustomerServiceSession,
        CustomerServiceTicket,
    )

    sf = models.get_session_factory()
    with sf() as s:
        owner = s.query(models.User).first()
        cs = CustomerServiceSession(user_id=owner.id)
        s.add(cs)
        s.flush()
        ticket = CustomerServiceTicket(
            ticket_no="CS-PARA",
            session_id=cs.id,
            user_id=owner.id,
            title="原问题",
            summary="复现",
            intent="product_issue",
            status="processing",
            evidence_json="{}",
        )
        s.add(ticket)
        s.flush()
        ticket_id = ticket.id
        cr = models.EmployeeChangeRequest(
            source_employee_id="fix-1",
            change_kind="code_patch",
            status="applied",
            staged_commit_sha="a" * 40,
        )
        s.add(cr)
        s.flush()
        cr_id = cr.id
        ev = models.IncidentEvent(
            event_type="ops.intake.customer_ticket",
            source="customer_ticket",
            payload_json=json.dumps(
                {"summary": "handler outputs", "ticket_id": ticket_id, "user_id": owner.id}
            ),
            dispatched_count=0,
        )
        s.add(ev)
        s.commit()
        s.refresh(ev)
        event_id = ev.id

    def repair_actions(db):
        return db.query(CustomerServiceAction).filter_by(
            ticket_id=ticket_id, action_type="issue.repair.result"
        )

    def readback():
        with sf() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            resolution = json.loads(ticket.evidence_json)["resolution"]
            claim = json.loads(db.get(models.IncidentEvent, event_id).payload_json)["_team_claim"]
            messages = db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count()
            return ticket, resolution, claim, messages, repair_actions(db).count()

    para = {
        **PARA_OK,
        "completed": completed,
        "status": "para_task_completed" if completed else "para_task_accepted",
    }
    assert execution_pending(_employee_result([para])) is (not completed)

    def fake_execute(employee_id, task, env=None, user_id=0, **kwargs):
        companion = [{"handler": "change_request", "ok": True, "change_request_id": cr_id}]
        return _employee_result([para, *(INFO if employee_id != "fix-1" else companion)])

    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.execute_employee_task", fake_execute
    )
    monkeypatch.setattr(
        "modstore_server.incident_team_orchestrator.build_incident_team",
        lambda eid: {
            "event_id": eid,
            "team": [
                {"employee_id": f"{role}-1", "role": role} for role in ("scout", "fix", "verify")
            ],
        },
    )
    monkeypatch.setattr(
        "modstore_server.release_recovery_orchestrator.maybe_execute_recovery",
        lambda **kw: {"ok": False, "skipped": True},
    )

    result = dispatch_incident_team(event_id)
    assert result["ok"] is completed
    ticket, resolution, claim, _, repairs = readback()
    assert repairs == int(completed)
    assert resolution["repair_verified"] is completed
    assert resolution["state"] == ("awaiting_delivery" if completed else "processing")
    assert ticket.status == "processing" and ticket.closed_at is None
    if not completed:
        assert ticket.decision_status == "pending"
    assert claim["ok"] is completed
    assert claim["handler_failed_roles"] == []
    scout = next(r for r in claim["team"] if r["role"] == "scout")
    assert [o["handler"] for o in scout["handler_outputs"]["outputs"]] == [
        "para_delegate",
        "llm_md",
        "echo",
    ]
    assert scout["status"] == ("completed" if completed else "pending")
    assert scout["handler_outputs"]["outputs"][0]["completed"] is completed

    if not completed:
        import httpx

        from modstore_server.incident_team_completion import reconcile_pending_teams

        monkeypatch.setattr(
            "modstore_server.incident_team_orchestrator.execute_employee_task",
            lambda *a, **kw: pytest.fail("续读不能重新派单"),
        )
        if terminal == "missing":
            with sf() as db:
                event = db.get(models.IncidentEvent, event_id)
                data = json.loads(event.payload_json)
                for row in data["_team_claim"]["team"]:
                    row["handler_outputs"]["outputs"][0].pop("task_id")
                event.payload_json = json.dumps(data)
                db.commit()
            reconcile_pending_teams(
                event_id=event_id, fetcher=lambda *a: pytest.fail("无号不能猜测读取")
            )
            ticket, resolution, _, _, _ = readback()
            assert resolution["state"] == "awaiting_manual_review"
            assert not resolution["repair_verified"] and ticket.closed_at is None
            return
        if terminal in {"closed", "reopened"}:
            with sf() as db:
                ticket = db.get(CustomerServiceTicket, ticket_id)
                ticket.status = "resolved" if terminal == "closed" else "processing"
                data = json.loads(ticket.evidence_json)
                data["resolution"]["state"] = terminal
                ticket.evidence_json = original_decision = json.dumps(data)
                messages = db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count()
                db.commit()

            def fetch(base, tid):
                return {"id": tid, "status": "completed"}

            assert reconcile_pending_teams(event_id=event_id, fetcher=fetch)["changed"] == 1
            ticket, _, claim, latest_messages, repairs = readback()
            assert repairs == 0 and ticket.evidence_json == original_decision
            assert latest_messages == messages
            assert claim["ok"]
            assert reconcile_pending_teams(event_id=event_id, fetcher=fetch)["changed"] == 0
            return
        for mismatch in ("owner", "incident"):
            with sf() as db:
                target = db.get(
                    models.IncidentEvent if mismatch == "owner" else CustomerServiceTicket,
                    event_id if mismatch == "owner" else ticket_id,
                )
                field = "payload_json" if mismatch == "owner" else "evidence_json"
                original = getattr(target, field)
                data = json.loads(original)
                if mismatch == "owner":
                    data["user_id"] += 1
                else:
                    data["resolution"]["incident_event_id"] = event_id + 1
                setattr(target, field, json.dumps(data))
                db.commit()
            assert (
                reconcile_pending_teams(
                    event_id=event_id, fetcher=lambda base, tid: {"id": tid, "status": "completed"}
                )["changed"]
                == 0
            )
            with sf() as db:
                assert not json.loads(db.get(CustomerServiceTicket, ticket_id).evidence_json)[
                    "resolution"
                ]["repair_verified"]
                setattr(
                    db.get(type(target), event_id if mismatch == "owner" else ticket_id),
                    field,
                    original,
                )
                db.commit()
        for error in (
            httpx.HTTPStatusError(
                "token=secret",
                request=httpx.Request("GET", "http://para"),
                response=httpx.Response(401),
            ),
            httpx.ConnectError("token=secret"),
        ):

            def broken_fetch(*args):
                raise error

            assert reconcile_pending_teams(event_id=event_id, fetcher=broken_fetch)["changed"] == 1
            ticket, resolution, _, _, _ = readback()
            assert resolution["state"] == "processing"
            assert "secret" not in ticket.evidence_json
            assert "读取失败" in resolution["processing"][0]["poll_error"]
        models._SessionFactory = None  # Recreate database access to simulate process restart.
        sf = models.get_session_factory()

        def terminal_fetch(base, task_id):
            assert task_id == "p1"
            return {"id": task_id, "status": terminal, "summary": "修复结果"}

        assert reconcile_pending_teams(event_id=event_id, fetcher=terminal_fetch)["changed"] == 1
        with sf() as db:
            ticket = db.get(CustomerServiceTicket, ticket_id)
            resolution = json.loads(ticket.evidence_json)["resolution"]
            assert resolution["repair_verified"] is (terminal == "completed")
            assert resolution["state"] == (
                "awaiting_delivery" if terminal == "completed" else "repair_failed"
            )
            assert ticket.closed_at is None and ticket.status == "processing"
            count = db.query(CustomerServiceMessage).filter_by(ticket_id=ticket_id).count()
            from modstore_server.customer_issue_shared_release import (
                bind_shared_release,
                record_worker_repair,
            )
            from tests.test_customer_issue_delivery_pipeline import github_fixture

            actions = repair_actions(db)
            assert actions.count() == int(terminal == "completed")
            if terminal == "completed":
                claim = json.loads(db.get(models.IncidentEvent, event_id).payload_json)[
                    "_team_claim"
                ]
                record_worker_repair(db, ticket, event_id, claim["team"])
                assert actions.count() == 1
                github_fixture(monkeypatch)
                target = bind_shared_release(db, ticket, "c" * 40)
                assert target and target["change_request_id"] == cr_id
                assert target["ticket_id"] == ticket_id and ticket.closed_at is None
                db.commit()
        assert reconcile_pending_teams(event_id=event_id, fetcher=terminal_fetch)["changed"] == 0
        assert dispatch_incident_team(event_id)["ok"] is (terminal == "completed")
        assert readback()[3] == count


def test_real_async_para_return_keeps_parent_task_id(monkeypatch):
    import httpx

    from modstore_server import para_delegate_handler as handler

    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://para")
    monkeypatch.setenv("MODSTORE_PARA_WAIT_FOR_COMPLETION", "0")
    monkeypatch.setattr(handler, "_get_para_token", lambda *a: {"token": "test", "source": "test"})
    monkeypatch.setattr(
        handler,
        "_resolve_dispatch_devices",
        lambda *a: ("local", [{"id": "d1", "_selected_tool": "cursor"}], ""),
    )
    monkeypatch.setattr(handler, "_force_single_device_attempt", lambda *a: {})
    client_class = httpx.Client
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json={"task": {"id": "parent-task"}, "subtask": {"id": "sub"}})

    monkeypatch.setattr(
        handler.httpx,
        "Client",
        lambda **kw: client_class(transport=httpx.MockTransport(respond), **kw),
    )
    result = handler._post_para_api_once(
        {"task": "test", "report_only": True, "repo_url": "https://github.com/example/test.git"}
    )
    assert result["accepted"] and not result["completed"]
    assert result["task_id"] == "parent-task"
    assert execution_pending(_employee_result([result]))
    assert requests == [("POST", "/api/tasks")]


def test_pending_pagination_does_not_starve_later_tasks(fresh_db, monkeypatch):
    from modstore_server import incident_team_completion as completion

    monkeypatch.setattr(completion, "_PENDING_CURSOR", 0)
    sf = models.get_session_factory()
    with sf.begin() as db:
        for index in range(3):
            outputs = [
                {
                    **PARA_OK,
                    "task_id": f"p{index}",
                    "completed": False,
                    "status": "para_task_accepted",
                }
            ]
            rows = [
                {
                    "role": role,
                    "ok": False,
                    "status": "pending",
                    "handler_outputs": handler_output_digest(_employee_result(outputs)),
                }
                for role in ("scout", "fix", "verify")
            ]
            db.add(
                models.IncidentEvent(
                    event_type="unit",
                    source="unit",
                    payload_json=json.dumps({"_team_claim": {"team": rows, "ok": False}}),
                )
            )
    seen = []

    def read(base, tid):
        seen.append(tid)
        return {"id": tid, "status": "completed" if tid == "p2" else "running"}

    assert completion.reconcile_pending_teams(limit=2, fetcher=read)["changed"] == 0
    assert set(seen) == {"p0", "p1"}
    assert completion.reconcile_pending_teams(limit=2, fetcher=read)["changed"] == 1
    assert set(seen) == {"p0", "p1", "p2"}
    assert completion.reconcile_pending_teams(limit=2, fetcher=read)["changed"] == 0
