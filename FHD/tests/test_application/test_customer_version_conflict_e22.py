"""E22：同一客户的并发更新必须在数据库事务里比较版本。"""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.customer_app_service import CustomerApplicationService
from app.db.bootstrap.locations import create_desktop_business_tables
from app.db.models.purchase_unit import PurchaseUnit
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


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
    engine = None
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
        if engine is not None:
            engine.dispose()
        sender.close()


@contextmanager
def _prepare(tmp: Path):
    import app.application.customer_app_service as customers

    previous_session = customers.get_customers_session
    environment = {
        "XCAGI_TOOL_IDEMPOTENCY_PATH": str(tmp / "idempotency.sqlite"),
        "AUDIT_LOG_PATH": str(tmp / "audit.jsonl"),
        "SECRET_KEY": "e22-version-conflict-secret-32bytes",
    }
    previous_env = {key: os.environ.get(key) for key in environment}
    engine = None
    try:
        os.environ.update(environment)
        permissions.clear_idempotent_replay_for_tests()
        permissions.drop_process_idempotency_memory()
        engine = _engine(tmp / "business.sqlite")
        PurchaseUnit.__table__.create(engine)
        customers.get_customers_session = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )
        yield engine
    finally:
        customers.get_customers_session = previous_session
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        permissions.drop_process_idempotency_memory()
        if engine is not None:
            engine.dispose()


def test_two_processes_one_version_conflict():
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="e22-race-") as raw, _prepare(Path(raw)) as engine:
        tmp = Path(raw)
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
    with tempfile.TemporaryDirectory(prefix="e22-pair-") as raw, _prepare(Path(raw)) as engine:
        tmp = Path(raw)
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
    with tempfile.TemporaryDirectory(prefix="e22-plain-") as raw, _prepare(Path(raw)) as engine:
        unit_id = _seed(engine, "旧接口客户", "13800000007", 11)
        first = _update(unit_id, "13800006666", "e22-plain-1", None)
        second = _update(unit_id, "13800007777", "e22-plain-2", None)
        assert first.get("success") is True
        assert second.get("success") is True
        assert first.get("error_code") != "version_conflict"
        assert _phone(engine, unit_id) == "13800007777"


def test_duplicate_name_does_not_write_phone():
    with tempfile.TemporaryDirectory(prefix="e22-name-") as raw, _prepare(Path(raw)) as engine:
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


@pytest.mark.parametrize("versioned", [False, True])
def test_customer_rename_preserves_product_and_shipment_links_within_tenant(versioned):
    from app.db.models.product import Product, UomUnit
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    with (
        tempfile.TemporaryDirectory(prefix="customer-rename-") as raw,
        _prepare(Path(raw)) as engine,
    ):
        UomUnit.__table__.create(engine, checkfirst=True)
        Product.__table__.create(engine, checkfirst=True)
        ShipmentRecord.__table__.create(engine, checkfirst=True)
        unit_id = _seed(engine, "合成客户", "", 11)
        with Session(engine) as db:
            db.add_all(
                [
                    Product(name="本租户产品", unit="合成客户", tenant_id=11),
                    Product(name="其他租户产品", unit="合成客户", tenant_id=22),
                    ShipmentRecord(
                        quantity_kg=1,
                        quantity_tins=1,
                        purchase_unit="合成客户",
                        product_name="本租户记录",
                        tenant_id=11,
                    ),
                    ShipmentRecord(
                        quantity_kg=1,
                        quantity_tins=1,
                        purchase_unit="合成客户",
                        product_name="其他租户记录",
                        tenant_id=22,
                    ),
                ]
            )
            db.commit()
        payload = {"customer_name": "合成客户新名"}
        if versioned:
            payload["expected_version"] = 1
        with tenant_scope(11):
            result = CustomerApplicationService().update(unit_id, payload)
        assert result["success"] is True
        with Session(engine) as db:
            products = db.execute(
                select(Product.tenant_id, Product.unit).execution_options(skip_tenant_filter=True)
            ).all()
            shipments = db.execute(
                select(ShipmentRecord.tenant_id, ShipmentRecord.purchase_unit).execution_options(
                    skip_tenant_filter=True
                )
            ).all()
        assert sorted(products) == [(11, "合成客户新名"), (22, "合成客户")], (
            "products",
            products,
            shipments,
        )
        assert sorted(shipments) == [(11, "合成客户新名"), (22, "合成客户")], (
            "shipments",
            products,
            shipments,
        )


