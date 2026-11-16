"""Old ETL import paths and permission codes must keep working after the ELT rename."""

from __future__ import annotations

from types import SimpleNamespace

from app.application.tenant_rbac_policy import canonical_permission_code
from app.compat import elt_import_aliases as aliases


def test_canonical_permission_code_maps_legacy_etl_codes():
    assert canonical_permission_code("etl.read") == "elt.read"
    assert canonical_permission_code("elt.execute") == "elt.execute"
    assert canonical_permission_code("customer.view") == "customer.view"


def test_legacy_etl_permission_still_authorizes_canonical_elt_codes(monkeypatch):
    from app.domain.shared_services.auth_service import AuthService

    service = AuthService()
    monkeypatch.setattr(
        service,
        "get_user_permissions",
        lambda _user: [
            canonical_permission_code("etl.read"),
            canonical_permission_code("etl.execute"),
        ],
    )
    user = SimpleNamespace(role="user", tier="user", tenant_id=1)
    monkeypatch.setattr("app.db.bootstrap.guarded.enabled", lambda: False)
    assert service.has_permission(user, "elt.read") is True
    assert service.has_permission(user, "etl.execute") is True


def test_deprecated_ocr_module_exports_tables_to_workbook_path():
    import app.application.shipment_excel_elt_ocr as current
    import app.application.shipment_excel_etl_ocr as legacy

    assert legacy is current
    assert legacy.tables_to_workbook_path is current.tables_to_workbook_path


def test_deprecated_profile_module_keeps_old_symbol_names():
    import app.application.shipment_elt_profile as current
    import app.application.shipment_etl_profile as legacy

    assert legacy is current
    assert hasattr(legacy, "ShipmentEtlProfile")
    assert legacy.ShipmentEtlProfile is current.ShipmentEltProfile
