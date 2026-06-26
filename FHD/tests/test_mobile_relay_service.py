from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _load_mobile_relay_service_module():
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "mobile_relay_service.py"
    spec = importlib.util.spec_from_file_location("mobile_relay_service_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mobile_relay_pair_dispatch_complete_round_trip(monkeypatch, tmp_path):
    relay = _load_mobile_relay_service_module()

    engine = create_engine(f"sqlite:///{tmp_path / 'relay.db'}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_db():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(relay, "get_db", test_db)
    service = relay.MobileRelayService()

    registered = service.register_desktop(
        label="测试电脑",
        device_id="mac-1",
        relay_base_url="https://relay.example.test/api",
        capabilities={"codex": True, "host": "192.168.1.8", "port": 17500},
    )
    paired = service.confirm_mobile(
        user_id=7,
        username="tester",
        relay_id=registered["relay_id"],
        code=registered["pairing_code"],
    )
    assert paired is not None
    assert paired["status"] == "paired"
    assert paired["local_base_url"] == "http://192.168.1.8:17500"
    assert paired["paired_at"]

    created = service.create_task(
        user_id=7,
        relay_id=registered["relay_id"],
        kind="codex.invoke",
        payload={"message": "运行真实 Codex"},
    )
    assert created is not None
    assert created["status"] == "queued"

    polled = service.poll_desktop(
        relay_id=registered["relay_id"],
        desktop_token=registered["desktop_token"],
    )
    assert polled is not None
    assert polled["tasks"][0]["status"] == "running"

    completed = service.complete_desktop_task(
        relay_id=registered["relay_id"],
        desktop_token=registered["desktop_token"],
        task_id=created["task_id"],
        status="completed",
        result={"ok": True, "codex": {"assistant_message": {"body": "完成"}}},
    )
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["result"]["codex"]["assistant_message"]["body"] == "完成"


def test_mobile_relay_account_auth_binding(monkeypatch, tmp_path):
    relay = _load_mobile_relay_service_module()

    engine = create_engine(f"sqlite:///{tmp_path / 'relay-account.db'}")
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_db():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(relay, "get_db", test_db)
    service = relay.MobileRelayService()

    registered = service.register_desktop(
        label="账号绑定电脑",
        device_id="mac-account-1",
        relay_base_url="https://relay.example.test/api",
        capabilities={"codex": True, "host": "192.168.1.9", "port": 42422},
    )
    bound = service.bind_mobile_by_account(
        user_id=9,
        username="account-user",
        relay_id=registered["relay_id"],
    )
    assert bound is not None
    assert bound["status"] == "paired"
    assert bound["relay_id"] == registered["relay_id"]
    assert bound["local_base_url"] == "http://192.168.1.9:42422"

    hijack = service.bind_mobile_by_account(
        user_id=10,
        username="other-user",
        relay_id=registered["relay_id"],
    )
    assert hijack is None
