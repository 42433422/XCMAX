from __future__ import annotations

import json
import multiprocessing
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client() -> TestClient:
    from app.fastapi_routes.domains.misc.misc_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_memory_client(monkeypatch, trusted_actor):
    actor = trusted_actor(
        user_id=7, role="admin", permissions=["memory_v2.read", "memory_v2.write"]
    )
    original = _client

    def client():
        result = original()
        result.headers.update(actor.headers)
        return result

    monkeypatch.setattr(__import__(__name__, fromlist=["_client"]), "_client", client)
    return actor


def _patch_agent_repo(repo: InMemoryAgentRunRepository):
    return patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    )


def _configure_runtime(monkeypatch, tmp_path) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    memory_dir = tmp_path / "memory"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_dir / "memory_store.json"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-receipts.sqlite"))
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    from app.application.agent_orchestrator.tool_permission import (
        clear_idempotent_replay_for_tests,
    )

    clear_idempotent_replay_for_tests()
    memory_mod.reset_user_memory_service()


def _concurrent_memory_candidate_write(user_id, key, value, barrier) -> None:
    from app.application.memory_v2_facade import get_user_memory_service

    barrier.wait(timeout=15)
    get_user_memory_service().propose_memory_candidate(
        user_id, "preference", key, value, source="user_explicit"
    )


def _assert_memory_run(
    repo: InMemoryAgentRunRepository,
    run_id: str,
    *,
    action: str,
    risk: str,
) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "7"
    assert run.status == "completed"
    assert run.intent == f"ERP Agent 请求执行 memory_v2.{action}"
    assert run.steps[0].risk == "high"
    assert run.tool_calls[0].tool_id == "memory_v2"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == "memory_v2.write"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed"} <= {
        event.event_type for event in run.events
    }


def test_memory_v2_proposal_readback_preserves_pending_relation_conflict(
    tmp_path, monkeypatch, authenticated_memory_client
) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    def relation(person):
        return {
            "statement": f"Northwind contact {person}",
            "subject": "Northwind",
            "predicate": "contact",
            "object": person,
            "relation_cardinality": "one",
            "entities": [
                {
                    "name": "Northwind",
                    "type": "organization",
                    "role": "subject",
                    "entity_id": "customer:17",
                },
                {"name": person, "type": "person", "role": "object"},
            ],
        }

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)
    try:
        with _patch_agent_repo(repo):
            client = ApprovedCapabilityClient(_client(), repo, authenticated_memory_client)
            payload = {
                "user_id": "7",
                "memory_type": "entity",
                "key": "contact",
                "source": "user_explicit",
                "evidence": [{"source": "reviewed_business_record"}],
            }
            first = client.post("/memory/v2/candidates", json={**payload, "value": relation("Alice")})
            assert first.status_code == 200, first.json()
            first_id = first.json()["candidate"]["memory_id"]
            confirmed = client.post(f"/memory/v2/{first_id}/confirm", json={"user_id": "7"})
            assert confirmed.status_code == 200, confirmed.json()
            active = confirmed.json()["memory"]
            second = client.post("/memory/v2/candidates", json={**payload, "value": relation("Bob")})
            assert second.status_code == 200, second.json()
            candidate = second.json()["candidate"]
            assert candidate["status"] == "pending"
            assert candidate["conflict_review"] == [
                {"memory_id": first_id, "revision": active["revision"]}
            ]
    finally:
        memory_mod.reset_user_memory_service()


