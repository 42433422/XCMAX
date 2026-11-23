"""A delivered webhook must not be replayed when its acknowledgement is uncertain."""

from __future__ import annotations

import json

import httpx
import pytest
import tenacity
from sqlalchemy import event

from app.application.elt import service_execution
from app.application.elt.errors import EltError
from app.application.elt.service_support import load_json
from app.application.elt.targets.batch import WebhookAdapter
from app.db.models.elt import EltRun, EltRunRow
from tests.test_application.test_etl_preview_confirmation import execute
from tests.test_application.test_etl_preview_task_boundaries import (
    create_preview,
    ready_preview,
    snapshot,
)
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)


@pytest.fixture
def receiver(monkeypatch):
    client_type = httpx.Client
    monkeypatch.setattr("app.application.elt.targets._assert_safe_webhook_url", lambda url: None)
    monkeypatch.setattr("app.application.elt.targets.batch.read_webhook_secret", lambda ref: "")

    def install(handler):
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


def dispatch(rows=None, **context):
    rows = [{"name": "one"}] if rows is None else rows
    return WebhookAdapter().execute_batch(
        rows,
        {
            "run_id": "original-run",
            "target_config": {"endpoint_url": "https://receiver.example/elt"},
            "row_count": len(rows),
            **context,
        },
    )


def acknowledgement(request):
    payload = json.loads(request.content)
    return {
        "run_id": payload["run_id"],
        "chunk_index": payload["chunk_index"],
        "idempotency_key": payload["idempotency_key"],
        "executed_rows": len(payload["rows"]),
        "committed": True,
    }


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
@pytest.mark.parametrize("succeeds", [False, True])
def test_only_pre_dispatch_connection_failures_are_retried(
    receiver, monkeypatch, error_type, succeeds
):
    retrying = tenacity.Retrying
    waits = []
    monkeypatch.setattr(
        tenacity, "Retrying", lambda **kwargs: retrying(sleep=waits.append, **kwargs)
    )
    attempts = []

    def receive(request):
        attempts.append(request)
        if succeeds and len(attempts) == 3:
            return httpx.Response(200, json=acknowledgement(request))
        raise error_type("request body was not sent", request=request)

    receiver(receive)
    if succeeds:
        assert dispatch()["executed"] == 1
    else:
        with pytest.raises(EltError) as error:
            dispatch()
        assert error.value.code == "ELT_WEBHOOK_DELIVERY_FAILED"
    assert len(attempts) == 3
    assert waits == [1, 2]
    assert len({request.content for request in attempts}) == 1
    assert {request.headers["Idempotency-Key"] for request in attempts} == {"original-run:0"}


@pytest.mark.parametrize("failure", ["read_timeout", "write_timeout", "server_error"])
def test_uncertain_ack_never_replays_a_received_effect(receiver, failure):
    effects = []

    def receive(request):
        effects.append(json.loads(request.content))
        if failure == "server_error":
            return httpx.Response(503)
        error = httpx.ReadTimeout if failure == "read_timeout" else httpx.WriteTimeout
        raise error("acknowledgement unavailable", request=request)

    receiver(receive)
    with pytest.raises(EltError):
        dispatch()
    assert len(effects) == 1


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"run_id": "another-run"},
        {"chunk_index": True},
        {"idempotency_key": "another-run:0"},
        {"executed_rows": 0},
        {"executed_rows": True},
        {"committed": False},
        {"success": False},
    ],
)
def test_unbound_or_missing_receipt_is_not_completed(receiver, changed):
    calls = []

    def receive(request):
        calls.append(request)
        body = {**acknowledgement(request), **changed} if changed else {}
        return httpx.Response(200, json=body)

    receiver(receive)
    with pytest.raises(EltError) as error:
        dispatch()
    assert error.value.code == "ELT_WEBHOOK_RECEIPT_UNVERIFIED"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [202, 204])
def test_transport_acceptance_is_not_business_commit(receiver, status):
    receiver(lambda request: httpx.Response(status, json=acknowledgement(request)))
    with pytest.raises(EltError) as error:
        dispatch()
    assert error.value.code == "ELT_WEBHOOK_RECEIPT_UNVERIFIED"


def test_invalid_json_is_unknown_without_replay(receiver):
    calls = []

    def receive(request):
        calls.append(request)
        return httpx.Response(200, content=b"accepted")

    receiver(receive)
    with pytest.raises(EltError) as error:
        dispatch()
    assert error.value.code == "ELT_WEBHOOK_RECEIPT_UNVERIFIED"
    assert len(calls) == 1


def test_bound_chunk_receipts_preserve_original_request_identity(receiver):
    calls = []

    def receive(request):
        calls.append(request)
        return httpx.Response(200, json={**acknowledgement(request), "untrusted": "discard"})

    receiver(receive)
    result = dispatch([{"n": n} for n in range(501)])
    assert result["executed"] == 501
    assert len(calls) == 2
    receipts = result["receipt"]["chunks"]
    assert [item["receipt"]["executed_rows"] for item in receipts] == [500, 1]
    assert [item["receipt"]["idempotency_key"] for item in receipts] == [
        "original-run:0",
        "original-run:1",
    ]
    assert all("untrusted" not in item["receipt"] for item in receipts)
    assert result["receipt"]["business_verified"] is False


