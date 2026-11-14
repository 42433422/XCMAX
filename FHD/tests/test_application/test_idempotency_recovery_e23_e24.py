"""E23/E24：进程崩溃后的幂等回读和释放，用真实进程而不是假结果。"""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.task_lifecycle import TaskLifecycleRecord


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )


def _bind(db_path: str, idem_path: str):
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = idem_path
    os.environ["PYTEST_CURRENT_TEST"] = ""
    os.environ["SECRET_KEY"] = "e23-e24-recovery-secret-32bytes"
    engine = _engine(Path(db_path))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.application.customer_app_service as customers

    customers.get_customers_session = factory
    return engine


def _prepare(tmp: Path):
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = str(tmp / "idempotency.sqlite")
    os.environ["AUDIT_LOG_PATH"] = str(tmp / "audit.jsonl")
    os.environ["SECRET_KEY"] = "e23-e24-recovery-secret-32bytes"
    permissions.clear_idempotent_replay_for_tests()
    permissions.drop_process_idempotency_memory()
    engine = _engine(tmp / "business.sqlite")
    PurchaseUnit.__table__.create(engine)
    TaskLifecycleRecord.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.application.customer_app_service as customers

    customers.get_customers_session = factory
    return engine


@contextmanager
def _prepared_fixture(prefix: str):
    import app.application.customer_app_service as customers

    original_session = customers.get_customers_session
    keys = ("XCAGI_TOOL_IDEMPOTENCY_PATH", "AUDIT_LOG_PATH", "SECRET_KEY")
    original_env = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix=prefix) as raw:
        engine = None
        try:
            tmp = Path(raw)
            engine = _prepare(tmp)
            yield tmp, engine
        finally:
            customers.get_customers_session = original_session
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            permissions.drop_process_idempotency_memory()
            if engine is not None:
                engine.dispose()


def _rows(engine, name: str) -> list[dict]:
    with Session(engine) as db:
        found = list(
            db.execute(
                select(PurchaseUnit)
                .where(PurchaseUnit.unit_name == name)
                .execution_options(skip_tenant_filter=True)
            ).scalars()
        )
    return [
        {
            "id": int(row.id),
            "tenant_id": int(row.tenant_id),
            "contact_phone": row.contact_phone or "",
        }
        for row in found
    ]


def _execute(name: str, key: str, phone: str | None = None) -> dict:
    params: dict = {"unit_name": name, "idempotency_key": key}
    if phone is not None:
        params["contact_phone"] = phone
    return AgentToolExecutor().execute(
        AgentStep(node_id=key, tool_id="customers", action="create", params=params),
        runtime_context={
            "tenant_id": "11",
            "user_id": "11",
            "task_id": key,
            "employee_id": "employee-a",
            "idempotency_key": key,
        },
    )


def _die_after_commit(db_path: str, idem_path: str, name: str, key: str, phone: str) -> None:
    _bind(db_path, idem_path)
    from app.application.agent_orchestrator import tool_permission as worker_permissions

    worker_permissions.drop_process_idempotency_memory()

    def finish_and_die(_claim_key: str, _output: dict) -> None:
        os._exit(23)

    worker_permissions.finish_idempotent_replay = finish_and_die
    _execute(name, key, phone)


def _die_before_commit(db_path: str, idem_path: str, name: str, key: str) -> None:
    _bind(db_path, idem_path)
    from app.application.agent_orchestrator import tool_permission as worker_permissions

    worker_permissions.drop_process_idempotency_memory()

    def die(*_args, **_kwargs):
        os._exit(24)

    import app.application.customer_app_service as customers

    customers.CustomerApplicationService.create = die
    _execute(name, key)


def _hold_claim(db_path: str, idem_path: str, name: str, key: str, started, release) -> None:
    _bind(db_path, idem_path)
    permissions.drop_process_idempotency_memory()
    claim_key, replay = permissions.begin_idempotent_replay(
        {
            "tenant_id": "11",
            "user_id": "11",
            "task_id": key,
            "idempotency_key": key,
        },
        "customers",
        "create",
        {"unit_name": name, "idempotency_key": key},
    )
    started.set()
    release.wait(timeout=30)
    if replay is None and claim_key:
        os._exit(0)


