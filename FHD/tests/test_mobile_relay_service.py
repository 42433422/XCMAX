from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.runtime_foundation import MobileRelayDesktop, MobileRelayTask


def _load_mobile_relay_service_module():
    path = Path(__file__).resolve().parents[1] / "app" / "services" / "mobile_relay_service.py"
    spec = importlib.util.spec_from_file_location("mobile_relay_service_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mobile_relay_account_auth_binding(monkeypatch, tmp_path):
    relay = _load_mobile_relay_service_module()

    engine = create_engine(f"sqlite:///{tmp_path / 'relay-account.db'}")
    MobileRelayDesktop.__table__.create(engine)
    MobileRelayTask.__table__.create(engine)
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


def test_completion_push_static_helper_covers_statuses_and_body_sources(monkeypatch):
    """直接覆盖完成推送的状态/正文分支,避免新增旁路拖低全量 branch ratchet。"""
    relay = _load_mobile_relay_service_module()
    import app.services.mobile_push as mobile_push

    calls: list[tuple] = []
    monkeypatch.setattr(
        mobile_push,
        "notify_user",
        lambda uid, title, body, data=None: (
            calls.append((uid, title, body, data)) or {"outbox": True}
        ),
    )

    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": "7",
            "kind": "cursor.invoke",
            "status": "failed",
            "task_id": "task-failed",
            "result_json": '{"error_message": "依赖安装失败"}',
        }
    )
    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": 8,
            "kind": "trae.invoke",
            "status": "blocked",
            "task_id": "task-blocked",
            "result": {"answer": "需要你确认分支"},
        }
    )
    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": 9,
            "kind": "codex.invoke",
            "status": "completed",
            "task_id": "task-fallback",
            "result_json": "not-json",
        }
    )

    assert [c[0] for c in calls] == [7, 8, 9]
    assert "任务失败" in calls[0][1]
    assert calls[0][2] == "依赖安装失败"
    assert "任务受阻" in calls[1][1]
    assert calls[1][2] == "需要你确认分支"
    assert calls[2][2] == "codex 已结束本次任务，打开对话查看详情。"
    assert calls[2][3]["task_status"] == "completed"


def test_completion_push_static_helper_skips_invalid_uid_and_unknown_status(monkeypatch):
    relay = _load_mobile_relay_service_module()
    import app.services.mobile_push as mobile_push

    calls: list[tuple] = []
    monkeypatch.setattr(
        mobile_push,
        "notify_user",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"outbox": True},
    )

    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": "not-int",
            "kind": "codex.invoke",
            "status": "completed",
            "result": {"summary": "不会发送"},
        }
    )
    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": 7,
            "kind": "codex.invoke",
            "status": "mystery",
            "result": {"summary": "不会发送"},
        }
    )

    assert calls == []


def test_completion_push_static_helper_swallows_push_exception(monkeypatch):
    relay = _load_mobile_relay_service_module()
    import app.services.mobile_push as mobile_push

    def boom(*_args, **_kwargs):
        raise RuntimeError("push down")

    monkeypatch.setattr(mobile_push, "notify_user", boom)

    relay.MobileRelayService._notify_task_creator(
        {
            "created_by_user_id": 7,
            "kind": "claude.invoke",
            "status": "completed",
            "task_id": "task-push-down",
            "result": {"output": "已完成"},
        }
    )
