"""E22：同一客户的并发更新必须在数据库事务里比较版本。"""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.customer_app_service import CustomerApplicationService
from app.db.bootstrap.locations import create_desktop_business_tables
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
    engine = _engine(Path(db_path))
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def open_session():
        return factory()

    import app.application.customer_app_service as customers

    customers.get_customers_session = open_session
    return engine


def _version(engine, unit_id: int) -> int:
    with Session(engine) as db:
        value = db.execute(
            select(PurchaseUnit.version)
            .where(PurchaseUnit.id == unit_id)
            .execution_options(skip_tenant_filter=True)
        ).scalar_one()
    return int(value)


def _phone(engine, unit_id: int) -> str:
    with Session(engine) as db:
        value = db.execute(
            select(PurchaseUnit.contact_phone)
            .where(PurchaseUnit.id == unit_id)
            .execution_options(skip_tenant_filter=True)
        ).scalar_one()
    return str(value or "")


def _seed(engine, name: str, phone: str, tenant_id: int) -> int:
    with Session(engine) as db:
        db.add(
            PurchaseUnit(
                unit_name=name,
                contact_phone=phone,
                tenant_id=tenant_id,
                is_active=True,
                version=1,
            )
        )
        db.commit()
        return int(
            db.execute(
                select(PurchaseUnit.id)
                .where(PurchaseUnit.unit_name == name)
                .execution_options(skip_tenant_filter=True)
            ).scalar_one()
        )


def _update(unit_id: int, phone: str, key: str, expected) -> dict:
    params = {"id": unit_id, "contact_phone": phone, "idempotency_key": key}
    if expected is not None:
        params["expected_version"] = expected
    return AgentToolExecutor().execute(
        AgentStep(node_id=key, tool_id="customers", action="update", params=params),
        runtime_context={
            "tenant_id": "11",
            "user_id": "11",
            "task_id": key,
            "employee_id": "employee-a",
            "idempotency_key": key,
        },
    )


def _race_worker(db_path: str, idem_path: str, unit_id: int, phone: str, key: str, barrier, sender):
    try:
        engine = _bind(db_path, idem_path)
        permissions.drop_process_idempotency_memory()
        seen = _version(engine, unit_id)
        barrier.wait(timeout=30)
        result = _update(unit_id, phone, key, seen)
        sender.send(
            {
                "success": result.get("success"),
                "error_code": result.get("error_code"),
                "version": seen,
                "phone": phone,
            }
        )
    finally:
        sender.close()


def _prepare(tmp: Path) -> object:
    os.environ["XCAGI_TOOL_IDEMPOTENCY_PATH"] = str(tmp / "idempotency.sqlite")
    os.environ["AUDIT_LOG_PATH"] = str(tmp / "audit.jsonl")
    os.environ["SECRET_KEY"] = "e22-version-conflict-secret-32bytes"
    permissions.clear_idempotent_replay_for_tests()
    permissions.drop_process_idempotency_memory()
    engine = _engine(tmp / "business.sqlite")
    PurchaseUnit.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.application.customer_app_service as customers

    customers.get_customers_session = factory
    return engine


def test_two_processes_one_version_conflict():
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="e22-race-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
        unit_id = _seed(engine, "并发客户甲", "13800000000", 11)
        parent_version = _version(engine, unit_id)
        barrier = ctx.Barrier(2)
        receiver, sender = ctx.Pipe(duplex=False)
        worker = ctx.Process(
            target=_race_worker,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                unit_id,
                "13800002222",
                "e22-right",
                barrier,
                sender,
            ),
        )
        worker.start()
        sender.close()
        barrier.wait(timeout=30)
        left = _update(unit_id, "13800001111", "e22-left", parent_version)
        remote = receiver.recv()
        worker.join(timeout=30)
        final_phone = _phone(engine, unit_id)
        winner = ""
        if left.get("success") is True and remote.get("success") is not True:
            winner = "13800001111"
        elif remote.get("success") is True and left.get("success") is not True:
            winner = "13800002222"
        loser_code = (
            left.get("error_code") if left.get("success") is not True else remote.get("error_code")
        )
        assert worker.exitcode == 0
        assert remote.get("version") == parent_version
        assert winner
        assert loser_code == "version_conflict"
        assert final_phone == winner

        latest = _version(engine, unit_id)
        again = _update(unit_id, "13800003333", "e22-reread", latest)
        assert again.get("success") is True
        assert _phone(engine, unit_id) == "13800003333"
        assert _version(engine, unit_id) == latest + 1


def test_different_customers_both_succeed():
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="e22-pair-") as raw:
        tmp = Path(raw)
        engine = _prepare(tmp)
        left_id = _seed(engine, "并发客户乙", "13800000001", 11)
        right_id = _seed(engine, "并发客户丙", "13800000002", 11)
        barrier = ctx.Barrier(2)
        receiver, sender = ctx.Pipe(duplex=False)
        worker = ctx.Process(
            target=_race_worker,
            args=(
                str(tmp / "business.sqlite"),
                str(tmp / "idempotency.sqlite"),
                right_id,
                "13800004444",
                "e22-other",
                barrier,
                sender,
            ),
        )
        worker.start()
        sender.close()
        barrier.wait(timeout=30)
        left = _update(left_id, "13800005555", "e22-self", _version(engine, left_id))
        remote = receiver.recv()
        worker.join(timeout=30)
        assert worker.exitcode == 0
        assert left.get("success") is True
        assert remote.get("success") is True
        assert _phone(engine, left_id) == "13800005555"
        assert _phone(engine, right_id) == "13800004444"


