"""送货单 ETL 生产就绪门禁：集成测 + 清单断言。"""

from __future__ import annotations

import os
import tempfile
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


def _create_test_symlink(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt":
            pytest.skip(f"Windows runner cannot create a test reparse point: {exc}")
        raise


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
    from app.application.excel_etl_kb import reset_excel_etl_kb_for_tests
    from app.application.shipment_etl_profile import clear_profile_cache

    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(tmp_path / "kb.json"))
    monkeypatch.setenv("FHD_EXCEL_ETL_DEFAULT_TARGET", "shipment")
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.delenv("FHD_EXCEL_ETL_ALLOW_BUILTIN", raising=False)
    reset_excel_etl_kb_for_tests(tmp_path / "kb.json")
    clear_profile_cache()

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
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
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


def test_etl_path_resolver_rejects_traversal_and_symlink_escape(tmp_path, monkeypatch):
    """Resolved paths must stay under the configured root, including through links."""
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "private.xlsx"
    secret.write_bytes(b"not an ETL workbook")
    prefix_sibling = tmp_path / "allowed-other"
    prefix_sibling.mkdir()
    sibling_file = prefix_sibling / "private.xlsx"
    sibling_file.write_bytes(b"not an allowed-root file")
    link = allowed / "linked.xlsx"
    _create_test_symlink(link, secret)
    (allowed / "input.xlsx").write_bytes(b"inside")

    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    assert security.resolve_etl_path("input.xlsx") == allowed / "input.xlsx"
    for raw in ("../outside/private.xlsx", str(secret), str(sibling_file), str(link)):
        with pytest.raises(security.ShipmentEtlPathError):
            security.resolve_etl_path(raw)


