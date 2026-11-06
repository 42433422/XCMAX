"""E23/E24：进程崩溃后的幂等回读和释放，用真实进程而不是假结果。"""

from __future__ import annotations

import multiprocessing
import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.db.models.purchase_unit import PurchaseUnit


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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.application.customer_app_service as customers

    customers.get_customers_session = factory
    return engine


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
    with tempfile.TemporaryDirectory(prefix="e23-readback-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
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
    with tempfile.TemporaryDirectory(prefix="e24-live-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
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
    with tempfile.TemporaryDirectory(prefix="e24-race-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
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
    with tempfile.TemporaryDirectory(prefix="e24-again-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
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
    with tempfile.TemporaryDirectory(prefix="e23-mismatch-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
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