def test_commit_failure_leaves_no_partial_write(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="e22-rollback-") as raw, _prepare(Path(raw)) as engine:
        unit_id = _seed(engine, "回滚客户", "13800000010", 11)
        import app.application.customer_app_service as customers

        factory = customers.get_customers_session

        def open_session():
            session = factory()

            def fail_commit(*_args, **_kwargs):
                raise sqlite3.DatabaseError("disk")

            session.commit = fail_commit
            return session

        with monkeypatch.context() as fault:
            fault.setattr(customers, "get_customers_session", open_session)
            result = CustomerApplicationService().update(
                unit_id, {"contact_phone": "13800009999", "expected_version": 1}
            )
        assert result.get("success") is False
        assert _phone(engine, unit_id) == "13800000010"
        assert _version(engine, unit_id) == 1


def test_cross_tenant_update_stays_blocked():
    with tempfile.TemporaryDirectory(prefix="e22-tenant-") as raw, _prepare(Path(raw)) as engine:
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
    with tempfile.TemporaryDirectory(prefix="e22-stale-") as raw, _prepare(Path(raw)) as engine:
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

    with _prepare(tmp_path) as engine, monkeypatch.context() as migration:
        migration.setenv("DATABASE_URL", str(engine.url))
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        revision = "2026_11_06_purchase_unit_version"
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


@pytest.mark.parametrize("fail_body", [False, True])
def test_prepare_restores_runtime_and_closes_database(tmp_path, fail_body):
    import app.application.customer_app_service as customers

    previous_session = customers.get_customers_session
    previous_env = {
        key: os.environ.get(key)
        for key in ("XCAGI_TOOL_IDEMPOTENCY_PATH", "AUDIT_LOG_PATH", "SECRET_KEY")
    }
    expected_error = (
        pytest.raises(RuntimeError, match="fixture failure") if fail_body else nullcontext()
    )
    with expected_error:
        with _prepare(tmp_path) as engine:
            assert customers.get_customers_session is not previous_session
            with engine.connect() as connection:
                pooled_connection = connection.connection.driver_connection
                assert pooled_connection.execute("SELECT 1").fetchone() == (1,)
            if fail_body:
                raise RuntimeError("fixture failure")
    assert customers.get_customers_session is previous_session
    assert {key: os.environ.get(key) for key in previous_env} == previous_env
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        pooled_connection.execute("SELECT 1")


def test_customer_cascade_only_deletes_own_children(trusted_actor):
    from app.db.models.product import Product, UomUnit
    from app.db.models.shipment import ShipmentRecord
    from app.infrastructure.tenant_scope import tenant_scope

    with (
        tempfile.TemporaryDirectory(prefix="customer-cascade-") as raw,
        _prepare(Path(raw)) as engine,
    ):
        actor = trusted_actor(
            tenant_id=11,
            role="cascade-review",
            permissions=["customer.edit", "product.edit", "shipment.edit"],
        )
        UomUnit.__table__.create(engine, checkfirst=True)
        Product.__table__.create(engine, checkfirst=True)
        ShipmentRecord.__table__.create(engine, checkfirst=True)
        unit_id = _seed(engine, "合成客户", "", 11)
        other_id = _seed(engine, "另一客户", "", 11)
        with Session(engine) as db:
            db.add_all(
                [
                    Product(name="目标产品", unit="合成客户", tenant_id=11),
                    Product(name="其他企业产品", unit="合成客户", tenant_id=22),
                    ShipmentRecord(
                        quantity_kg=1,
                        quantity_tins=1,
                        purchase_unit="合成客户",
                        product_name="目标发货",
                        tenant_id=11,
                        unit_id=unit_id,
                    ),
                    ShipmentRecord(
                        quantity_kg=1,
                        quantity_tins=1,
                        purchase_unit="合成客户",
                        product_name="其他客户发货",
                        tenant_id=11,
                        unit_id=other_id,
                    ),
                    ShipmentRecord(
                        quantity_kg=1,
                        quantity_tins=1,
                        purchase_unit="合成客户",
                        product_name="其他企业发货",
                        tenant_id=22,
                    ),
                ]
            )
            db.commit()
        with tenant_scope(11):
            assert not CustomerApplicationService().delete(unit_id)["success"]
            assert CustomerApplicationService().delete(
                unit_id, force=True, runtime_context=actor.context
            )["success"]
        with Session(engine) as db:
            products = (
                db.execute(select(Product.name).execution_options(skip_tenant_filter=True))
                .scalars()
                .all()
            )
            shipments = (
                db.execute(
                    select(ShipmentRecord.product_name).execution_options(skip_tenant_filter=True)
                )
                .scalars()
                .all()
            )
        assert products == ["其他企业产品"]
        assert set(shipments) == {"其他客户发货", "其他企业发货"}