@pytest.mark.parametrize("account_tier", ["normal", "personal"])
def test_memory_v2_lifecycle_routes_execute_through_agent(
    tmp_path,
    monkeypatch,
    authenticated_memory_client,
    account_tier,
) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.db.models.user import User

    with authenticated_memory_client.factory.begin() as db:
        db.get(User, authenticated_memory_client.user_id).account_tier = account_tier
    memory_owner = scoped_personal_memory_id(authenticated_memory_client.context)

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)

    try:
        with _patch_agent_repo(repo):
            client = ApprovedCapabilityClient(_client(), repo, authenticated_memory_client)
            created = client.post(
                "/memory/v2/candidates",
                json={
                    "user_id": "7",
                    "memory_type": "preference",
                    "key": "default_customer",
                    "value": "七彩乐园",
                    "confidence": 0.8,
                    "source": "settings_ui",
                    "evidence": [{"message": "总是给七彩乐园开单"}],
                },
                headers={"X-User-Id": "7"},
            )
            assert created.status_code == 200, created.json()
            created_body = created.json()
            assert created_body["success"] is True
            assert created_body["agent_run_id"] == created_body["run_id"]
            assert created_body["agent_status"] == "completed"
            candidate = created_body["candidate"]
            memory_id = candidate["memory_id"]
            _assert_memory_run(
                repo, created_body["run_id"], action="propose_candidate", risk="medium"
            )

            confirmed = client.post(
                f"/memory/v2/{memory_id}/confirm",
                json={"user_id": "7"},
                headers={"X-User-Id": "7"},
            )
            assert confirmed.status_code == 200
            confirmed_body = confirmed.json()
            assert confirmed_body["memory"]["status"] == "active"
            _assert_memory_run(repo, confirmed_body["run_id"], action="confirm", risk="high")

            svc = memory_mod.get_user_memory_service()
            assert svc.get_preference(memory_owner, "default_customer") == "七彩乐园"

            corrected = client.patch(
                f"/memory/v2/{memory_id}",
                json={
                    "user_id": "7",
                    "key": "favorite_customer",
                    "value": "彩虹乐园",
                    "reason": "用户纠正名称",
                },
                headers={"X-User-Id": "7"},
            )
            assert corrected.status_code == 200
            corrected_body = corrected.json()
            assert corrected_body["memory"]["key"] == "favorite_customer"
            _assert_memory_run(repo, corrected_body["run_id"], action="correct", risk="high")
            assert svc.get_preference(memory_owner, "default_customer") is None
            assert svc.get_preference(memory_owner, "favorite_customer") == "彩虹乐园"

            rejected = client.post(
                f"/memory/v2/{memory_id}/reject",
                json={"user_id": "7", "reason": "用户拒绝"},
                headers={"X-User-Id": "7"},
            )
            assert rejected.status_code == 200, rejected.json()
            rejected_body = rejected.json()
            assert rejected_body["memory"]["status"] == "rejected"
            assert rejected_body["memory"]["revision"] == corrected_body["memory"]["revision"] + 1
            assert (
                repo.get(rejected_body["run_id"]).tool_calls[0].metadata["verification"]["accepted"]
                is True
            )
            assert svc.get_preference(memory_owner, "favorite_customer") is None

            deleted = client.delete(
                f"/memory/v2/{memory_id}",
                params={"user_id": "7", "reason": "用户删除"},
                headers={"X-User-Id": "7"},
            )
            assert deleted.status_code == 200
            deleted_body = deleted.json()
            assert deleted_body["memory"]["status"] == "deleted"
            _assert_memory_run(repo, deleted_body["run_id"], action="delete", risk="high")
            assert svc.get_preference(memory_owner, "favorite_customer") is None
    finally:
        memory_mod.reset_user_memory_service()


def test_memory_v2_blocked_source_confirm_route_records_failed_agent_run(
    tmp_path,
    monkeypatch,
    authenticated_memory_client,
) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)

    try:
        with _patch_agent_repo(repo):
            client = ApprovedCapabilityClient(_client(), repo, authenticated_memory_client)
            created = client.post(
                "/memory/v2/candidates",
                json={
                    "user_id": "7",
                    "memory_type": "preference",
                    "key": "favorite_customer",
                    "value": "污染客户",
                    "confidence": 0.95,
                    "source": "llm_guess",
                },
                headers={"X-User-Id": "7"},
            )
            assert created.status_code == 200
            candidate = created.json()["candidate"]
            assert candidate["status"] == "rejected"
            assert candidate["source_policy"] == "blocked"

            confirm = client.post(
                f"/memory/v2/{candidate['memory_id']}/confirm",
                json={"user_id": "7"},
                headers={"X-User-Id": "7"},
            )
            assert confirm.status_code == 202
            body = confirm.json()
            assert body["success"] is False
            assert body["agent_run_id"] == body["run_id"]
            run = repo.get(body["run_id"])
            assert run is not None
            assert run.status == "blocked"
            assert run.intent == "ERP Agent 请求执行 memory_v2.confirm"
            assert run.tool_calls[0].tool_id == "memory_v2"
            assert run.tool_calls[0].action == "confirm"
            assert run.tool_calls[0].permission == "memory_v2.write"
            assert run.tool_calls[0].output == {
                "success": False,
                "message": "记忆已拒绝，不能确认",
                "outcome": "unknown",
                "reconciliation_required": True,
                "retryable": False,
            }
            verification = run.tool_calls[0].metadata["verification"]
            assert verification["accepted"] is False
            assert verification["code"] == "execution_receipt_not_successful"
            assert "tool.completed" not in {event.event_type for event in run.events}
            persisted = json.loads((tmp_path / "memory" / "memory_store.json").read_text())
            records = next(iter(persisted.values()))["memory_v2_records"]
            assert records == [candidate]
    finally:
        memory_mod.reset_user_memory_service()


