"""送货单 ETL 生产就绪门禁：集成测 + 清单断言。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.shipment_app_service import ShipmentApplicationService
from app.application.shipment_excel_etl_app_service import (
    execute_shipment_excel_etl,
    note_fingerprint,
    preview_shipment_excel_etl,
    write_delivery_note_workbook,
)
from app.db.base import Base
from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint
from app.domain.shipment.aggregates import Shipment


class _MemoryRepo:
    def __init__(self) -> None:
        self.items: dict[int, Shipment] = {}
        self._n = 0
        self.fail_after = None  # type: ignore[var-annotated]

    def save(self, shipment: Shipment) -> Shipment:
        if self.fail_after is not None and self._n >= int(self.fail_after):
            raise RuntimeError("forced save failure")
        if shipment.id is None:
            self._n += 1
            shipment.id = self._n
        self.items[int(shipment.id)] = shipment
        return shipment

    def find_by_id(self, shipment_id: int) -> Shipment | None:
        return self.items.get(int(shipment_id))

    def delete(self, shipment_id: int) -> bool:
        return self.items.pop(int(shipment_id), None) is not None

    def find_all(self, page: int = 1, per_page: int = 20):
        return list(self.items.values())

    def find_by_unit(self, unit_name: str):
        return [s for s in self.items.values() if s.purchase_unit_name == unit_name]

    def count(self) -> int:
        return len(self.items)


@pytest.fixture()
def orm_fp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'etl_fp.db'}")
    Base.metadata.create_all(bind=engine, tables=[ShipmentEtlImportFingerprint.__table__])
    Session = sessionmaker(bind=engine)

    class _Ctx:
        def __enter__(self):
            self.db = Session()
            return self.db

        def __exit__(self, *a):
            self.db.close()

    monkeypatch.setenv("FHD_SHIPMENT_ETL_FINGERPRINT_BACKEND", "orm")
    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_fingerprint_store._legacy_db_path",
        lambda: tmp_path / "legacy_fp.sqlite3",
    )
    monkeypatch.setattr(
        "app.application.shipment_excel_etl_fingerprint_store._ensure_orm_table",
        lambda: True,
    )
    return engine


def test_orm_fingerprint_unique_constraint(orm_fp_db):
    from app.application.shipment_excel_etl_fingerprint_store import (
        has_fingerprint,
        record_fingerprint,
    )

    record_fingerprint("tenant:1", "abc123", shipment_id=11, unit_name="甲")
    assert has_fingerprint("tenant:1", "abc123") is True
    # 同租户同指纹二次写入应更新而非炸
    record_fingerprint("tenant:1", "abc123", shipment_id=12, unit_name="甲")
    assert has_fingerprint("tenant:1", "abc123") is True
    # 不同租户可并存
    record_fingerprint("tenant:2", "abc123", shipment_id=21, unit_name="乙")
    assert has_fingerprint("tenant:2", "abc123") is True

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=orm_fp_db)
    db = Session()
    db.add(ShipmentEtlImportFingerprint(tenant_key="tenant:1", fingerprint="abc123"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_real_create_shipment_idempotent_and_order_meta(tmp_path, monkeypatch, orm_fp_db):
    path = tmp_path / "prod.xlsx"
    write_delivery_note_workbook(
        [
            {
                "unit_name": "生产验收客户",
                "contact_person": "验收",
                "order_date": "2026年07月24日",
                "order_number": "PROD-9001",
                "items": [
                    {
                        "model_number": "P9001",
                        "product_name": "验收漆",
                        "quantity_tins": 2,
                        "tin_spec": 25,
                        "quantity_kg": 50,
                        "unit_price": 10,
                        "amount": 500,
                    }
                ],
            }
        ],
        path,
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    repo = _MemoryRepo()
    svc = ShipmentApplicationService(repository=repo)
    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", lambda: svc)
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records",
        lambda records: {"success": True, "imported": len(records)},
    )

    first = execute_shipment_excel_etl(path, workspace_root=tmp_path, idempotent=True)
    assert first["success"] is True
    assert first["shipment_created"] == 1
    assert len(repo.items) == 1
    saved = next(iter(repo.items.values()))
    assert "external_order_number=PROD-9001" in str(saved.raw_text or "")
    assert "fingerprint=" in str(saved.raw_text or "")

    second = execute_shipment_excel_etl(path, workspace_root=tmp_path, idempotent=True)
    assert second["success"] is True
    assert second["shipment_created"] == 0
    assert second["shipment_skipped"] == 1
    assert len(repo.items) == 1


def test_compensate_on_failure_rolls_back_created(tmp_path, monkeypatch, orm_fp_db):
    path = tmp_path / "multi.xlsx"
    write_delivery_note_workbook(
        [
            {
                "unit_name": "补偿客户A",
                "order_number": "C-1",
                "order_date": "2026年07月24日",
                "sheet": "A",
                "items": [
                    {
                        "model_number": "C1",
                        "product_name": "A漆",
                        "quantity_tins": 1,
                        "tin_spec": 20,
                        "quantity_kg": 20,
                        "unit_price": 8,
                        "amount": 160,
                    }
                ],
            },
            {
                "unit_name": "补偿客户B",
                "order_number": "C-2",
                "order_date": "2026年07月24日",
                "sheet": "B",
                "items": [
                    {
                        "model_number": "C2",
                        "product_name": "B漆",
                        "quantity_tins": 1,
                        "tin_spec": 20,
                        "quantity_kg": 20,
                        "unit_price": 9,
                        "amount": 180,
                    }
                ],
            },
        ],
        path,
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    class _FlakySvc(ShipmentApplicationService):
        def __init__(self, repository):
            super().__init__(repository=repository)
            self._n = 0

        def create_shipment(self, *a, **k):
            self._n += 1
            if self._n >= 2:
                return {"success": False, "message": "forced fail"}
            return super().create_shipment(*a, **k)

    repo = _MemoryRepo()
    svc = _FlakySvc(repo)
    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", lambda: svc)
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records",
        lambda records: {"success": True, "imported": len(records)},
    )

    out = execute_shipment_excel_etl(
        path,
        workspace_root=tmp_path,
        idempotent=True,
        compensate_on_failure=True,
    )
    assert out["success"] is False
    assert out["shipment_failed"] >= 1
    assert out.get("compensated")
    assert out.get("safe_to_retry") is True
    # 补偿后内存库不应残留有效 pending 单（取消后仍在 items 但 status=cancelled）
    assert all(s.status == "cancelled" for s in repo.items.values()) or len(repo.items) == 0


def test_production_gates_checklist(tmp_path, monkeypatch, orm_fp_db):
    """生产上线门禁：全部通过才算可上生产。"""
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        batch_execute_allowed,
        resolve_etl_path,
    )
    from app.utils.deployment import deployment_is_production

    path = tmp_path / "gate.xlsx"
    write_delivery_note_workbook(
        [
            {
                "unit_name": "门禁客户",
                "order_number": "G-1",
                "order_date": "2026年07月24日",
                "items": [
                    {
                        "model_number": "G1",
                        "product_name": "门禁漆",
                        "quantity_tins": 1,
                        "tin_spec": 25,
                        "quantity_kg": 25,
                        "unit_price": 10,
                        "amount": 250,
                    }
                ],
            }
        ],
        path,
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("FHD_SHIPMENT_ETL_ALLOW_BATCH", raising=False)

    gates = {}

    # 1) 路径沙箱
    try:
        resolve_etl_path("/etc/hosts", workspace_root=tmp_path)
        gates["path_sandbox"] = False
    except ShipmentEtlPathError:
        gates["path_sandbox"] = True

    # 2) 批量默认关闭
    gates["batch_disabled_by_default"] = batch_execute_allowed() is False

    # 3) dry-run 不写库
    repo = _MemoryRepo()
    svc = ShipmentApplicationService(repository=repo)
    monkeypatch.setattr("app.bootstrap.get_shipment_app_service", lambda: svc)
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records",
        lambda records: {"success": True, "imported": len(records)},
    )
    dry = execute_shipment_excel_etl(path, dry_run=True, workspace_root=tmp_path)
    gates["dry_run"] = dry.get("dry_run") is True and len(repo.items) == 0

    # 4) 预览含确认与重复计数字段
    preview = preview_shipment_excel_etl(path, workspace_root=tmp_path)
    gates["preview_contract"] = bool(
        preview.get("success")
        and preview.get("confirm_required")
        and "duplicate_note_count" in preview
        and preview.get("notes")
    )

    # 5) 指纹唯一 + 幂等
    first = execute_shipment_excel_etl(path, workspace_root=tmp_path)
    second = execute_shipment_excel_etl(path, workspace_root=tmp_path)
    gates["idempotent"] = (
        first.get("success") is True
        and first.get("shipment_created") == 1
        and second.get("shipment_created") == 0
        and second.get("shipment_skipped") == 1
    )
    gates["order_meta"] = "external_order_number=G-1" in str(
        next(iter(repo.items.values())).raw_text or ""
    )

    # 6) 指纹长度稳定
    fp = note_fingerprint(preview["notes"][0])
    gates["fingerprint_stable"] = len(fp) >= 16

    # 7) ORM 表存在唯一约束
    uq = ShipmentEtlImportFingerprint.__table_args__[0]
    gates["db_unique"] = getattr(uq, "name", "") == "uq_shipment_etl_tenant_fingerprint"

    # 8) 生产环境探测函数可用（不要求当前就在 production）
    gates["deployment_probe"] = callable(deployment_is_production)

    failed = [k for k, v in gates.items() if not v]
    assert not failed, f"production gates failed: {failed}; detail={gates}"


def test_fixtures_roundtrip_still_ok():
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "shipment_etl"
        / "闭环测试_送货单模板.xlsx"
    )
    if not fixture.is_file():
        pytest.skip("fixture missing")
    from app.application.shipment_excel_etl_app_service import parse_delivery_notes

    parsed = parse_delivery_notes(fixture, include_ledger=False)
    assert parsed["success"] is True
    assert parsed["note_count"] >= 1
