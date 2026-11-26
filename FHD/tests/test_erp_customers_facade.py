from __future__ import annotations

import json
from pathlib import Path

import pytest

MOD_DIR = Path(__file__).resolve().parents[1] / "mods" / "bridge" / "xcagi-erp-domain-bridge"


def test_manifest_customers_via_service():
    data = json.loads((MOD_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert data.get("config", {}).get("customers_via_service") is True
    assert data.get("config", {}).get("wechat_contacts_via_facade") is False


def test_customers_list_via_service(monkeypatch):
    from app.mod_sdk import erp_customers_facade as cf

    monkeypatch.setattr(cf, "is_erp_customers_via_service_enabled", lambda: True)

    class FakeSvc:
        def get_all(self, keyword=None, page=1, per_page=20):
            return {"success": True, "data": [{"id": 2, "customer_name": "ACME"}], "total": 1}

    monkeypatch.setattr(cf, "_service", lambda: FakeSvc())
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda request: None,
    )
    out = cf.customers_list(None, page=1, per_page=20)
    assert out["success"] is True
    assert out["total"] == 1
    assert out.get("execution_path") == "customers_service"


def test_facade_customer_write_contract_rejects_invalid_payload_without_execution(monkeypatch):
    from pydantic import ValidationError

    from app.mod_sdk import erp_customers_facade as facade

    called = []
    monkeypatch.setattr(facade, "_run_customer_capability", lambda *a, **kw: called.append((a, kw)))
    for bad in (
        {"unit_name": "Alpha", "name": "Beta"},
        {"unit_name": 2},
        {"unit_name": "Acme", "expected_version": True},
    ):
        with pytest.raises(ValidationError):
            facade.customers_create(None, bad)
        with pytest.raises(ValidationError):
            facade.customers_update(None, 7, bad)
    assert called == []


def test_facade_customer_update_normalizes_version_without_client_tenant(monkeypatch):
    from app.mod_sdk import erp_customers_facade as facade

    records = []
    monkeypatch.setattr(
        facade,
        "_run_customer_capability",
        lambda request, action, params: records.append((action, params)),
    )
    facade.customers_update(
        None,
        42,
        {"unit_name": "  Acme  ", "expected_version": "2", "tenant_id": 999},
    )
    assert records == [
        (
            "update",
            {
                "id": 42,
                "customer_name": "Acme",
                "contact_person": "",
                "contact_phone": "",
                "contact_address": "",
                "expected_version": 2,
            },
        )
    ]
