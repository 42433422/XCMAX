from __future__ import annotations

import importlib.util
from contextlib import contextmanager
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


def test_poll_requeues_stale_running_orphans(monkeypatch, tmp_path):
    """孤儿回收:claimed_at 超 TTL 的 running 在下次 poll 时被重入队并重新认领。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-orphan.db'}")
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
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="t", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )
    task = service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="codex.invoke", payload={"message": "x"}
    )

    # 第一次 poll → running
    p1 = service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    assert p1["tasks"][0]["status"] == "running"

    # 把 claimed_at 倒退到很久以前(模拟执行端中途死)
    with test_db() as db:
        db.execute(
            relay.text("UPDATE mobile_relay_tasks SET claimed_at = :old WHERE task_id = :t"),
            {"old": "2020-01-01T00:00:00+00:00", "t": task["task_id"]},
        )

    # 第二次 poll → 孤儿被重入队并重新认领,任务回到这个 relay
    p2 = service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    assert any(t["task_id"] == task["task_id"] for t in p2["tasks"]), (
        "stale running 应被重入队并重新认领"
    )
    assert p2["tasks"][0]["status"] == "running"


def test_poll_does_not_requeue_fresh_running(monkeypatch, tmp_path):
    """活着的 running(claimed_at 近期)绝不能被误重入队。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-fresh.db'}")
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
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="t", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )
    service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="codex.invoke", payload={"message": "x"}
    )
    service.poll_desktop(
        relay_id=reg["relay_id"], desktop_token=reg["desktop_token"]
    )  # → running, claimed now
    # 立刻再 poll:无新 queued,且刚才的 running 不该被重入队
    p2 = service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    assert p2["tasks"] == []


def test_complete_invoke_task_pushes_creator(monkeypatch, tmp_path):
    """CLI 执行类任务(*.invoke)到达终态 → 主动推送创建者手机(标题/渠道/负载正确)。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-push.db'}")
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
    import app.services.mobile_push as mobile_push

    calls: list[tuple] = []
    monkeypatch.setattr(
        mobile_push,
        "notify_user",
        lambda uid, title, body, data=None: (
            calls.append((uid, title, body, data)) or {"outbox": True}
        ),
    )
    service = relay.MobileRelayService()
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="t", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )
    created = service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="claude.invoke", payload={"message": "修 bug"}
    )
    service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    service.complete_desktop_task(
        relay_id=reg["relay_id"],
        desktop_token=reg["desktop_token"],
        task_id=created["task_id"],
        status="completed",
        result={"summary": "已修复并通过测试"},
    )
    assert len(calls) == 1, "完成 *.invoke 任务必须推送创建者"
    uid, title, body, data = calls[0]
    assert uid == 7
    assert "任务完成" in title
    assert "已修复并通过测试" in body
    assert data["channel"] == "xcagi_chat", "必须用 App 已注册的通知渠道"
    assert data["type"] == "relay_task_done"
    assert data["task_id"] == created["task_id"]
    assert data["tool"] == "claude"


def test_complete_git_op_and_cancelled_do_not_push(monkeypatch, tmp_path):
    """git 快捷操作(同步交互)与 cancelled(用户自己取消)不推送。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-nopush.db'}")
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
    import app.services.mobile_push as mobile_push

    calls: list[tuple] = []
    monkeypatch.setattr(
        mobile_push,
        "notify_user",
        lambda *a, **k: calls.append((a, k)) or {"outbox": True},
    )
    service = relay.MobileRelayService()
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="t", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )
    git_task = service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="git.merge", payload={"branch": "dev"}
    )
    cli_task = service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="codex.invoke", payload={"message": "x"}
    )
    service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    service.complete_desktop_task(
        relay_id=reg["relay_id"],
        desktop_token=reg["desktop_token"],
        task_id=git_task["task_id"],
        status="completed",
        result={"ok": True},
    )
    service.complete_desktop_task(
        relay_id=reg["relay_id"],
        desktop_token=reg["desktop_token"],
        task_id=cli_task["task_id"],
        status="cancelled",
        result={},
    )
    assert calls == [], "git 操作与 cancelled 不该推送"


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


def test_is_desktop_online_branches():
    """诚实在线判定：仅 paired + 近期心跳算在线；缺心跳/坏时间戳/未配对一律离线。"""
    from datetime import UTC, datetime, timedelta

    relay = _load_mobile_relay_service_module()
    now = datetime.now(UTC).replace(microsecond=0)
    fresh = now.isoformat()
    stale = (now - timedelta(hours=2)).isoformat()

    assert relay._is_desktop_online("paired", fresh) is True
    assert relay._is_desktop_online("paired", stale) is False
    assert relay._is_desktop_online("paired", "") is False
    assert relay._is_desktop_online("paired", None) is False
    assert relay._is_desktop_online("paired", "not-a-timestamp") is False
    assert relay._is_desktop_online("pending", fresh) is False
    # 无时区的 naive 时间戳按 UTC 处理
    assert relay._is_desktop_online("paired", now.replace(tzinfo=None).isoformat()) is True


def test_get_task_is_scoped_to_owning_user(monkeypatch, tmp_path):
    """跨用户不得读到他人中继任务：user B 查 user A 的 task → None（隔离负向测试）。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-scope.db'}")
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
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="owner", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )
    task = service.create_task(
        user_id=7, relay_id=reg["relay_id"], kind="codex.invoke", payload={"message": "x"}
    )
    assert task is not None

    # 归属用户可读
    assert service.get_task(user_id=7, task_id=task["task_id"]) is not None
    # 其他用户读不到（JOIN mobile_user_id 限定）
    assert service.get_task(user_id=8, task_id=task["task_id"]) is None
    # 其他用户也不能对该 relay 建任务（非其绑定）
    assert (
        service.create_task(
            user_id=8, relay_id=reg["relay_id"], kind="codex.invoke", payload={}
        )
        is None
    )


def test_desktop_online_reflects_poll_heartbeat(monkeypatch, tmp_path):
    """绑定后未 poll 视为离线；poll 心跳后在线；心跳过期回到离线（不得假装在线）。"""
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-online.db'}")
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
    reg = service.register_desktop(
        label="pc", device_id="mac-1", relay_base_url="https://r.test/api"
    )
    service.confirm_mobile(
        user_id=7, username="t", relay_id=reg["relay_id"], code=reg["pairing_code"]
    )

    # 尚无 poll 心跳 → 离线
    assert service.desktop_online(user_id=7, relay_id=reg["relay_id"]) is False
    desktops = service.list_desktops(user_id=7)
    assert desktops and desktops[0]["online"] is False

    # 桌面 poll 一次 → 在线
    service.poll_desktop(relay_id=reg["relay_id"], desktop_token=reg["desktop_token"])
    assert service.desktop_online(user_id=7, relay_id=reg["relay_id"]) is True
    assert service.list_desktops(user_id=7)[0]["online"] is True

    # 心跳过期 → 离线
    with test_db() as db:
        db.execute(
            relay.text("UPDATE mobile_relay_desktops SET last_seen_at = :old WHERE relay_id = :r"),
            {"old": "2020-01-01T00:00:00+00:00", "r": reg["relay_id"]},
        )
    assert service.desktop_online(user_id=7, relay_id=reg["relay_id"]) is False

    # 未绑定关系 → None（区别于离线）
    assert service.desktop_online(user_id=99, relay_id=reg["relay_id"]) is None
