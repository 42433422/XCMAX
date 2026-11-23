"""Paid delivery starts retain the original SQL claim and native session identity."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from modstore_server.models import get_session_factory
from modstore_server.models_cs import CustomerServiceAuditLog, CustomerServiceTicket
from tests.test_customer_service_api import _as_user, _make_ticket, _make_user


@pytest.fixture
def paid_ticket(client, monkeypatch):
    from modstore_server import customer_service_delivery_crm_api as crm
    from modstore_server import customer_service_delivery_payment_api as payment
    from modstore_server import workbench_api

    owner = _make_user("paid_delivery_recovery")
    order_no = f"PAID-{uuid.uuid4().hex}"
    factory = get_session_factory()
    evidence = {
        "kind": "module",
        "title": "One purchased customization",
        "requirements": "Deliver the original customer-approved quotation scope.",
        "acceptance_criteria": "Verify the original customer requirement.",
        "delivery_terms": {"pricing_mode": "post_delivery_addon"},
        "crm": {
            "assignment": {"status": "assigned", "owner_name": "Delivery operator"},
            "quote": {"status": "accepted", "amount": 100, "currency": "CNY"},
            "payment": {"status": "unpaid", "reference": order_no},
        },
        "runs": [],
    }
    with factory.begin() as db:
        ticket = _make_ticket(
            db,
            owner,
            ticket_no=f"CD-{uuid.uuid4().hex}",
            title=evidence["title"],
            intent="custom_delivery",
            status="processing",
            evidence_json=json.dumps(evidence),
        )
        ticket_id = ticket.id

    def paid_order(user_id, *, expected_out_trade_no):
        assert user_id == owner.id and expected_out_trade_no == order_no
        return {"order_kind": "custom_delivery", "total_amount": "100.00", "trade_no": "T-1"}

    state = SimpleNamespace(
        factory=factory,
        owner=owner,
        ticket_id=ticket_id,
        calls=[],
        snapshots={},
        payment=payment,
        crm=crm,
        order_no=order_no,
        workbench=workbench_api,
    )

    async def snapshot(session_id, user_id):
        assert user_id == owner.id
        return state.snapshots.get(session_id)

    monkeypatch.setattr(payment, "find_matching_paid_order", paid_order)
    monkeypatch.setattr(crm, "find_matching_paid_order", paid_order)
    monkeypatch.setattr(workbench_api, "get_workbench_session_snapshot", snapshot)
    return state


def stored(state):
    with state.factory() as db:
        ticket = db.get(CustomerServiceTicket, state.ticket_id)
        evidence = json.loads(ticket.evidence_json)
        audits = (
            db.query(CustomerServiceAuditLog)
            .filter_by(ticket_id=ticket.id, event_type="custom_delivery_payment_verified")
            .count()
        )
        return evidence, audits


def original_snapshot(state, session_id):
    return {
        "id": session_id,
        "user_id": state.owner.id,
        "status": "running",
        "steps": [],
        "source_scope": {
            "owner_user_id": state.owner.id,
            "ticket_id": state.ticket_id,
            "session_id": session_id,
        },
    }


async def readback(state):
    with state.factory() as db:
        ticket = db.get(CustomerServiceTicket, state.ticket_id)
        changed = await state.payment.reconcile_custom_delivery_payment(db, ticket)
        if changed:
            db.commit()
        return changed


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", [("payment", "payment"), ("payment", "crm"), ("crm", "crm")])
async def test_concurrent_payment_readbacks_dispatch_only_one_original_generation(
    paid_ticket, monkeypatch, entries
):
    from modstore_server.customer_service_delivery_models import CustomDeliveryCrmUpdateBody

    state = paid_ticket
    admin = _make_user("payment_recovery_admin", admin=True)
    loaded = asyncio.Barrier(2)
    entered, release = asyncio.Event(), asyncio.Event()

    async def start(user_id, payload, *, session_id="", **kwargs):
        assert user_id == state.owner.id
        assert kwargs["delivery_context"]["ticket_id"] == state.ticket_id
        state.calls.append(session_id)
        state.snapshots[session_id] = original_snapshot(state, session_id)
        entered.set()
        await release.wait()
        return {"session_id": session_id or uuid.uuid4().hex[:24], "status": "running"}

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", start)

    async def update(entry):
        with state.factory() as db:
            ticket = db.get(CustomerServiceTicket, state.ticket_id)
            await loaded.wait()
            if entry == "crm":
                try:
                    await state.crm.update_custom_delivery_crm(
                        state.ticket_id,
                        CustomDeliveryCrmUpdateBody(
                            section="payment", status="paid", amount=100, reference=state.order_no
                        ),
                        db=db,
                        user=admin,
                    )
                    return True
                except HTTPException as exc:
                    assert exc.status_code == 409
                    return False
            changed = await state.payment.reconcile_custom_delivery_payment(db, ticket)
            if changed:
                db.commit()
            return changed

    tasks = [asyncio.create_task(update(entry)) for entry in entries]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
    finally:
        release.set()
    changed = await asyncio.gather(*tasks)
    evidence, audits = stored(state)
    assert len(state.calls) == 1
    assert sum(changed) == 1
    if entries == ("payment", "payment"):
        assert audits == 1
    elif entries == ("crm", "crm"):
        assert audits == 0
    with state.factory() as db:
        assert (
            db.query(CustomerServiceAuditLog)
            .filter(
                CustomerServiceAuditLog.ticket_id == state.ticket_id,
                CustomerServiceAuditLog.event_type.in_(
                    ["custom_delivery_payment_verified", "custom_delivery_crm_payment_updated"]
                ),
            )
            .count()
            == 1
        )
    assert len(evidence["runs"]) == 1
    assert evidence["runs"][0]["session_id"] == evidence["delivery_generation"] == state.calls[0]
    assert evidence["crm"]["payment"]["status"] == "paid"


@pytest.mark.asyncio
@pytest.mark.parametrize("native_status", ["running", "error"])
async def test_lost_response_recovers_only_original_native_receipt(
    paid_ticket, monkeypatch, native_status
):
    state = paid_ticket

    async def accepted_then_lost(user_id, payload, *, session_id, **kwargs):
        evidence, audits = stored(state)
        assert evidence["delivery_generation"] == session_id
        assert evidence["crm"]["payment"]["status"] == "paid" and audits == 1
        state.calls.append(session_id)
        state.snapshots[session_id] = {
            **original_snapshot(state, session_id),
            "status": native_status,
        }
        raise TimeoutError("private upstream response lost")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", accepted_then_lost)
    assert await readback(state)
    before, _ = stored(state)
    assert before["runs"] == [] and "尚待确认" in before["start_error"]
    assert await readback(state)
    assert not await readback(state)
    evidence, audits = stored(state)
    assert state.calls == [evidence["delivery_generation"]]
    assert len(evidence["runs"]) == 1 and evidence["runs"][0]["attempt"] == 1
    assert evidence["runs"][0]["session_id"] == before["delivery_generation"]
    assert evidence["runs"][0]["status"] == native_status
    assert "start_error" not in evidence and audits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt", ["missing", "wrong_owner", "wrong_ticket", "wrong_id", "unbound"]
)
async def test_unknown_start_never_replays_or_accepts_an_unrelated_receipt(
    paid_ticket, monkeypatch, receipt
):
    state = paid_ticket

    async def lost(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        raise TimeoutError("unobserved native outcome")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", lost)
    assert await readback(state)
    before, audits = stored(state)
    sid = before["delivery_generation"]
    if receipt != "missing":
        snapshot = original_snapshot(state, sid)
        if receipt == "wrong_owner":
            snapshot["user_id"] = state.owner.id + 1
        elif receipt == "wrong_ticket":
            snapshot["source_scope"]["ticket_id"] = state.ticket_id + 1
        elif receipt == "wrong_id":
            snapshot["id"] = "another-generation"
        else:
            snapshot.pop("source_scope")
        state.snapshots[sid] = snapshot
    assert not await readback(state)
    assert not await readback(state)
    after, later_audits = stored(state)
    assert after == before and later_audits == audits == 1
    assert state.calls == [sid]


@pytest.mark.asyncio
async def test_crash_after_sql_claim_before_native_call_keeps_unknown_identity(
    paid_ticket, monkeypatch
):
    from modstore_server import customer_delivery_workbench_start as starter

    state = paid_ticket

    async def process_lost(**kwargs):
        evidence, audits = stored(state)
        assert evidence["delivery_generation"] == kwargs["session_id"] and audits == 1
        raise asyncio.CancelledError

    async def forbidden_start(*args, **kwargs):
        pytest.fail("An uncertain committed claim must not dispatch again")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", forbidden_start)
    with monkeypatch.context() as patch:
        patch.setattr(starter, "_start_custom_delivery_run", process_lost)
        with pytest.raises(asyncio.CancelledError):
            await readback(state)
    before, audits = stored(state)
    assert before["crm"]["payment"]["status"] == "paid" and before["runs"] == []
    assert not await readback(state)
    assert stored(state) == (before, audits)
    assert state.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["quote", "owner"])
async def test_stale_payment_readback_cannot_claim_changed_terms(
    paid_ticket, monkeypatch, changed_field
):
    state = paid_ticket

    async def forbidden_start(*args, **kwargs):
        pytest.fail("Stale terms must not reach the native starter")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", forbidden_start)
    replacement = _make_user("changed_delivery_owner")
    with state.factory() as stale:
        ticket = stale.get(CustomerServiceTicket, state.ticket_id)
        with state.factory.begin() as changed:
            current = changed.get(CustomerServiceTicket, state.ticket_id)
            if changed_field == "quote":
                evidence = json.loads(current.evidence_json)
                evidence["crm"]["quote"]["amount"] = 200
                current.evidence_json = json.dumps(evidence)
            else:
                current.user_id = replacement.id
        assert not await state.payment.reconcile_custom_delivery_payment(stale, ticket)
    evidence, audits = stored(state)
    assert "delivery_generation" not in evidence and evidence["runs"] == []
    assert evidence["crm"]["payment"]["status"] == "unpaid" and audits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["quote", "payment", "requirements", "refunded"])
async def test_changed_terms_during_dispatch_are_not_overwritten_or_reused(
    paid_ticket, monkeypatch, changed_field
):
    state = paid_ticket

    async def concurrent_edit(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        state.snapshots[session_id] = original_snapshot(state, session_id)
        with state.factory.begin() as db:
            ticket = db.get(CustomerServiceTicket, state.ticket_id)
            evidence = json.loads(ticket.evidence_json)
            if changed_field == "quote":
                evidence["crm"]["quote"]["amount"] = 200
            elif changed_field == "payment":
                evidence["crm"]["payment"]["reference"] = "another-order"
            elif changed_field == "refunded":
                evidence["crm"]["payment"]["status"] = "refunded"
            else:
                evidence["requirements"] = "A different scope requires another customer decision."
            ticket.evidence_json = json.dumps(evidence)
        return {"session_id": session_id, "status": "running"}

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", concurrent_edit)
    assert await readback(state)
    before, audits = stored(state)
    assert before["runs"] == [] and audits == 1
    assert not await readback(state)
    assert stored(state) == (before, audits)
    assert state.calls == [before["delivery_generation"]]


@pytest.mark.asyncio
async def test_failed_claim_transaction_does_not_dispatch_and_can_retry(paid_ticket, monkeypatch):
    from sqlalchemy import event

    state = paid_ticket

    async def start(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        return {"session_id": session_id, "status": "running"}

    def fail_before_commit(db):
        raise RuntimeError("transaction did not commit")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", start)
    with state.factory() as db:
        event.listen(db, "before_commit", fail_before_commit)
        ticket = db.get(CustomerServiceTicket, state.ticket_id)
        with pytest.raises(RuntimeError, match="transaction did not commit"):
            await state.payment.reconcile_custom_delivery_payment(db, ticket)
        db.rollback()
    evidence, audits = stored(state)
    assert "delivery_generation" not in evidence and audits == 0 and state.calls == []
    assert evidence["crm"]["payment"]["status"] == "unpaid"
    assert await readback(state)
    evidence, audits = stored(state)
    assert state.calls == [evidence["delivery_generation"]] and audits == 1


@pytest.mark.asyncio
async def test_insufficient_original_payment_never_claims_and_valid_payment_can_retry(
    paid_ticket, monkeypatch
):
    state = paid_ticket
    amount = 99

    def matched(user_id, *, expected_out_trade_no):
        assert user_id == state.owner.id and expected_out_trade_no == state.order_no
        return {"order_kind": "custom_delivery", "total_amount": str(amount)}

    async def start(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        return {"session_id": session_id, "status": "running"}

    monkeypatch.setattr(state.payment, "find_matching_paid_order", matched)
    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", start)
    assert not await readback(state)
    evidence, audits = stored(state)
    assert "delivery_generation" not in evidence and audits == 0 and not state.calls
    amount = 100
    assert await readback(state)
    evidence, audits = stored(state)
    assert state.calls == [evidence["delivery_generation"]] and audits == 1


def test_pending_original_claim_blocks_rework_without_any_mutation(
    client, paid_ticket, monkeypatch
):
    state = paid_ticket

    async def lost(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        raise TimeoutError("unknown production admission")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", lost)
    with _as_user(state.owner):
        listed = client.get("/api/customer-service/custom-deliveries")
        assert listed.status_code == 200
        current = next(row for row in listed.json()["items"] if row["id"] == state.ticket_id)
        assert current["custom_delivery"]["start_unconfirmed"] is True
        assert "尚待确认" in current["custom_delivery"]["stage_label"]
        before = stored(state)
        with state.factory() as db:
            audit_count = (
                db.query(CustomerServiceAuditLog).filter_by(ticket_id=state.ticket_id).count()
            )
        for source in (None, "versioned_main"):
            response = client.post(
                f"/api/customer-service/custom-deliveries/{state.ticket_id}/decision",
                json={"action": "rework", "note": "继续原生产请求", "source_mode": source},
            )
            assert response.status_code == 409
            assert "尚待回读" in response.json()["detail"]
        assert stored(state) == before
        with state.factory() as db:
            assert (
                db.query(CustomerServiceAuditLog).filter_by(ticket_id=state.ticket_id).count()
                == audit_count
            )
    assert state.calls == [before[0]["delivery_generation"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["quote", "owner"])
async def test_change_after_claim_commit_cannot_replace_claim_identity(
    paid_ticket, monkeypatch, changed_field
):
    from sqlalchemy import event

    state = paid_ticket
    replacement = _make_user("post_commit_delivery_owner")

    async def start(user_id, payload, *, session_id, **kwargs):
        state.calls.append((user_id, session_id))
        return {"session_id": session_id, "status": "running"}

    def changed_after_commit(_db):
        with state.factory.begin() as db:
            ticket = db.get(CustomerServiceTicket, state.ticket_id)
            evidence = json.loads(ticket.evidence_json)
            assert (
                evidence["delivery_generation"] and evidence["crm"]["payment"]["status"] == "paid"
            )
            if changed_field == "quote":
                evidence["crm"]["quote"]["amount"] = 200
                ticket.evidence_json = json.dumps(evidence)
            else:
                ticket.user_id = replacement.id

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", start)
    with state.factory() as db:
        event.listen(db, "after_commit", changed_after_commit, once=True)
        ticket = db.get(CustomerServiceTicket, state.ticket_id)
        assert await state.payment.reconcile_custom_delivery_payment(db, ticket)
        db.commit()
    evidence, audits = stored(state)
    assert state.calls == []
    assert evidence["runs"] == [] and evidence["delivery_generation"] and audits == 1
    if changed_field == "quote":
        assert evidence["crm"]["quote"]["amount"] == 200
    else:
        with state.factory() as db:
            assert db.get(CustomerServiceTicket, state.ticket_id).user_id == replacement.id


@pytest.mark.parametrize("section", ["quote", "payment"])
def test_pending_claim_freezes_commerce_identity_but_allows_other_crm_changes(
    client, paid_ticket, monkeypatch, section
):
    state = paid_ticket
    admin = _make_user("pending_delivery_admin", admin=True)

    async def lost(user_id, payload, *, session_id, **kwargs):
        state.calls.append(session_id)
        raise TimeoutError("unknown production admission")

    monkeypatch.setattr(state.workbench, "start_workbench_session_for_user", lost)
    with _as_user(state.owner):
        assert client.get("/api/customer-service/custom-deliveries").status_code == 200
    before, audits = stored(state)
    with state.factory() as db:
        before_audits = (
            db.query(CustomerServiceAuditLog).filter_by(ticket_id=state.ticket_id).count()
        )
    with _as_user(admin):
        change = (
            {"section": "quote", "status": "accepted", "amount": 200, "number": "Q-CHANGED"}
            if section == "quote"
            else {
                "section": "payment",
                "status": "refunded",
                "amount": 100,
                "reference": state.order_no,
            }
        )
        rejected = client.post(
            f"/api/customer-service/custom-deliveries/{state.ticket_id}/crm", json=change
        )
        assert rejected.status_code == 409
        assert stored(state) == (before, audits)
        with state.factory() as db:
            assert (
                db.query(CustomerServiceAuditLog).filter_by(ticket_id=state.ticket_id).count()
                == before_audits
            )
        assigned = client.post(
            f"/api/customer-service/custom-deliveries/{state.ticket_id}/crm",
            json={"section": "assignment", "owner_name": "Another delivery operator"},
        )
        assert assigned.status_code == 200
    sid = before["delivery_generation"]
    state.snapshots[sid] = original_snapshot(state, sid)
    with _as_user(state.owner):
        assert client.get("/api/customer-service/custom-deliveries").status_code == 200
    evidence, later_audits = stored(state)
    assert evidence["crm"]["assignment"]["owner_name"] == "Another delivery operator"
    assert evidence["crm"]["quote"] == before["crm"]["quote"]
    assert evidence["crm"]["payment"] == before["crm"]["payment"]
    assert evidence["runs"][0]["session_id"] == evidence["delivery_generation"] == sid
    assert state.calls == [sid] and later_audits == audits == 1