@pytest.fixture
def memory_case(tmp_path, monkeypatch, local_tools, authenticated_memory_client):
    import app.domain.shared_services.user_memory_service as memory_mod

    # Fault-injection cases keep the real executor, claims and JSON transactions
    # in this process; the normal/personal lifecycle tests above cover workers.
    _configure_runtime(monkeypatch, tmp_path)
    repo = InMemoryAgentRunRepository()
    with _patch_agent_repo(repo):
        client = ApprovedCapabilityClient(_client(), repo, authenticated_memory_client)
        response = client.post(
            "/memory/v2/candidates",
            json={
                "user_id": "7",
                "memory_type": "preference",
                "key": "original",
                "value": "A",
                "source": "settings_ui",
            },
        )
        assert response.status_code == 200, response.json()
        result = response.json()
        try:
            yield SimpleNamespace(
                repo=repo,
                client=client,
                run=repo.get(result["run_id"]),
                memory_id=result["candidate"]["memory_id"],
                path=tmp_path / "memory" / "memory_store.json",
            )
        finally:
            memory_mod.reset_user_memory_service()


def _memory_readback(run, *, output=None, context_changes=None):
    from app.application.agent_orchestrator.verification_readback import (
        verify_independent_result,
    )

    call = run.tool_calls[0]
    step = run.steps[0]
    context = {
        **run.metadata["runtime_context"],
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "idempotency_key": call.metadata["idempotency_key"],
        **(context_changes or {}),
    }
    return verify_independent_result(
        run=run,
        step=step,
        call=call,
        output=deepcopy(call.output) if output is None else output,
        context=context,
    )


def test_memory_readback_survives_service_restart_without_initializing_or_writing(
    memory_case, monkeypatch
):
    import app.domain.shared_services.user_memory_service as memory_mod
    from app.infrastructure.user_memory.persistence import MemoryRepository

    memory_mod.reset_user_memory_service()

    def forbidden(*args, **kwargs):
        raise AssertionError("readback must not initialize a store, write, or rebuild projections")

    monkeypatch.setattr(memory_mod, "get_user_memory_service", forbidden)
    monkeypatch.setattr(MemoryRepository, "__init__", forbidden)
    monkeypatch.setattr(MemoryRepository, "get_memory", forbidden)
    monkeypatch.setattr(MemoryRepository, "save_memory", forbidden)
    monkeypatch.setattr("app.application.user_memory.projections.sync_memory_projection", forbidden)
    before = {
        item.name: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in memory_case.path.parent.iterdir()
        if item.is_file()
    }
    report = _memory_readback(memory_case.run)
    assert report["status"] == "verified", report
    assert memory_mod.UserMemoryStore._instance is None
    assert memory_mod.UserMemoryService._instance is None
    after = {
        item.name: (item.read_bytes(), item.stat().st_mtime_ns)
        for item in memory_case.path.parent.iterdir()
        if item.is_file()
    }
    assert after == before


@pytest.mark.parametrize("field", ["tenant_id", "user_id", "mod_id", "local_user_id"])
def test_memory_readback_rejects_foreign_scope_without_opening_store(
    memory_case, monkeypatch, field
):
    def forbidden(*args, **kwargs):
        raise AssertionError("scope must be checked before opening the memory store")

    monkeypatch.setattr("app.application.memory_v2_facade._memory_snapshot", forbidden)
    report = _memory_readback(memory_case.run, context_changes={field: "foreign-scope"})
    assert report["status"] in {"failed", "inconclusive"}
    assert report["code"] == (
        "result_read_permission_unavailable"
        if field == "local_user_id"
        else "result_scope_mismatch"
    )


def test_memory_readback_checks_current_owner_management_permission(
    memory_case, authenticated_memory_client, monkeypatch
):
    from app.db.models.permission import Role

    with authenticated_memory_client.factory.begin() as db:
        role = db.query(Role).filter_by(name="admin").one()
        role.permissions = [
            permission for permission in role.permissions if permission.code != "memory_v2.write"
        ]
    original = memory_case.path.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("permission must be checked before opening the memory store")

    monkeypatch.setattr("app.application.memory_v2_facade._memory_snapshot", forbidden)
    report = _memory_readback(memory_case.run)
    assert report["code"] == "result_read_permission_unavailable"
    assert memory_case.path.read_bytes() == original