def _recover_once(db_path: str, idem_path: str, name: str, key: str, barrier, sender) -> None:
    try:
        _bind(db_path, idem_path)
        permissions.drop_process_idempotency_memory()
        if os.environ.get("XCMAX_CONTRACT_FAULT") == "ignore-claim":

            def begin(*_args, **_kwargs):
                return (f"forced-{os.getpid()}", None)

            permissions.begin_idempotent_replay = begin
        barrier.wait(timeout=30)
        result = _execute(name, key)
        sender.send(
            {
                "success": result.get("success"),
                "error_code": result.get("error_code"),
                "id": (result.get("data") or {}).get("id")
                if isinstance(result.get("data"), dict)
                else None,
            }
        )
    finally:
        sender.close()


def test_e23_kill_after_commit_returns_the_same_row():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e23-readback-") as (tmp, engine):
        worker = ctx.Process(
            target=_die_after_commit,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "回读客户",
                "e23-key",
                "13800000023",
            ),
        )
        worker.start()
        worker.join(timeout=30)
        before = _rows(engine, "回读客户")
        permissions.drop_process_idempotency_memory()
        restored = _execute("回读客户", "e23-key", "13800000023")
        after = _rows(engine, "回读客户")
        assert worker.exitcode == 23
        assert len(before) == 1 and len(after) == 1
        assert after[0]["id"] == before[0]["id"]
        assert restored.get("success") is True
        assert restored.get("data", {}).get("id") == before[0]["id"]
        assert restored.get("data", {}).get("tenant_id") == 11
        assert restored.get("data", {}).get("contact_phone") == "13800000023"
        again = _execute("回读客户", "e23-key", "13800000023")
        assert again.get("data", {}).get("id") == before[0]["id"]
        assert len(_rows(engine, "回读客户")) == 1


def test_e24_live_owner_is_not_cleared():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e24-live-") as (tmp, engine):
        started, release = ctx.Event(), ctx.Event()
        holder = ctx.Process(
            target=_hold_claim,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "活着的认领",
                "e24-live",
                started,
                release,
            ),
        )
        holder.start()
        assert started.wait(timeout=30)
        blocked = _execute("活着的认领", "e24-live")
        assert holder.is_alive()
        assert blocked.get("success") is not True
        assert blocked.get("error_code") == "idempotency_in_progress"
        assert _rows(engine, "活着的认领") == []
        release.set()
        holder.join(timeout=30)


def test_e24_two_recoveries_leave_one_row():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e24-race-") as (tmp, engine):
        crashed = ctx.Process(
            target=_die_before_commit,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "崩溃前客户",
                "e24-race",
            ),
        )
        crashed.start()
        crashed.join(timeout=30)
        assert crashed.exitcode == 24
        assert _rows(engine, "崩溃前客户") == []
        barrier = ctx.Barrier(2)
        left_rx, left_tx = ctx.Pipe(duplex=False)
        right_rx, right_tx = ctx.Pipe(duplex=False)
        args = (
            str(tmp / "business.sqlite"),
            str(tmp / "idempotency.sqlite"),
            "崩溃前客户",
            "e24-race",
            barrier,
        )
        left = ctx.Process(target=_recover_once, args=(*args, left_tx))
        right = ctx.Process(target=_recover_once, args=(*args, right_tx))
        left.start()
        right.start()
        left_tx.close()
        right_tx.close()
        left_result = left_rx.recv()
        right_result = right_rx.recv()
        left.join(timeout=30)
        right.join(timeout=30)
        rows = _rows(engine, "崩溃前客户")
        successes = [item for item in (left_result, right_result) if item.get("success") is True]
        assert left.exitcode == 0 and right.exitcode == 0
        assert len(rows) == 1
        assert len(successes) >= 1
        assert all(item.get("id") in (None, rows[0]["id"]) for item in (left_result, right_result))
        assert all(
            item.get("success") is True or item.get("error_code") == "idempotency_in_progress"
            for item in (left_result, right_result)
        )


