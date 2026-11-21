"""Durable manual handoffs keep the original management mandate and principal."""

from __future__ import annotations

import json

import pytest

from modstore_server import employee_autonomy_service as autonomy
from modstore_server import employee_handoff
from modstore_server import employee_orchestrator as _claim_orchestrator
from modstore_server import xiaoc_life_chat, xiaoc_life_store
from modstore_server.xiaoc_life_policy import LifePolicyError
from tests.test_workflow_nl_graph_skill_generation import _bootstrap

_REAL_DISPATCH_SUBTASKS = _claim_orchestrator.dispatch_subtasks


@pytest.fixture
def handoff_case(tmp_path, monkeypatch):
    models = _bootstrap(tmp_path, monkeypatch)
    state = {"level": 3}
    monkeypatch.setattr(xiaoc_life_store, "read_state", lambda: dict(state))
    monkeypatch.setattr(employee_handoff, "_target_exists", lambda *_: True)
    monkeypatch.setattr(autonomy, "_publish_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "modstore_server.notification_service.employee_message_to_boss", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "modstore_server.employee_collab_reporter.report_suggestion_dispatched",
        lambda *_a, **_k: None,
    )
    factory = models.get_session_factory()
    with factory() as session:
        first = models.User(username="other-admin", password_hash="x", is_admin=True)
        owner = models.User(username="original-owner", password_hash="x", is_admin=True)
        session.add_all([first, owner])
        session.commit()
        session.refresh(owner)
        session.expunge(owner)
    calls = []

    def dispatch(subtasks, **kwargs):
        from modstore_server import employee_executor

        calls.append(
            {
                "owner": kwargs["created_by_user_id"],
                "scope_active": xiaoc_life_chat.manual_life_scope_active(),
            }
        )
        result = employee_executor._actions_real(
            {"handlers": ["direct_python"]},
            {"input": {"suppress_employee_im": True}},
            subtasks[0].task_brief,
            subtasks[0].employee_id,
            kwargs["created_by_user_id"],
        )
        return {"ok": True, "results": [result]}

    output = tmp_path / "handoff-output.txt"

    def direct_action(*_args):
        output.write_text("executed once", encoding="utf-8")
        return {"handler": "direct_python", "ok": True, "output": "actual result"}

    monkeypatch.setattr("modstore_server.employee_orchestrator.dispatch_subtasks", dispatch)
    monkeypatch.setattr("modstore_server.employee_executor._action_direct_python", direct_action)
    return models, factory, owner, state, calls, output


def handoff():
    return employee_handoff.perform_handoff(
        source_employee_id="source",
        target_employee_id="target",
        reason="requires specialist",
        context="already observed facts",
        original_task="format the report",
    )


def test_downgrade_before_handoff_cannot_create_a_new_business_task(handoff_case):
    models, factory, owner, state, _calls, _output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        state["level"] = 1
        try:
            result = handoff()
        except LifePolicyError:
            result = {"ok": False}
    with factory() as session:
        assert session.query(models.EmployeeCollabThread).count() == 0
        assert session.query(models.EmployeeCollabMessage).count() == 0
        assert session.query(models.EmployeeSuggestion).count() == 0
    assert result["ok"] is False


def test_persisted_handoff_rechecks_level_and_preserves_original_owner(handoff_case):
    models, factory, owner, state, calls, output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        queued = handoff()
    assert queued["ok"] is True and queued["suggestion_id"]
    state["level"] = 1
    blocked = autonomy.dispatch_pending_suggestions()
    assert calls == [] and not output.exists()
    assert blocked["skipped"] == 1
    with factory() as session:
        row = session.get(models.EmployeeSuggestion, queued["suggestion_id"])
        assert row.status == "pending" and row.approved_at is None

    # Restoring capability resumes the same pending row; it does not invent another task.
    state["level"] = 3
    resumed = autonomy.dispatch_pending_suggestions()
    assert resumed["ok_count"] == 1 and output.read_text() == "executed once"
    assert calls == [{"owner": owner.id, "scope_active": True}]
    assert autonomy.dispatch_pending_suggestions()["processed"] == 0