def test_update_without_version_stays_compatible():
    with tempfile.TemporaryDirectory(prefix="e22-plain-") as raw:
        engine = _prepare(Path(raw))
        unit_id = _seed(engine, "旧接口客户", "13800000007", 11)
        first = _update(unit_id, "13800006666", "e22-plain-1", None)
        second = _update(unit_id, "13800007777", "e22-plain-2", None)
        assert first.get("success") is True
        assert second.get("success") is True
        assert first.get("error_code") != "version_conflict"
        assert _phone(engine, unit_id) == "13800007777"


def test_duplicate_name_does_not_write_phone():
    with tempfile.TemporaryDirectory(prefix="e22-name-") as raw:
        engine = _prepare(Path(raw))
        kept = _seed(engine, "保留客户", "13800000008", 11)
        other = _seed(engine, "另一客户", "13800000009", 11)
        result = CustomerApplicationService().update(
            kept,
            {
                "customer_name": "另一客户",
                "contact_phone": "13800008888",
                "expected_version": 1,
            },
        )
        assert result.get("success") is False
        assert _phone(engine, kept) == "13800000008"
        assert _version(engine, kept) == 1
        assert _phone(engine, other) == "13800000009"


def test_commit_failure_leaves_no_partial_write(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="e22-rollback-") as raw:
        engine = _prepare(Path(raw))
        unit_id = _seed(engine, "回滚客户", "13800000010", 11)
        import app.application.customer_app_service as customers

        factory = customers.get_customers_session

        def open_session():
            session = factory()

            def fail_commit(*_args, **_kwargs):
                raise sqlite3.DatabaseError("disk")

            session.commit = fail_commit
            return session

        monkeypatch.setattr(customers, "get_customers_session", open_session)
        result = CustomerApplicationService().update(
            unit_id, {"contact_phone": "13800009999", "expected_version": 1}
        )
        assert result.get("success") is False
        assert _phone(engine, unit_id) == "13800000010"
        assert _version(engine, unit_id) == 1


def test_cross_tenant_update_stays_blocked():
    with tempfile.TemporaryDirectory(prefix="e22-tenant-") as raw:
        engine = _prepare(Path(raw))
        foreign = _seed(engine, "租户乙客户", "13900000016", 22)
        result = _update(foreign, "13900000999", "e22-cross", _version(engine, foreign))
        assert result.get("success") is not True
        assert _phone(engine, foreign) == "13900000016"


def test_desktop_sqlite_adds_default_version_without_rewriting_phone(tmp_path: Path):
    db_path = tmp_path / "xcagi.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE purchase_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_name TEXT NOT NULL DEFAULT '',
                contact_phone TEXT,
                tenant_id INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO purchase_units (unit_name, contact_phone, tenant_id) VALUES (?, ?, ?)",
            ("历史客户", "13800001234", 11),
        )
        connection.commit()
    create_desktop_business_tables(db_path, sqlite3.connect)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT contact_phone, version FROM purchase_units WHERE unit_name = ?",
            ("历史客户",),
        ).fetchone()
    assert row == ("13800001234", 1)


def test_stale_version_is_not_success():
    with tempfile.TemporaryDirectory(prefix="e22-stale-") as raw:
        engine = _prepare(Path(raw))
        unit_id = _seed(engine, "过期版本客户", "13800000011", 11)
        won = _update(unit_id, "13800001111", "e22-won", 1)
        lost = _update(unit_id, "13800002222", "e22-lost", 1)
        assert won.get("success") is True
        assert lost.get("success") is False
        assert lost.get("error_code") == "version_conflict"
        assert _phone(engine, unit_id) == "13800001111"
        assert _version(engine, unit_id) == 2


def test_alembic_rollback_preserves_version_and_rejects_stale_write(tmp_path, monkeypatch):
    from alembic.config import Config

    from alembic import command

    engine = _prepare(tmp_path)
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = "2026_11_06_purchase_unit_version"
    try:
        unit_id = _seed(engine, "迁移回退客户", "13800007777", 11)
        with engine.begin() as db:
            db.execute(
                PurchaseUnit.__table__.update().where(PurchaseUnit.id == unit_id).values(version=7)
            )
        command.stamp(config, "2026_11_06_task_lifecycle")
        command.upgrade(config, revision)
        for attempt in range(2):
            command.downgrade(config, "2026_11_06_task_lifecycle")
            command.upgrade(config, revision)
            assert _version(engine, unit_id) == 7
            stale = _update(unit_id, "13800001111", f"e22-migration-stale-{attempt}", 1)
            assert stale.get("success") is False
            assert stale.get("error_code") == "version_conflict"
            assert _phone(engine, unit_id) == "13800007777"
        current = _update(unit_id, "13800008888", "e22-migration-current", 7)
        assert current.get("success") is True
        assert _version(engine, unit_id) == 8
        assert _phone(engine, unit_id) == "13800008888"
    finally:
        engine.dispose()