@pytest.mark.parametrize("missing", ["receipt", "baseline"])
def test_memory_readback_requires_original_durable_proof(memory_case, missing):
    from app.application.agent_orchestrator.tool_permission import (
        clear_idempotent_replay_for_tests,
    )

    if missing == "receipt":
        clear_idempotent_replay_for_tests()
    else:
        memory_case.run.tool_calls[0].metadata["verification_contract"].pop("memory_baseline")
    original = memory_case.path.read_bytes()
    report = _memory_readback(memory_case.run)
    assert report["status"] == "inconclusive"
    assert report["code"] == f"result_memory_{missing}_unavailable"
    assert memory_case.path.read_bytes() == original


@pytest.mark.parametrize("field", ["value", "recorded_at_utc"])
def test_memory_readback_rejects_fabricated_output(memory_case, field):
    output = deepcopy(memory_case.run.tool_calls[0].output)
    output["candidate"][field] = "forged"
    report = _memory_readback(memory_case.run, output=output)
    assert report["status"] == "failed"
    assert report["code"] == "result_memory_receipt_mismatch"


@pytest.mark.parametrize(
    "tamper", ["value", "revision", "recorded_at_utc", "owner", "missing", "symlink", "store"]
)
def test_memory_readback_rejects_changed_original_store(memory_case, monkeypatch, tmp_path, tamper):
    import app.domain.shared_services.user_memory_service as memory_mod

    payload = json.loads(memory_case.path.read_text())
    owner = next(iter(payload))
    if tamper in {"value", "revision", "recorded_at_utc"}:
        payload[owner]["memory_v2_records"][0][tamper] = "changed"
        memory_case.path.write_text(json.dumps(payload))
    elif tamper == "owner":
        payload["other-owner"] = payload.pop(owner)
        payload["other-owner"]["user_id"] = "other-owner"
        memory_case.path.write_text(json.dumps(payload))
    elif tamper == "missing":
        memory_case.path.unlink()
    elif tamper == "symlink":
        replacement = tmp_path / "copied-memory.json"
        memory_case.path.rename(replacement)
        memory_case.path.symlink_to(replacement)
    else:
        replacement = tmp_path / "different-store.json"
        replacement.write_bytes(memory_case.path.read_bytes())
        memory_mod.reset_user_memory_service()
        monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(replacement))
    report = _memory_readback(memory_case.run)
    assert report["status"] in {"failed", "inconclusive"}, report
    assert (
        report["code"]
        == {
            "value": "result_memory_state_mismatch",
            "revision": "result_memory_state_mismatch",
            "recorded_at_utc": "result_memory_state_mismatch",
            "owner": "result_memory_owner_unavailable",
            "missing": "result_memory_owner_unavailable",
            "symlink": "result_evidence_mismatch",
            "store": "result_memory_source_mismatch",
        }[tamper]
    )


@pytest.mark.parametrize(
    "action,field,requested,actual",
    [
        ("correct", "value", "B", "C"),
        ("correct", "key", "requested-key", "wrong-key"),
        ("confirm", "value", "B", "C"),
        ("confirm", "key", "requested-key", "wrong-key"),
        ("confirm", "memory_type", "entity", "episodic"),
        ("confirm", "confidence", 0.8, 0.2),
        ("reject", "reason", "requested reason", "wrong reason"),
    ],
)
def test_memory_readback_rejects_wrong_effect_even_when_real_claim_and_output_match(
    memory_case, monkeypatch, local_tools, action, field, requested, actual
):
    import app.domain.shared_services.user_memory_service as memory_mod

    # Fault injection only changes the writer input; its real JSON transaction,
    # original durable tool claim and host readback all remain in use.
    service = memory_mod.get_user_memory_service()
    method = {
        "correct": "correct_memory",
        "confirm": "confirm_memory_candidate",
        "reject": "reject_memory_candidate",
    }[action]
    original = getattr(service, method)

    def write_wrong_effect(*args, **kwargs):
        if action == "confirm":
            kwargs["correction"] = {**(kwargs.get("correction") or {}), field: actual}
        else:
            kwargs[field] = actual
        return original(*args, **kwargs)

    writer = Mock(side_effect=write_wrong_effect)
    monkeypatch.setattr(service, method, writer)
    payload = {"user_id": "7", field: requested}
    if action in {"confirm", "reject"}:
        response = memory_case.client.post(
            f"/memory/v2/{memory_case.memory_id}/{action}",
            json=(
                {"user_id": "7", "correction": {field: requested}}
                if action == "confirm"
                else payload
            ),
        )
    else:
        response = memory_case.client.patch(f"/memory/v2/{memory_case.memory_id}", json=payload)
    body = response.json()
    assert response.status_code == 202, body
    assert body["success"] is False
    run = memory_case.repo.get(body["run_id"])
    assert run.status == "blocked"
    call = run.tool_calls[0]
    assert call.output["success"] is True
    assert call.output["memory"]["rejected_reason" if action == "reject" else field] == actual
    assert call.metadata["verification"]["code"] == "result_memory_effect_mismatch"
    assert call.metadata["verification"]["accepted"] is False
    assert writer.call_count == 1
    persisted = json.loads(memory_case.path.read_text())
    assert next(iter(persisted.values()))["memory_v2_records"][0] == call.output["memory"]