def test_persisted_handoff_cannot_fall_back_to_a_different_administrator(handoff_case):
    models, factory, owner, _state, calls, output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        queued = handoff()
    with factory() as session:
        session.get(models.User, owner.id).is_admin = False
        session.commit()
    blocked = autonomy.dispatch_pending_suggestions()
    assert calls == [] and not output.exists()
    assert blocked["skipped"] == 1
    with factory() as session:
        assert session.get(models.EmployeeSuggestion, queued["suggestion_id"]).status == "pending"


def test_private_handoff_keeps_its_scope_when_management_is_l1(handoff_case):
    models, factory, owner, state, calls, output = handoff_case
    with factory() as session:
        session.get(models.User, owner.id).is_admin = False
        session.commit()
    owner.is_admin = False
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        queued = handoff()
    assert queued["ok"] is True
    state["level"] = 1
    assert autonomy.dispatch_pending_suggestions()["ok_count"] == 1
    assert output.exists() and calls == [{"owner": owner.id, "scope_active": False}]


def test_model_payload_cannot_replace_or_create_a_management_mandate(handoff_case):
    models, factory, owner, _state, _calls, _output = handoff_case

    def create():
        return autonomy.create_employee_suggestion(
            source_employee_id="source",
            summary="untrusted scope in model payload",
            payload={"_xiaoc_manual_scope": {"minimum_level": 1, "owner_user_id": 1}},
            target_employee_ids=["target"],
            emit_event=False,
            auto_dispatch=False,
        )["suggestion_id"]

    with xiaoc_life_chat.manual_life_scope(owner, 3):
        managed_id = create()
    private_id = create()
    with factory() as session:
        managed = json.loads(session.get(models.EmployeeSuggestion, managed_id).payload_json)
        private = json.loads(session.get(models.EmployeeSuggestion, private_id).payload_json)
    assert managed["_xiaoc_manual_scope"] == {"minimum_level": 3, "owner_user_id": owner.id}
    assert "_xiaoc_manual_scope" not in private


def test_legacy_handoff_requires_real_owner_approval_before_resuming(handoff_case):
    models, factory, owner, state, calls, output = handoff_case
    queued = handoff()  # Historical rows have no source-request context in their payload.
    assert queued["ok"] is True
    assert autonomy.dispatch_pending_suggestions()["skipped"] == 1
    with factory() as session:
        row = session.get(models.EmployeeSuggestion, queued["suggestion_id"])
        assert row.status == "pending" and row.approved_by_user_id is None
    state["level"] = 1
    approved = autonomy.approve_suggestion(
        queued["suggestion_id"], approved_by_user_id=owner.id, dispatch_now=True
    )
    assert approved["ok"] is False and approved["status"] == "blocked"
    assert calls == [] and not output.exists()
    state["level"] = 3
    assert autonomy.dispatch_pending_suggestions()["ok_count"] == 1
    assert calls == [{"owner": owner.id, "scope_active": True}]


@pytest.mark.parametrize("stored_scope", [None, {}, {"minimum_level": 1, "owner_user_id": 2}])
def test_corrupt_scope_cannot_be_treated_as_an_unrestricted_private_task(
    handoff_case, stored_scope
):
    models, factory, owner, _state, calls, output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        queued = handoff()
    with factory() as session:
        row = session.get(models.EmployeeSuggestion, queued["suggestion_id"])
        payload = json.loads(row.payload_json)
        payload["_xiaoc_manual_scope"] = stored_scope
        row.payload_json = json.dumps(payload)
        session.commit()
    assert autonomy.dispatch_pending_suggestions()["skipped"] == 1
    assert calls == [] and not output.exists()


def test_oversized_suggestion_cannot_truncate_its_trusted_scope(handoff_case):
    models, factory, owner, _state, _calls, _output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3), pytest.raises(ValueError):
        autonomy.create_employee_suggestion(
            source_employee_id="source",
            summary="too large",
            payload={"context": "x" * 100000},
            target_employee_ids=["target"],
            emit_event=False,
        )
    with factory() as session:
        assert session.query(models.EmployeeSuggestion).count() == 0