def test_e24_second_crash_can_still_recover():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e24-again-") as (tmp, engine):
        db_path = str(tmp / "business.sqlite")
        idem_path = str(tmp / "idempotency.sqlite")
        first = ctx.Process(
            target=_die_before_commit, args=(db_path, idem_path, "再次崩溃", "e24-again")
        )
        first.start()
        first.join(timeout=30)
        second = ctx.Process(
            target=_die_before_commit, args=(db_path, idem_path, "再次崩溃", "e24-again")
        )
        second.start()
        second.join(timeout=30)
        assert first.exitcode == 24 and second.exitcode == 24
        assert _rows(engine, "再次崩溃") == []
        permissions.drop_process_idempotency_memory()
        restored = _execute("再次崩溃", "e24-again")
        rows = _rows(engine, "再次崩溃")
        assert restored.get("success") is True
        assert len(rows) == 1
        assert restored.get("data", {}).get("id") == rows[0]["id"]
        assert len(_rows(engine, "再次崩溃")) == 1


def test_same_key_with_different_phone_does_not_reuse_the_row():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e23-mismatch-") as (tmp, engine):
        worker = ctx.Process(
            target=_die_after_commit,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "参数不同",
                "e23-mismatch",
                "13800000023",
            ),
        )
        worker.start()
        worker.join(timeout=30)
        permissions.drop_process_idempotency_memory()
        rejected = _execute("参数不同", "e23-mismatch", "13800000999")
        assert rejected.get("success") is not True
        assert rejected.get("error_code") == "idempotency_conflict"
        assert len(_rows(engine, "参数不同")) == 1
        assert _rows(engine, "参数不同")[0]["contact_phone"] == "13800000023"


def test_r07_replaying_the_old_success_for_a_different_phone_fails(monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path

    real = permissions.begin_idempotent_replay

    def replay_previous(*args, **kwargs):
        key, replay = real(*args, **kwargs)
        if isinstance(replay, dict) and replay.get("success") is not True:
            return key, {"success": True, "data": {"contact_phone": "13800000023"}}
        return key, replay

    monkeypatch.setattr(permissions, "begin_idempotent_replay", replay_previous)
    try:
        test_same_key_with_different_phone_does_not_reuse_the_row()
    except AssertionError as exc:
        assert "not True" in str(exc) or "idempotency_conflict" in str(exc)
    else:
        raise AssertionError("a different phone reused the previous success")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    restored = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_application/test_idempotency_recovery_e23_e24.py::test_same_key_with_different_phone_does_not_reuse_the_row",
            "-q",
            "-o",
            "addopts=",
            "--tb=line",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr


def test_r09_two_recoveries_without_the_claim_leave_two_rows():
    import subprocess
    import sys
    from pathlib import Path

    os.environ["XCMAX_CONTRACT_FAULT"] = "ignore-claim"
    try:
        test_e24_two_recoveries_leave_one_row()
    except AssertionError:
        # 未领取时的恢复会破坏「只留一行」不变量；不依赖内部断言的具体文案。
        pass
    else:
        raise AssertionError("two recoveries without a claim still left one row")
    finally:
        os.environ.pop("XCMAX_CONTRACT_FAULT", None)
    env = os.environ.copy()
    env.pop("XCMAX_CONTRACT_FAULT", None)
    env.pop("PYTHONPATH", None)
    restored = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_application/test_idempotency_recovery_e23_e24.py::test_e24_two_recoveries_leave_one_row",
            "-q",
            "-o",
            "addopts=",
            "--tb=line",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr


def test_crash_before_create_does_not_claim_an_existing_customer():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e24-existing-") as (tmp, engine):
        with Session(engine) as db:
            db.add(PurchaseUnit(unit_name="之前的客户", tenant_id=11, is_active=True))
            db.commit()
        before = _rows(engine, "之前的客户")
        worker = ctx.Process(
            target=_die_before_commit,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "之前的客户",
                "existing",
            ),
        )
        worker.start()
        worker.join(timeout=30)
        assert worker.exitcode == 24
        permissions.drop_process_idempotency_memory()
        restored = _execute("之前的客户", "existing")
        assert restored.get("success") is not True
        assert restored.get("reconciliation_required") is True
        assert _rows(engine, "之前的客户") == before


