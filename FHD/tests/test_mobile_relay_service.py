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


def test_schema_inspection_reuses_session_connection(monkeypatch):
    """Do not open a second PostgreSQL connection while DDL locks are held."""

    relay = _load_mobile_relay_service_module()
    connection = object()
    inspected: list[object] = []
    statements: list[object] = []

    class _Inspector:
        @staticmethod
        def get_columns(table):
            assert table == "mobile_relay_tasks"
            return [{"name": "task_id"}]

    class _Db:
        @staticmethod
        def connection():
            return connection

        @staticmethod
        def get_bind():
            raise AssertionError("engine-level inspection can deadlock PostgreSQL DDL")

        @staticmethod
        def execute(statement):
            statements.append(statement)

    def _inspect(bind):
        inspected.append(bind)
        return _Inspector()

    monkeypatch.setattr(relay, "sa_inspect", _inspect)
    relay.MobileRelayService._ensure_column(
        _Db(),
        "mobile_relay_tasks",
        "thread_id",
        "VARCHAR(64) NOT NULL DEFAULT ''",
    )

    assert inspected == [connection]
    assert len(statements) == 1


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


def test_four_super_employee_threads_runs_retry_and_archive(monkeypatch, tmp_path):
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-threads.db'}")
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
    monkeypatch.setattr(service, "_notify_task_creator", lambda _task: None)
    registered = service.register_desktop(label="四员工电脑", device_id="mac-four")
    assert service.bind_mobile_by_account(
        user_id=7, username="admin", relay_id=registered["relay_id"]
    )

    employee_kinds = {
        "codex-super-employee": "codex.invoke",
        "claude-super-employee": "claude.invoke",
        "cursor-super-employee": "cursor.invoke",
        "trae-super-employee": "trae.invoke",
    }
    threads = {}
    tasks = {}
    for employee_id, kind in employee_kinds.items():
        thread = service.create_thread(
            user_id=7,
            relay_id=registered["relay_id"],
            employee_id=employee_id,
            title=f"{employee_id} 对话",
        )
        assert thread and thread["employee_id"] == employee_id
        threads[employee_id] = thread
        task = service.create_task(
            user_id=7,
            relay_id=registered["relay_id"],
            kind=kind,
            thread_id=thread["thread_id"],
            payload={"message": f"{employee_id} 第一轮"},
        )
        assert task and task["attempt_no"] == 1
        assert task["thread_id"] == thread["thread_id"]
        assert task["payload"]["context"]["persistent_conversation"] is True
        tasks[employee_id] = task

    codex_followup = service.create_task(
        user_id=7,
        relay_id=registered["relay_id"],
        kind="codex.invoke",
        thread_id=threads["codex-super-employee"]["thread_id"],
        payload={"message": "Codex 第二轮，必须等待第一轮完成"},
    )
    assert codex_followup is not None
    assert len(service.list_threads(user_id=7)) == 4
    assert len(service.list_tasks(user_id=7, active_only=True)) == 5
    polled = service.poll_desktop(
        relay_id=registered["relay_id"],
        desktop_token=registered["desktop_token"],
        max_tasks=4,
        busy_tools=[],
    )
    assert polled is not None
    assert {item["kind"] for item in polled["tasks"]} == set(employee_kinds.values())
    assert codex_followup["task_id"] not in {item["task_id"] for item in polled["tasks"]}

    for employee_id, task in tasks.items():
        tool = task["kind"].split(".", 1)[0]
        completed = service.complete_desktop_task(
            relay_id=registered["relay_id"],
            desktop_token=registered["desktop_token"],
            task_id=task["task_id"],
            status="completed",
            result={
                "ok": True,
                "session": {
                    "session_id": f"{tool}-session",
                    "workspace_root": f"/tmp/{tool}-workspace",
                    "branch": f"super-employee/{tool}/thread",
                },
            },
        )
        assert completed and completed["status"] == "completed"
        thread = service.get_thread(user_id=7, thread_id=threads[employee_id]["thread_id"])
        assert thread and thread["cli_session_id"] == f"{tool}-session"
        assert thread["status"] == "completed"

    followup_poll = service.poll_desktop(
        relay_id=registered["relay_id"],
        desktop_token=registered["desktop_token"],
        max_tasks=4,
        busy_tools=[],
    )
    assert followup_poll is not None
    assert [item["task_id"] for item in followup_poll["tasks"]] == [codex_followup["task_id"]]
    assert service.complete_desktop_task(
        relay_id=registered["relay_id"],
        desktop_token=registered["desktop_token"],
        task_id=codex_followup["task_id"],
        status="completed",
        result={"ok": True},
    )

    codex_task = tasks["codex-super-employee"]
    retried = service.retry_task(user_id=7, task_id=codex_task["task_id"])
    assert retried and retried["attempt_no"] == 2
    assert retried["work_item_id"] == codex_task["work_item_id"]
    archived = service.archive_thread(
        user_id=7, thread_id=threads["trae-super-employee"]["thread_id"]
    )
    assert archived and archived["status"] == "archived"
    assert len(service.list_threads(user_id=7)) == 3


def test_cancel_running_task_is_delivered_and_late_completion_cannot_revive_it(
    monkeypatch, tmp_path
):
    relay = _load_mobile_relay_service_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'relay-cancel.db'}")
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
    monkeypatch.setattr(service, "_notify_task_creator", lambda _task: None)
    desktop = service.register_desktop(label="owner desktop", device_id="owner-mac")
    assert service.bind_mobile_by_account(user_id=7, username="owner", relay_id=desktop["relay_id"])
    thread = service.create_thread(
        user_id=7,
        relay_id=desktop["relay_id"],
        employee_id="codex-super-employee",
        title="cancel me",
    )
    assert thread is not None
    task = service.create_task(
        user_id=7,
        relay_id=desktop["relay_id"],
        kind="codex.invoke",
        thread_id=thread["thread_id"],
        payload={"message": "long task"},
    )
    assert task is not None
    claimed = service.poll_desktop(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        max_tasks=1,
    )
    assert claimed and claimed["tasks"][0]["status"] == "running"

    # A different enterprise/user cannot cancel the owner's task.
    assert service.cancel_task(user_id=8, task_id=task["task_id"]) is None
    cancelled = service.cancel_task(user_id=7, task_id=task["task_id"])
    assert cancelled and cancelled["status"] == "cancelled"
    # Cancellation is idempotent.
    cancelled_again = service.cancel_task(user_id=7, task_id=task["task_id"])
    assert cancelled_again and cancelled_again["status"] == "cancelled"

    signal = service.poll_desktop(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        max_tasks=0,
        inflight_task_ids=[task["task_id"], "another-enterprise-task"],
    )
    assert signal and signal["tasks"] == []
    assert signal["cancelled_task_ids"] == [task["task_id"]]

    late = service.complete_desktop_task(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        task_id=task["task_id"],
        status="completed",
        result={
            "ok": True,
            "answer": "late success must be ignored",
            "session": {"session_id": "late-session", "branch": "late-branch"},
        },
    )
    assert late and late["status"] == "cancelled"
    assert "late success" not in str(late.get("result") or {})
    thread_after = service.get_thread(user_id=7, thread_id=thread["thread_id"])
    assert thread_after and thread_after["status"] == "cancelled"
    assert thread_after["cli_session_id"] == ""
    assert thread_after["branch"] == ""


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