@pytest.mark.parametrize("failure", ["missing_receipt", "lost_ack"])
def test_worker_preserves_unknown_and_blocks_repeat_submission(
    preview_store, receiver, monkeypatch, failure
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="webhook")
    with store.factory() as db:
        config = store.service.create_target_config(
            db,
            owner_user_id=7,
            name="test receiver",
            endpoint_url="https://receiver.example/elt",
            headers={},
            secret=None,
        )
        db.commit()
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"target_config_id": config["id"]}
        )
    store.executor.futures[-1].result(timeout=10)
    revision = snapshot(store, run_id)["preview_revision"]
    deliveries = []

    def receive(request):
        deliveries.append(json.loads(request.content))
        if failure == "lost_ack":
            raise httpx.ReadTimeout("receiver committed before losing ACK", request=request)
        return httpx.Response(200, json={})

    receiver(receive)
    execute(store, run_id, revision)
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert current["status"] == "outcome_unknown"
    assert current["error_code"] == "ELT_OUTCOME_UNKNOWN"
    assert all(row["execution_status"] != "success" for row in current["persisted_rows"])
    with pytest.raises(EltError):
        execute(store, run_id, revision)
    with store.factory() as db, pytest.raises(EltError) as error:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    assert error.value.code == "ELT_RETRY_NOT_ALLOWED"
    assert len(deliveries) == 1


@pytest.mark.parametrize("failure", ["second_ack_lost", "first_receipt_commit_failed"])
def test_worker_saves_each_webhook_ack_before_sending_the_next_chunk(
    preview_store, receiver, monkeypatch, failure
):
    store = preview_store
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    csv = "客户名称,电话\n" + "".join(f"分片客户{i},13{i:09d}\n" for i in range(501))
    run_id = create_preview(store, target="webhook", csv=csv.encode())
    store.executor.futures[-1].result(timeout=10)
    with store.factory() as db:
        config = store.service.create_target_config(
            db,
            owner_user_id=7,
            name="test chunk receiver",
            endpoint_url="https://receiver.example/elt",
            headers={},
            secret=None,
        )
        db.commit()
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"target_config_id": config["id"]}
        )
    store.executor.futures[-1].result(timeout=10)
    revision = snapshot(store, run_id)["preview_revision"]
    failed_commits = []

    if failure == "first_receipt_commit_failed":

        def factory():
            db = store.factory()

            def before_commit(session):
                if failed_commits:
                    return
                for current in session.identity_map.values():
                    if isinstance(current, EltRun) and current.id == run_id:
                        receipt = load_json(current.receipt_json, {})
                        if receipt.get("batch_result"):
                            failed_commits.append(receipt)
                            raise OSError("synthetic first chunk receipt commit failure")

            event.listen(db, "before_commit", before_commit)
            return db

        monkeypatch.setattr(service_execution, "new_session", factory)

    deliveries = []
    before_delivery = []
    original_owners = []

    def receive(request):
        payload = json.loads(request.content)
        deliveries.append(payload)
        with store.factory() as check:
            current = check.get(EltRun, run_id)
            before_delivery.append(load_json(current.receipt_json, {}))
            original_owners.append((current.operation_kind, current.operation_token))
        if payload["chunk_index"] == 1 and failure == "second_ack_lost":
            raise httpx.ReadTimeout("second receiver ACK was lost after commit", request=request)
        return httpx.Response(200, json=acknowledgement(request))

    receiver(receive)
    execute(store, run_id, revision)
    store.executor.futures[-1].result(timeout=10)
    assert [len(payload["rows"]) for payload in deliveries] == (
        [500, 1] if failure == "second_ack_lost" else [500]
    )
    assert len(failed_commits) == (failure == "first_receipt_commit_failed")
    with store.factory() as check:
        current = check.get(EltRun, run_id)
        assert current.status == "outcome_unknown"
        assert current.error_code == "ELT_OUTCOME_UNKNOWN"
        assert (current.operation_kind, current.operation_token) == original_owners[0]
        assert current.executed_rows == 0
        result = load_json(current.receipt_json, {})["batch_result"]
        assert result["executed"] == 500
        receipt = result["receipt"]
        assert receipt["business_verified"] is False
        assert receipt["executed_rows"] == 500
        assert receipt["chunks"] == [
            {
                "chunk_index": 0,
                "status_code": 200,
                "receipt": {
                    "run_id": run_id,
                    "chunk_index": 0,
                    "idempotency_key": f"{run_id}:0",
                    "executed_rows": 500,
                    "committed": True,
                },
            }
        ]
        assert not any(
            row.execution_status == "success"
            for row in check.query(EltRunRow).filter_by(run_id=run_id)
        )
        if failure == "second_ack_lost":
            assert before_delivery[1] == {"batch_result": result}
    with pytest.raises(EltError):
        execute(store, run_id, revision)
    with store.factory() as db, pytest.raises(EltError) as error:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    assert error.value.code == "ELT_RETRY_NOT_ALLOWED"
    assert len(deliveries) == (2 if failure == "second_ack_lost" else 1)