def test_etl_input_opens_only_regular_files_beneath_the_trusted_root(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    safe_file = allowed / "input.xlsx"
    safe_file.write_bytes(b"trusted workbook")
    outside = tmp_path / "private.xlsx"
    outside.write_bytes(b"private workbook")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with security.open_etl_input_file(safe_file) as stream:
        assert stream.read() == b"trusted workbook"
    with pytest.raises(security.ShipmentEtlPathError):
        with security.open_etl_input_file(outside):
            pytest.fail("an outside file must not be opened")


def test_etl_input_rejects_a_leaf_symlink_swapped_after_resolution(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "input.xlsx"
    source.write_bytes(b"trusted workbook")
    outside = tmp_path / "private.xlsx"
    outside.write_bytes(b"private workbook")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    resolve = security.resolve_etl_path

    def replace_after_resolve(path, **kwargs):
        resolved = resolve(path, **kwargs)
        source.unlink()
        _create_test_symlink(source, outside)
        return resolved

    monkeypatch.setattr(security, "resolve_etl_path", replace_after_resolve)
    with pytest.raises((security.ShipmentEtlPathError, OSError)):
        with security.open_etl_input_file(source) as stream:
            pytest.fail(f"must not read swapped private input: {stream.read()!r}")


def test_prepare_etl_output_path_rejects_existing_leaf_symlink(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    output_dir = allowed / "outputs"
    output_dir.mkdir(parents=True)
    outside = tmp_path / "private.json"
    outside.write_text("private", encoding="utf-8")
    link = output_dir / "data.json"
    _create_test_symlink(link, outside)
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with pytest.raises(security.ShipmentEtlPathError):
        security.prepare_etl_output_path(link)
    assert outside.read_text(encoding="utf-8") == "private"


def test_etl_output_resolver_rejects_symlink_escape_without_writing(tmp_path, monkeypatch):
    """An existing output alias cannot redirect a workbook write outside the root."""
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"preserve this file")
    _create_test_symlink(allowed / "result.xlsx", outside)

    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with pytest.raises(security.ShipmentEtlPathError):
        security.resolve_etl_output_path(allowed / "result.xlsx")
    assert outside.read_bytes() == b"preserve this file"


def test_etl_output_writer_rejects_leaf_symlink_replaced_after_validation(tmp_path, monkeypatch):
    """The atomic publish check rejects a symlink inserted after validation."""

    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"preserve this file")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    destination = security.resolve_etl_output_path(allowed / "result.xlsx")
    reject_symlink = (
        security._windows_reject_existing_reparse_leaf
        if os.name == "nt"
        else security._reject_output_symlink
    )
    inserted_link = False

    def insert_leaf_link_before_publish(*args):
        nonlocal inserted_link
        if os.name == "nt":
            parent_fd, name = args
        else:
            name, parent_fd, _parent_path = args
        if name == destination.name and not inserted_link:
            _create_test_symlink(destination, outside)
            inserted_link = True
        return reject_symlink(*args)

    monkeypatch.setattr(
        security,
        "_windows_reject_existing_reparse_leaf" if os.name == "nt" else "_reject_output_symlink",
        insert_leaf_link_before_publish,
    )
    with pytest.raises(security.ShipmentEtlPathError):
        with security.open_etl_output_file(destination) as stream:
            stream.write(b"replacement")
    assert inserted_link is True
    assert outside.read_bytes() == b"preserve this file"


def test_etl_output_writer_rejects_parent_symlink_replaced_after_validation(tmp_path, monkeypatch):
    """Directory-descriptor traversal must reject a swapped parent link."""
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    parent = allowed / "nested"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    destination = security.resolve_etl_output_path(parent / "result.xlsx")
    open_directory = security._open_directory_under_root
    calls = 0

    def replace_parent_before_open(root, directory, *, create):
        nonlocal calls
        calls += 1
        if calls == 1:
            directory.rmdir()
            _create_test_symlink(directory, outside, target_is_directory=True)
        return open_directory(root, directory, create=create)

    monkeypatch.setattr(security, "_open_directory_under_root", replace_parent_before_open)
    with pytest.raises(security.ShipmentEtlPathError):
        with security.open_etl_output_file(destination):
            pytest.fail("a swapped parent symlink must not be traversed")
    assert not (outside / destination.name).exists()


def test_etl_output_writer_atomically_overwrites_and_creates_parent(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    destination = allowed / "nested" / "result.xlsx"
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with security.open_etl_output_file(destination) as stream:
        stream.write(b"first workbook")
    assert destination.read_bytes() == b"first workbook"
    with security.open_etl_output_file(destination) as stream:
        stream.write(b"replacement workbook")
    assert destination.read_bytes() == b"replacement workbook"
    assert sorted(path.name for path in destination.parent.iterdir()) == ["result.xlsx"]


def test_etl_output_writer_preserves_existing_file_and_cleans_temp_on_failure(
    tmp_path, monkeypatch
):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    destination = allowed / "result.xlsx"
    destination.write_bytes(b"previous valid workbook")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with pytest.raises(RuntimeError, match="simulated workbook failure"):
        with security.open_etl_output_file(destination) as stream:
            stream.write(b"partial replacement")
            raise RuntimeError("simulated workbook failure")

    assert destination.read_bytes() == b"previous valid workbook"
    assert sorted(path.name for path in allowed.iterdir()) == ["result.xlsx"]


def test_etl_output_writer_fails_closed_without_secure_platform_handles(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    destination = allowed / "new" / "result.xlsx"
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.setattr(security, "_secure_output_handles_available", lambda: False)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    with pytest.raises(security.ShipmentEtlPathError, match="secure ETL output is unavailable"):
        with security.open_etl_output_file(destination):
            pytest.fail("must not fall back to path-based output")
    assert not destination.parent.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules only")
@pytest.mark.parametrize("name", ["report.xlsx:stream", "CON.xlsx", "NUL", "sample?.xlsx"])
def test_windows_output_component_rejects_device_names_and_streams(name):
    from app.application import shipment_excel_etl_security as security

    with pytest.raises(security.ShipmentEtlPathError):
        security._validated_path_component(name)


def test_etl_path_resolver_does_not_trust_cwd_or_global_temp(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    app_data = tmp_path / "app-data"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(app_data))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    outsider = tmp_path / "other-workspace"
    outsider.mkdir()
    private_file = outsider / "private.xlsx"
    private_file.write_bytes(b"private")

    roots = security._trusted_base_roots()
    assert Path.cwd() not in roots
    assert Path(tempfile.gettempdir()) not in roots
    with pytest.raises(security.ShipmentEtlPathError):
        security.resolve_etl_path(private_file)

    monkeypatch.setenv("WORKSPACE_ROOT", str(Path.cwd().parent))
    assert Path.cwd().parent.resolve() not in security._trusted_base_roots()


def test_etl_trusts_only_managed_employee_output_subdirectory(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    app_data = tmp_path / "app-data"
    monkeypatch.setenv("XCAGI_DATA_DIR", str(app_data))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)

    roots = security._trusted_base_roots()
    assert app_data / "outputs" in roots
    assert app_data not in roots
    output = security.resolve_etl_output_path(app_data / "outputs" / "report.xlsx")
    assert output == app_data / "outputs" / "report.xlsx"

    outside = tmp_path / "outside" / "report.xlsx"
    with pytest.raises(security.ShipmentEtlPathError):
        security.resolve_etl_output_path(outside)


def test_ocr_workbook_output_stays_in_configured_workspace(tmp_path, monkeypatch):
    from app.application.shipment_excel_etl_ocr import grid_to_workbook_path

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    output = grid_to_workbook_path(
        [["型号", "数量"], ["A-1", "2"]], output_path=tmp_path / "ocr.xlsx"
    )
    assert output == tmp_path / "ocr.xlsx"
    assert output.is_file()


def test_fixtures_roundtrip_still_ok(monkeypatch):
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "shipment_etl"
        / "闭环测试_送货单模板.xlsx"
    )
    if not fixture.is_file():
        pytest.skip("fixture missing")
    monkeypatch.setenv("WORKSPACE_ROOT", str(fixture.parent))
    from app.application.shipment_excel_etl_app_service import parse_delivery_notes

    parsed = parse_delivery_notes(fixture, include_ledger=False)
    assert parsed["success"] is True
    assert parsed["note_count"] >= 1