def test_memory_readback_rejects_wrong_source_governance(memory_case, monkeypatch, local_tools):
    import app.domain.shared_services.user_memory_service as memory_mod

    service = memory_mod.get_user_memory_service()
    original = service.propose_memory_candidate

    def ignore_blocked_source(*args, **kwargs):
        kwargs["source"] = "settings_ui"
        return original(*args, **kwargs)

    writer = Mock(side_effect=ignore_blocked_source)
    monkeypatch.setattr(service, "propose_memory_candidate", writer)
    response = memory_case.client.post(
        "/memory/v2/candidates",
        json={
            "user_id": "7",
            "memory_type": "preference",
            "key": "blocked-source",
            "value": "B",
            "source": "llm_guess",
        },
    )
    body = response.json()
    assert response.status_code == 202, body
    assert body["success"] is False
    run = memory_case.repo.get(body["run_id"])
    call = run.tool_calls[0]
    assert call.output["success"] is True
    assert call.output["candidate"]["status"] == "pending"
    assert call.metadata["verification"]["code"] == "result_memory_effect_mismatch"
    assert writer.call_count == 1


def test_memory_corrections_preserve_null_and_normalization_semantics(memory_case):
    confirmed = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/confirm",
        json={
            "user_id": "7",
            "correction": {
                "memory_type": "pref",
                "key": "  normalized  ",
                "value": None,
                "confidence": 8,
            },
        },
    )
    assert confirmed.status_code == 200, confirmed.json()
    current = confirmed.json()["memory"]
    assert (
        current["memory_type"],
        current["key"],
        current["value"],
        current["confidence"],
    ) == (
        "preference",
        "normalized",
        None,
        1.0,
    )
    changed = memory_case.client.patch(
        f"/memory/v2/{memory_case.memory_id}", json={"user_id": "7", "value": "new"}
    )
    assert changed.status_code == 200, changed.json()
    no_clear = memory_case.client.patch(
        f"/memory/v2/{memory_case.memory_id}", json={"user_id": "7", "value": None}
    )
    assert no_clear.status_code == 200, no_clear.json()
    assert no_clear.json()["memory"]["value"] == "new"
    assert no_clear.json()["memory"]["correction_count"] == 3


@pytest.mark.parametrize("field,value", [("key", "renamed"), ("memory_type", "entity")])
def test_memory_readback_rejects_stale_owned_preference_and_preserves_other_owners(
    memory_case, local_tools, field, value
):
    confirmed = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/confirm", json={"user_id": "7"}
    )
    assert confirmed.status_code == 200, confirmed.json()
    persisted = json.loads(memory_case.path.read_text())
    owner = next(iter(persisted))
    previous = persisted[owner]["preferences"]["original"]
    other = {"value": "other-value", "memory_id": "another-memory"}
    persisted[owner]["preferences"]["unrelated"] = other
    memory_case.path.write_text(json.dumps(persisted))
    changed = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/confirm",
        json={"user_id": "7", "correction": {field: value}},
    )
    assert changed.status_code == 200, changed.json()
    run = memory_case.repo.get(changed.json()["run_id"])
    persisted = json.loads(memory_case.path.read_text())
    assert "original" not in persisted[owner]["preferences"]
    assert persisted[owner]["preferences"]["unrelated"] == other
    persisted[owner]["preferences"]["original"] = previous
    memory_case.path.write_text(json.dumps(persisted))
    report = _memory_readback(run)
    assert report["code"] == "result_memory_effect_mismatch", report
    assert json.loads(memory_case.path.read_text())[owner]["preferences"]["unrelated"] == other


