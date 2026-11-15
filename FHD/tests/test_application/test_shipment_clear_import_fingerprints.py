"""清空订单必须同步清掉导入指纹，否则同一批文件会永久判定为重复而不再入库。"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.db_base import Base
from app.db.models import ShipmentRecord
from app.db.models.shipment_elt_fingerprint import ShipmentEltImportFingerprint
from app.infrastructure.persistence.shipment_record_command_impl import (
    SQLAlchemyShipmentRecordCommand,
)
from app.infrastructure.tenant_scope import tenant_scope


def _setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'shipments.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=engine))
    return sessionmaker(bind=engine)


def _seed(session_factory, *, tenant_id: int, unit_name: str = "刘英") -> None:
    with session_factory() as db:
        record = ShipmentRecord(
            tenant_id=tenant_id,
            purchase_unit=unit_name,
            product_name="购丁酯",
            quantity_kg=1.0,
            quantity_tins=1,
            status="pending",
        )
        db.add(record)
        db.flush()
        db.add(
            ShipmentEltImportFingerprint(
                tenant_key=f"tenant:{tenant_id}",
                fingerprint=f"fp-{tenant_id}-{record.id}",
                shipment_id=record.id,
                unit_name=unit_name,
                order_number="26-0100061A",
                file_name=f"{unit_name}.xlsx",
                source_kind="general_etl",
            )
        )
        db.commit()


def test_clear_all_removes_tenant_import_fingerprints(tmp_path, monkeypatch):
    factory = _setup(tmp_path, monkeypatch)
    _seed(factory, tenant_id=1)
    _seed(factory, tenant_id=2)

    with tenant_scope(1):
        result = SQLAlchemyShipmentRecordCommand().clear_all()

    assert result["success"] is True
    with factory() as db:
        assert db.query(ShipmentRecord).filter(ShipmentRecord.tenant_id == 1).count() == 0
        assert (
            db.query(ShipmentEltImportFingerprint)
            .filter(ShipmentEltImportFingerprint.tenant_key == "tenant:1")
            .count()
            == 0
        )
        # 其他租户的指纹不能被误删
        assert (
            db.query(ShipmentEltImportFingerprint)
            .filter(ShipmentEltImportFingerprint.tenant_key == "tenant:2")
            .count()
            == 1
        )


def test_delete_record_removes_its_fingerprint(tmp_path, monkeypatch):
    factory = _setup(tmp_path, monkeypatch)
    _seed(factory, tenant_id=1)
    with factory() as db:
        record_id = db.query(ShipmentRecord.id).scalar()

    with tenant_scope(1):
        result = SQLAlchemyShipmentRecordCommand().delete_record(record_id)

    assert result["success"] is True
    with factory() as db:
        remaining = db.query(ShipmentEltImportFingerprint).filter(
            ShipmentEltImportFingerprint.shipment_id == record_id
        )
        assert remaining.count() == 0


def test_stale_fingerprint_does_not_block_reimport(tmp_path, monkeypatch):
    """指纹指向的运单已被删除时，同一文件应能重新入库而不是永久判重。"""
    from app.application.elt.targets.orders import ShipmentAdapter

    factory = _setup(tmp_path, monkeypatch)
    adapter = ShipmentAdapter()
    data = {
        "purchase_unit": "刘英",
        "product_name": "购丁酯",
        "quantity_kg": "7.2",
        "quantity_tins": 1,
        "external_order_no": "26-0100061A",
    }
    with factory() as db:
        db.add(
            ShipmentEltImportFingerprint(
                tenant_key="tenant:1",
                fingerprint=adapter._fingerprint(data, {}),
                shipment_id=49,
                unit_name="刘英",
                order_number="26-0100061A",
                source_kind="general_etl",
            )
        )
        db.commit()
        with tenant_scope(1):
            decision = adapter.preview(db, data, allowed_update_fields=set(), context={})
    assert decision.action == "new"


def test_stale_fingerprint_is_replaced_on_execute(tmp_path, monkeypatch):
    """执行时同一指纹的旧行仍在：必须先清旧行，否则唯一约束会让整批导入回滚。"""
    from app.application.elt.targets.orders import ShipmentAdapter

    factory = _setup(tmp_path, monkeypatch)
    adapter = ShipmentAdapter()
    data = {
        "purchase_unit": "澜宇家私",
        "product_name": "电视柜",
        "quantity_kg": "1.5",
        "quantity_tins": 1,
        "external_order_no": "26-0100051A",
    }
    fingerprint = adapter._fingerprint(data, {})
    with factory() as db, tenant_scope(1):
        db.add(
            ShipmentEltImportFingerprint(
                tenant_key="tenant:1",
                fingerprint=fingerprint,
                shipment_id=999,
                unit_name="澜宇家私",
                order_number="26-0100051A",
                source_kind="general_etl",
            )
        )
        db.commit()
        result = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={"run_id": "run-1", "file_name": "澜宇电视柜.xlsx"},
        )
        db.commit()
        record_id = int(result["match_ref"])
        rows = (
            db.query(ShipmentEltImportFingerprint)
            .filter(ShipmentEltImportFingerprint.fingerprint == fingerprint)
            .all()
        )
        assert len(rows) == 1
        assert int(rows[0].shipment_id) == record_id
        assert db.get(ShipmentRecord, 999) is None


def test_clear_by_unit_removes_only_matching_fingerprints(tmp_path, monkeypatch):
    factory = _setup(tmp_path, monkeypatch)
    _seed(factory, tenant_id=1, unit_name="刘英")
    _seed(factory, tenant_id=1, unit_name="宗南家私")
    with factory() as db:
        target_ids = {
            row[0]
            for row in db.query(ShipmentRecord.id)
            .filter(ShipmentRecord.purchase_unit == "刘英")
            .all()
        }

    with tenant_scope(1):
        result = SQLAlchemyShipmentRecordCommand().clear_by_unit("刘英")

    assert result["success"] is True
    with factory() as db:
        left = {
            row[0]
            for row in db.query(ShipmentEltImportFingerprint.shipment_id).all()
        }
        assert target_ids.isdisjoint(left)
        assert left  # 另一个客户的指纹保留