@pytest.mark.parametrize("configured_user", [0, 1])
def test_manual_orchestration_keeps_request_owner_over_background_defaults(
    handoff_case, monkeypatch, configured_user
):
    from modstore_server.employee_orchestrator import plan_and_dispatch

    _models, _factory, owner, _state, _calls, _output = handoff_case
    received = []

    def execute(**kwargs):
        received.append(kwargs["created_by_user_id"])
        return {"ok": True}

    monkeypatch.setattr(
        "modstore_server.admin_duty_graph_api.execute_duty_graph_programmatic", execute
    )
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        assert plan_and_dispatch("authorized task", {}, created_by_user_id=configured_user)["ok"]
    assert received == [owner.id]


def test_private_employee_handoff_records_real_source_user_without_management_scope(
    handoff_case,
):
    from modstore_server.employee_executor_merged_mod2 import _execute_employee_phase_02

    models, factory, owner, state, calls, output = handoff_case
    state["level"] = 1
    with factory() as session:
        session.get(models.User, owner.id).is_admin = False
        session.commit()
        state_for_employee = {
            "session": session,
            "user_id": owner.id,
            "employee_id": "source",
            "manifest": {},
            "config": {"actions": {"handlers": ["echo"]}},
            "payload": {"suppress_employee_im": True},
            "reasoning": {
                "reasoning": json.dumps({"handoff_to": "target"}),
                "input": {"suppress_employee_im": True},
            },
            "task": "private source task",
            "_project_root": "",
        }
        assert _execute_employee_phase_02(state_for_employee) == (False, None)
        suggestion_id = state_for_employee["result"]["handoff"]["suggestion_id"]
    with factory() as session:
        payload = json.loads(session.get(models.EmployeeSuggestion, suggestion_id).payload_json)
        assert payload["_xiaoc_manual_scope"] == {"minimum_level": 0, "owner_user_id": owner.id}
    assert autonomy.dispatch_pending_suggestions()["ok_count"] == 1
    assert output.exists() and calls == [{"owner": owner.id, "scope_active": False}]


@pytest.fixture
def suggestion_claim_case(handoff_case, monkeypatch):
    models, factory, owner, _state, _calls, _output = handoff_case
    with xiaoc_life_chat.manual_life_scope(owner, 3):
        sid = handoff()["suggestion_id"]
    monkeypatch.setattr(_claim_orchestrator, "dispatch_subtasks", _REAL_DISPATCH_SUBTASKS)
    return models, factory, owner, sid