def test_memory_noop_confirmation_deduplication_and_delete_keep_original_record(
    memory_case, local_tools
):
    before = memory_case.run.tool_calls[0].output["candidate"]
    duplicate = memory_case.client.post(
        "/memory/v2/candidates",
        json={
            "user_id": "7",
            "memory_type": "preference",
            "key": "original",
            "value": "A",
            "source": "llm_guess",
        },
    )
    assert duplicate.status_code == 200, duplicate.json()
    assert duplicate.json()["created"] is False
    assert duplicate.json()["candidate"] == before
    confirmed = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/confirm", json={"user_id": "7"}
    )
    assert confirmed.status_code == 200, confirmed.json()
    repeated = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/confirm", json={"user_id": "7"}
    )
    assert repeated.status_code == 200, repeated.json()
    assert repeated.json()["memory"] == confirmed.json()["memory"]
    deleted = memory_case.client.delete(f"/memory/v2/{memory_case.memory_id}")
    assert deleted.status_code == 200, deleted.json()
    repeated = memory_case.client.delete(f"/memory/v2/{memory_case.memory_id}")
    assert repeated.status_code == 200, repeated.json()
    assert repeated.json()["memory"] == deleted.json()["memory"]


@pytest.mark.parametrize("initial_status", ["pending", "active"])
def test_memory_rejection_verifies_original_history_and_preserves_terminal_records(
    memory_case, local_tools, initial_status
):
    previous = memory_case.run.tool_calls[0].output["candidate"]
    if initial_status == "active":
        confirmed = memory_case.client.post(
            f"/memory/v2/{memory_case.memory_id}/confirm", json={"user_id": "7"}
        )
        assert confirmed.status_code == 200, confirmed.json()
        previous = confirmed.json()["memory"]
    response = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/reject",
        json={"user_id": "7", "reason": "user rejected this preference"},
    )
    assert response.status_code == 200, response.json()
    current = response.json()["memory"]
    run = memory_case.repo.get(response.json()["run_id"])
    assert run.status == "completed"
    assert run.tool_calls[0].metadata["verification"]["accepted"] is True
    assert current["status"] == "rejected" and current["eligible_for_planner"] is False
    assert current["revision"] == previous["revision"] + 1
    assert current["rejected_at"] == current["updated_at"]
    assert current["rejected_reason"] == "user rejected this preference"
    assert current["history"] == [
        *previous["history"],
        {
            "action": "rejected",
            "at": current["updated_at"],
            "previous": {key: value for key, value in previous.items() if key != "history"},
        },
    ]
    persisted = json.loads(memory_case.path.read_text())
    assert not next(iter(persisted.values()))["preferences"]
    repeated = memory_case.client.post(
        f"/memory/v2/{memory_case.memory_id}/reject",
        json={"user_id": "7", "reason": "a second reason must not rewrite the first"},
    )
    assert repeated.status_code == 200, repeated.json()
    assert repeated.json()["memory"] == current
    assert _memory_readback(memory_case.repo.get(repeated.json()["run_id"]))["status"] == "verified"
    deleted = memory_case.client.delete(f"/memory/v2/{memory_case.memory_id}")
    assert deleted.status_code == 200, deleted.json()
    original = memory_case.path.read_bytes()
    refused = memory_case.client.post(f"/memory/v2/{memory_case.memory_id}/reject")
    assert refused.status_code == 202, refused.json()
    assert refused.json()["success"] is False
    failed = memory_case.repo.get(refused.json()["run_id"])
    assert failed.status != "completed"
    assert failed.tool_calls[0].metadata["verification"]["accepted"] is False
    assert memory_case.path.read_bytes() == original


