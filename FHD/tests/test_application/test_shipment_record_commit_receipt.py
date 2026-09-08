from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.db.models import ShipmentRecord
from app.infrastructure.persistence.shipment_record_store_impl import SQLAlchemyShipmentRecordStore
from app.infrastructure.tenant_scope import tenant_scope


def test_record_receipt_survives_default_session_commit_and_close(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "shipment.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with tenant_scope(1):
        result = SQLAlchemyShipmentRecordStore().record_document_generation(
            unit_name="七彩乐园",
            unit_id=None,
            products=[
                {"name": "测试涂料", "model_number": "9803", "quantity_tins": 3, "tin_spec": 12}
            ],
            document_result={"doc_name": "test.xlsx"},
        )
        assert result["success"] and type(result["record_id"]) is int
        with factory() as db:
            row = db.get(ShipmentRecord, result["record_id"])
            assert row is not None
            assert row.purchase_unit == "七彩乐园" and row.tenant_id == 1
            assert row.model_number == "9803" and row.quantity_tins == 3
            assert row.quantity_kg == 36
    engine.dispose()