def test_suggestion_claim_scheduler_and_approval_dispatch_original_only_once(
    suggestion_claim_case, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from modstore_server import employee_executor

    models, factory, owner, sid = suggestion_claim_case
    assert autonomy.approve_suggestion(sid, approved_by_user_id=owner.id, dispatch_now=False)["ok"]
    entered, release, lock = Event(), Event(), Lock()
    calls = []

    def execute(_employee, _task, payload, *, user_id, **_kwargs):
        with lock:
            calls.append((payload["source_suggestion_id"], user_id))
            first = len(calls) == 1
        if first:
            entered.set()
            assert release.wait(5), "test release did not arrive"
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scheduler = pool.submit(autonomy.dispatch_pending_suggestions)
        try:
            assert entered.wait(5)
            with factory() as session:
                while_running = session.get(models.EmployeeSuggestion, sid).status
            approval = pool.submit(
                autonomy.approve_suggestion,
                sid,
                approved_by_user_id=owner.id,
                dispatch_now=True,
            ).result(timeout=5)
        finally:
            release.set()
        assert scheduler.result(timeout=5)["ok_count"] == 1
    assert while_running == "dispatched"
    assert approval["ok"] is False and approval["status"] == "dispatched"
    assert calls == [(sid, owner.id)]
    assert autonomy.approve_suggestion(sid, approved_by_user_id=owner.id)["status"] == "done"
    assert calls == [(sid, owner.id)]


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_suggestion_claim_stale_review_cannot_reset_a_completed_dispatch(
    suggestion_claim_case, monkeypatch, action
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread

    from sqlalchemy import event

    from modstore_server import employee_executor

    models, factory, owner, sid = suggestion_claim_case
    approval_read, release = Event(), Event()
    calls = []

    def execute(_employee, _task, payload, *, user_id, **_kwargs):
        calls.append((payload["source_suggestion_id"], user_id))
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    with factory() as session:
        engine = session.get_bind()

    def pause_approval(_conn, _cursor, statement, _params, _context, _many):
        if (
            current_thread().name.startswith("stale-approver")
            and statement.startswith("UPDATE employee_suggestions")
            and not approval_read.is_set()
        ):
            approval_read.set()
            assert release.wait(5), "test release did not arrive"

    event.listen(engine, "before_cursor_execute", pause_approval)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-approver") as pool:
            if action == "approve":
                stale = pool.submit(
                    autonomy.approve_suggestion,
                    sid,
                    approved_by_user_id=owner.id,
                    dispatch_now=True,
                )
            else:
                stale = pool.submit(
                    autonomy.reject_suggestion,
                    sid,
                    rejected_by_user_id=owner.id,
                    rejected_reason="concurrent review",
                )
            try:
                assert approval_read.wait(5)
                first = autonomy.dispatch_suggestion(sid, force_approve_if_needed=True)
                assert first["dispatch_result"]["ok"] is True
            finally:
                release.set()
            result = stale.result(timeout=5)
            assert result["status"] == "done"
            if action == "reject":
                assert result["ok"] is False
    finally:
        event.remove(engine, "before_cursor_execute", pause_approval)
    with factory() as session:
        assert session.get(models.EmployeeSuggestion, sid).status == "done"
    assert calls == [(sid, owner.id)]


def test_suggestion_claim_unknown_receipt_is_parked_without_redispatch(
    suggestion_claim_case, monkeypatch
):
    from modstore_server import employee_executor

    models, factory, owner, sid = suggestion_claim_case
    calls = []

    def execute(_employee, _task, payload, *, user_id, **_kwargs):
        calls.append((payload["source_suggestion_id"], user_id))
        return {
            "ok": False,
            "status": "unknown",
            "error": "original receipt unavailable",
        }

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    assert (
        autonomy.dispatch_suggestion(sid, force_approve_if_needed=True)["dispatch_result"]["ok"]
        is False
    )
    assert autonomy.dispatch_suggestion(sid)["status"] == "dispatched"
    assert autonomy.approve_suggestion(sid, approved_by_user_id=owner.id)["status"] == "dispatched"
    assert autonomy.dispatch_pending_suggestions()["processed"] == 0
    with factory() as session:
        row = session.get(models.EmployeeSuggestion, sid)
        assert row.status == "dispatched"
        assert json.loads(row.created_task_ids_json) == ["target"]
    assert calls == [(sid, owner.id)]


def test_suggestion_claim_preserves_specialized_evolution_recovery(
    suggestion_claim_case, monkeypatch
):
    from datetime import UTC, datetime

    from modstore_server import employee_evolution_dispatch

    models, factory, owner, sid = suggestion_claim_case
    with factory() as session:
        row = session.get(models.EmployeeSuggestion, sid)
        row.kind = "employee_evolution"
        row.status = "dispatched"
        row.approved_by_user_id = owner.id
        row.approved_at = datetime.now(UTC)
        row.created_task_ids_json = '["employee-pack-curator"]'
        session.commit()
    calls = []

    def recover(original_id):
        calls.append(original_id)
        return {"ok": True, "specialized_receipt": original_id}

    monkeypatch.setattr(employee_evolution_dispatch, "execute_approved_evolution", recover)
    assert autonomy.approve_suggestion(sid, approved_by_user_id=owner.id) == {
        "ok": True,
        "specialized_receipt": sid,
    }
    assert calls == [sid]


@pytest.mark.parametrize("status", ["dispatched", "done"])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_suggestion_claim_batch_review_cannot_reopen_original_execution(
    suggestion_claim_case, monkeypatch, status, action
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from modstore_server import admin_employee_autonomy_api as api
    from modstore_server import employee_executor

    models, factory, owner, sid = suggestion_claim_case
    with factory() as session:
        session.get(models.EmployeeSuggestion, sid).status = status
        session.commit()
    calls = []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: owner
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/employee-autonomy/suggestions/batch-review",
            json={"ids": [sid], "action": action, "dispatch_now": True},
        )
    assert response.status_code == 200
    with factory() as session:
        assert session.get(models.EmployeeSuggestion, sid).status == status
    assert calls == []
    assert response.json()["success"] == int(status == "done" and action == "approve")