def test_legacy_claim_without_a_transaction_receipt_remains_unknown():
    ctx = multiprocessing.get_context("spawn")
    with _prepared_fixture("e24-legacy-") as (tmp, engine):
        worker = ctx.Process(
            target=_die_before_commit,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                "旧操作",
                "legacy",
            ),
        )
        worker.start()
        worker.join(timeout=30)
        assert worker.exitcode == 24
        with sqlite3.connect(tmp / "idempotency.sqlite") as db:
            db.execute("UPDATE tool_idempotency SET owner = ?", (f"{worker.pid}:legacy-token",))
        permissions.drop_process_idempotency_memory()
        restored = _execute("旧操作", "legacy")
        assert restored.get("success") is not True
        assert restored.get("reconciliation_required") is True
        assert _rows(engine, "旧操作") == []


def test_customer_and_operation_receipt_commit_atomically():
    with _prepared_fixture("e23-receipt-rollback-") as (tmp, engine):
        with sqlite3.connect(tmp / "business.sqlite") as db:
            db.execute(
                "CREATE TRIGGER reject_receipt BEFORE INSERT ON task_lifecycle_records "
                "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END"
            )
        with pytest.raises(SQLAlchemyError):
            _execute("回执失败不可提交客户", "receipt-failed")
        assert _rows(engine, "回执失败不可提交客户") == []


@pytest.mark.parametrize("fault", ["refresh", "commit_ack"])
def test_post_commit_disconnect_keeps_the_original_claim_and_receipt(monkeypatch, fault):
    import app.application.customer_app_service as customers

    with _prepared_fixture("e23-committed-disconnect-") as (tmp, engine):
        factory = customers.get_customers_session

        def disconnected_session():
            session = factory()
            commit = session.commit

            def fail_refresh(*_args, **_kwargs):
                raise OperationalError("post-commit refresh", {}, RuntimeError("connection lost"))

            def lose_commit_ack():
                commit()
                raise OperationalError(
                    "commit acknowledgement", {}, RuntimeError("connection lost")
                )

            if fault == "refresh":
                session.refresh = fail_refresh
            else:
                session.commit = lose_commit_ack
            return session

        with monkeypatch.context() as patch:
            patch.setattr(customers, "get_customers_session", disconnected_session)
            first = _execute("已提交客户", "same-key", "13800000001")
        if fault == "commit_ack":
            assert first.get("outcome") == "unknown"
            assert first.get("retryable") is False
            assert first.get("reconciliation_required") is True
        else:
            assert first.get("success") is True
        before = _rows(engine, "已提交客户")
        assert len(before) == 1
        with sqlite3.connect(tmp / "idempotency.sqlite") as db:
            assert db.execute("SELECT count(*) FROM tool_idempotency").fetchone()[0] == 1
        with sqlite3.connect(tmp / "business.sqlite") as db:
            receipt = db.execute(
                "SELECT body_json FROM task_lifecycle_records WHERE module='customer_create'"
            ).fetchone()[0]
        assert json.loads(receipt)["customer_id"] == before[0]["id"]
        changed = _execute("改变参数的客户", "same-key", "13800000002")
        assert changed.get("error_code") == "idempotency_conflict"
        assert _rows(engine, "已提交客户") == before
        assert _rows(engine, "改变参数的客户") == []
        with sqlite3.connect(tmp / "business.sqlite") as db:
            assert (
                db.execute(
                    "SELECT body_json FROM task_lifecycle_records WHERE module='customer_create'"
                ).fetchone()[0]
                == receipt
            )


@pytest.mark.parametrize("fail", [False, True])
def test_recovery_fixture_restores_database_and_environment_after_exit(fail):
    import app.application.customer_app_service as customers

    original_session = customers.get_customers_session
    keys = ("XCAGI_TOOL_IDEMPOTENCY_PATH", "AUDIT_LOG_PATH", "SECRET_KEY")
    original_env = {key: os.environ.get(key) for key in keys}
    with pytest.raises(RuntimeError, match="fixture failure") if fail else nullcontext():
        with _prepared_fixture("e23-owned-") as (tmp, engine):
            with customers.get_customers_session() as session:
                assert session.get_bind() is engine
                assert session.get_bind().url.database == str(tmp / "business.sqlite")
            if fail:
                raise RuntimeError("fixture failure")
    assert customers.get_customers_session is original_session
    assert {key: os.environ.get(key) for key in keys} == original_env
    assert not tmp.exists()