@pytest.mark.parametrize(
    "tamper",
    [
        "revision",
        "eligible",
        "rejected_at",
        "recorded_at_utc",
        "history_action",
        "history_previous",
        "history_prefix",
    ],
)
def test_memory_rejection_readback_requires_the_frozen_transition(
    memory_case, monkeypatch, local_tools, tamper
):
    import app.domain.shared_services.user_memory_service as memory_mod

    service = memory_mod.get_user_memory_service()
    original = service.reject_memory_candidate

    def corrupt_committed_transition(*args, **kwargs):
        output = original(*args, **kwargs)
        record = deepcopy(output["memory"])
        if tamper == "revision":
            record["revision"] -= 1
        elif tamper == "eligible":
            record["eligible_for_planner"] = True
        elif tamper == "rejected_at":
            record["rejected_at"] = "unrelated rejection time"
        elif tamper == "recorded_at_utc":
            record["recorded_at_utc"] = "2026-11-24T00:00:00"
        elif tamper == "history_action":
            record["history"][-1]["action"] = "deleted"
        elif tamper == "history_previous":
            record["history"][-1]["previous"]["value"] = "another prior value"
        else:
            record["history"].insert(0, {"action": "injected history"})
        persisted = json.loads(memory_case.path.read_text())
        next(iter(persisted.values()))["memory_v2_records"][0] = record
        memory_case.path.write_text(json.dumps(persisted))
        return {**output, "memory": record}

    writer = Mock(side_effect=corrupt_committed_transition)
    monkeypatch.setattr(service, "reject_memory_candidate", writer)
    response = memory_case.client.post(f"/memory/v2/{memory_case.memory_id}/reject")
    assert response.status_code == 202, response.json()
    run = memory_case.repo.get(response.json()["run_id"])
    call = run.tool_calls[0]
    assert run.status == "blocked" and response.json()["success"] is False
    assert call.output["success"] is True and writer.call_count == 1
    assert call.metadata["verification"]["code"] == "result_memory_effect_mismatch"
    assert call.metadata["verification"]["accepted"] is False
    persisted = json.loads(memory_case.path.read_text())
    assert next(iter(persisted.values()))["memory_v2_records"][0] == call.output["memory"]


def test_memory_store_keeps_concurrent_same_and_other_user_writes(tmp_path, monkeypatch) -> None:
    import app.domain.shared_services.user_memory_service as memory_mod

    memory_dir = tmp_path / "memory"
    memory_path = memory_dir / "memory_store.json"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", str(memory_dir))
    monkeypatch.setattr(memory_mod, "JSON_MEMORY_PATH", str(memory_path))
    memory_mod.reset_user_memory_service()

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    writes = [
        ("memory-a", "first", "A"),
        ("memory-a", "second", "B"),
        ("memory-b", "third", "C"),
    ]
    processes = [
        context.Process(target=_concurrent_memory_candidate_write, args=(*write, barrier))
        for write in writes
    ]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 25
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        alive = [process for process in processes if process.is_alive()]
        for process in alive:
            process.terminate()
        for process in alive:
            process.join(5)
        assert not alive
        assert [process.exitcode for process in processes] == [0, 0, 0]

        memory_mod.reset_user_memory_service()
        service = memory_mod.get_user_memory_service()
        assert service.get_memory_v2_summary("memory-a")["by_status"] == {"pending": 2}
        assert service.get_memory_v2_summary("memory-b")["by_status"] == {"pending": 1}
        persisted = json.loads(memory_path.read_text(encoding="utf-8"))
        assert set(persisted) == {"memory-a", "memory-b"}
        assert {row["key"] for row in persisted["memory-a"]["memory_v2_records"]} == {
            "first",
            "second",
        }
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        memory_mod.reset_user_memory_service()


@pytest.mark.parametrize("path", ["/memory/v2", "/memory/v2/summary"])
def test_memory_reads_require_session_and_reject_another_owner(path):
    client = _client()
    assert client.get(path, params={"user_id": "other-owner"}).status_code == 403
    assert client.get(path, headers={"X-User-Id": "other-owner"}).status_code == 403
    client.headers.clear()
    assert client.get(path, params={"user_id": "7"}).status_code == 401


def test_memory_write_rejects_forged_owner_before_execution():
    client = _client()
    body = {
        "user_id": "other-owner",
        "memory_type": "preference",
        "key": "test",
        "value": "forged",
    }
    assert client.post("/memory/v2/candidates", json=body).status_code == 403
    client.headers.clear()
    assert client.post("/memory/v2/candidates", json=body).status_code == 401


def test_numeric_username_cannot_select_another_canonical_owner(trusted_actor):
    from app.db.models.user import User

    actor = trusted_actor(user_id=7)
    with actor.factory.begin() as db:
        db.get(User, 7).username = "8"
    client = _client()
    client.headers.update(actor.headers)
    assert client.get("/memory/v2", params={"user_id": "8"}).status_code == 403
    assert client.get("/memory/v2", params={"user_id": "7"}).status_code == 200


