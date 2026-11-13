"""云端只存密文：登记公钥后拒绝明文任务与明文结果，并限制密文留存周期。"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.desktop_relay import e2ee
from app.services import mobile_relay_service as relay


@pytest.fixture
def relay_e2ee(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-e2ee.db'}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def database():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(relay, "get_db", database)
    notifications = Mock()
    service = relay.MobileRelayService()
    monkeypatch.setattr(service, "_notify_task_creator", notifications)
    try:
        yield SimpleNamespace(service=service, database=database, engine=engine)
    finally:
        engine.dispose()


def _paired_with_public_key(context, user_id: int = 7501) -> dict:
    desktop_private = e2ee.generate_private_key_b64()
    desktop_public = e2ee.public_key_b64(desktop_private)
    desktop = context.service.register_desktop(
        label="加密执行端", device_id="e2ee-desktop", public_key=desktop_public
    )
    paired = context.service.bind_mobile_by_account(
        user_id=user_id, username="e2ee-user", pairing_code=desktop["pairing_code"]
    )
    assert paired is not None
    assert paired["public_key"] == desktop_public
    assert paired["key_fingerprint"]
    return {**desktop, "public_key": desktop_public, "private_key": desktop_private}


def test_plaintext_task_is_rejected_after_public_key_registered(relay_e2ee) -> None:
    desktop = _paired_with_public_key(relay_e2ee)

    with pytest.raises(ValueError):
        relay_e2ee.service.create_task(
            user_id=7501,
            relay_id=desktop["relay_id"],
            kind="codex.invoke",
            payload={"message": "客户A 欠款明细"},
        )


def test_encrypted_payload_is_stored_as_ciphertext_only(relay_e2ee) -> None:
    desktop = _paired_with_public_key(relay_e2ee)
    envelope, _, _ = e2ee.seal_payload(
        {"message": "客户A 欠款明细"}, desktop["public_key"]
    )

    task = relay_e2ee.service.create_task(
        user_id=7501,
        relay_id=desktop["relay_id"],
        kind="codex.invoke",
        payload=envelope,
    )

    with relay_e2ee.database() as db:
        raw = db.execute(
            text("SELECT payload_json FROM mobile_relay_tasks WHERE task_id = :task_id"),
            {"task_id": task["task_id"]},
        ).scalar_one()
    assert "客户A" not in raw
    assert e2ee.is_envelope(task["payload"])
    assert e2ee.open_envelope(task["payload"], desktop["private_key"])[0] == {
        "message": "客户A 欠款明细"
    }


def test_plaintext_result_is_rejected_and_encrypted_result_accepted(relay_e2ee) -> None:
    desktop = _paired_with_public_key(relay_e2ee)
    envelope, _, _ = e2ee.seal_payload({"message": "hello"}, desktop["public_key"])
    task = relay_e2ee.service.create_task(
        user_id=7501,
        relay_id=desktop["relay_id"],
        kind="codex.invoke",
        payload=envelope,
    )

    with pytest.raises(ValueError):
        relay_e2ee.service.complete_desktop_task(
            relay_id=desktop["relay_id"],
            desktop_token=desktop["desktop_token"],
            task_id=task["task_id"],
            status="completed",
            result={"summary": "客户A 的订单已处理"},
        )

    _, shared = e2ee.open_envelope(envelope, desktop["private_key"])
    sealed = e2ee.seal_result({"summary": "已处理"}, shared, ref=envelope["ref"])
    completed = relay_e2ee.service.complete_desktop_task(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        task_id=task["task_id"],
        status="completed",
        result=sealed,
    )

    assert completed is not None
    assert e2ee.is_envelope(completed["result"], require_epk=False)
    assert "已处理" not in str(completed["result"])


def test_e2ee_error_marker_is_allowed(relay_e2ee) -> None:
    desktop = _paired_with_public_key(relay_e2ee)
    envelope, _, _ = e2ee.seal_payload({"message": "hello"}, desktop["public_key"])
    task = relay_e2ee.service.create_task(
        user_id=7501, relay_id=desktop["relay_id"], kind="codex.invoke", payload=envelope
    )

    completed = relay_e2ee.service.complete_desktop_task(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        task_id=task["task_id"],
        status="failed",
        result={"e2ee_error": True},
    )

    assert completed is not None
    assert completed["status"] == "failed"


def test_completion_push_never_contains_result_body() -> None:
    captured: dict = {}
    from app.domain.shared_services import mobile_push

    original = mobile_push.notify_user
    mobile_push.notify_user = lambda user_id, **kwargs: captured.update(kwargs)
    try:
        relay.MobileRelayService._notify_task_creator(
            {
                "created_by_user_id": 1,
                "kind": "codex.invoke",
                "status": "completed",
                "task_id": "task-1",
                "result": {"summary": "客户A 欠款 10 万"},
            }
        )
    finally:
        mobile_push.notify_user = original

    assert captured
    assert "客户A" not in captured["body"]
    assert "欠款" not in captured["body"]
    assert "客户A" not in str(captured["data"])