@pytest.mark.parametrize("role", ["user", "admin"])
def test_memory_tools_bind_owner_before_role_bypass(trusted_actor, role):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    actor = trusted_actor(user_id=7, role=role)
    assert (
        actor_tool_denial("memory_v2", "propose_candidate", actor.context, {"user_id": "7"}) is None
    )
    denied = actor_tool_denial("memory_v2", "propose_candidate", actor.context, {"user_id": "8"})
    assert denied["reason"] == "memory_owner_mismatch"


@pytest.mark.parametrize(
    "tool,action",
    [
        ("sales", "query"),
        ("reports", "export"),
        ("reports", "sales_summary"),
        ("employee", "list"),
        ("employee", "execute"),
        ("excel_analysis", "read"),
        ("excel_analysis", "statistics"),
        ("excel_analysis", "structure"),
        ("excel_analysis", "query"),
    ],
)
def test_business_role_can_execute_registered_read_report_employee_chain(
    trusted_actor, tool, action
):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    actor = trusted_actor(user_id=8, role="user")
    assert actor_tool_denial(tool, action, actor.context, {}) is None
    viewer = trusted_actor(user_id=9, role="viewer")
    assert actor_tool_denial(tool, action, viewer.context, {})["reason"] == "permission_denied"


@pytest.mark.parametrize("account_tier", ["normal", "personal"])
def test_memory_v2_lifecycle_routes_require_shared_approval(
    tmp_path, monkeypatch, authenticated_memory_client, account_tier
):
    import app.domain.shared_services.user_memory_service as memory_mod
    from app.application.agent_task_context import scoped_personal_memory_id
    from app.db.models.user import User

    actor = authenticated_memory_client
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).account_tier = account_tier
    owner = scoped_personal_memory_id(actor.context)
    repo = InMemoryAgentRunRepository()
    _configure_runtime(monkeypatch, tmp_path)
    try:
        service = memory_mod.get_user_memory_service()
        candidate = service.propose_memory_candidate(
            owner, "preference", "customer", "七彩乐园", source="user_explicit"
        )["candidate"]
        memory_id = candidate["memory_id"]
        before = Path(memory_mod.JSON_MEMORY_PATH).read_bytes()
        cases = [
            (
                "POST",
                "/memory/v2/candidates",
                {
                    "user_id": "7",
                    "memory_type": "preference",
                    "key": "customer",
                    "value": "彩虹乐园",
                    "source": "user_explicit",
                },
                "propose_candidate",
            ),
            ("POST", f"/memory/v2/{memory_id}/confirm", {"user_id": "7"}, "confirm"),
            (
                "POST",
                f"/memory/v2/{memory_id}/reject",
                {"user_id": "7", "reason": "不是偏好"},
                "reject",
            ),
            (
                "PATCH",
                f"/memory/v2/{memory_id}",
                {"user_id": "7", "key": "favorite_customer", "value": "彩虹乐园"},
                "correct",
            ),
            (
                "DELETE",
                f"/memory/v2/{memory_id}?user_id=7&reason=用户删除",
                None,
                "delete",
            ),
        ]
        with _patch_agent_repo(repo), _client() as client:
            for method, path, body, action in cases:
                response = client.request(
                    method,
                    path,
                    json=body,
                    headers={"Idempotency-Key": f"memory-{action}"},
                )
                assert response.status_code == 202, response.text
                receipt = response.json()
                assert receipt["success"] is False and receipt["pending_approval"] is True
                run = repo.get(receipt["run_id"])
                assert run.user_id == "7" and run.status == "waiting_user"
                assert run.steps[0].tool_id == "memory_v2" and run.steps[0].action == action
                assert "user_id" not in run.steps[0].params
                assert not run.tool_calls
                assert "step.approved" not in {event.event_type for event in run.events}
                repeated = client.request(
                    method,
                    path,
                    json=body,
                    headers={"Idempotency-Key": f"memory-{action}"},
                )
                assert repeated.status_code == 202, repeated.text
                assert repeated.json()["run_id"] == receipt["run_id"]
                assert repeated.json()["approval_request_id"] == receipt["approval_request_id"]
        assert Path(memory_mod.JSON_MEMORY_PATH).read_bytes() == before
        assert service.get_preference(owner, "customer") is None
    finally:
        memory_mod.reset_user_memory_service()
