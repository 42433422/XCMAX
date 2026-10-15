from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.application.order_webhook_registry import list_webhooks
from app.fastapi_routes.knowledge_v1 import _KnowledgeIndex
from app.infrastructure.auth import business_scope_gate
from app.services import reconciliation_scheduler


def test_reconciliation_state_stays_in_user_data(monkeypatch, tmp_path: Path) -> None:
    data = str(tmp_path / "userdata")
    monkeypatch.setattr("app.utils.path_io.path_utils.get_data_dir", lambda: data)

    def snap(_start, end):
        row = {"period_start": "s", "orders": [], "totals": {}, "anomalies": []}
        row["period_end"] = end.isoformat()
        return row

    monkeypatch.setattr(reconciliation_scheduler, "compute_fhd_period_snapshot", snap)
    assert reconciliation_scheduler.run_reconciliation_full_cycle()["success"] is True
    state = tmp_path / "userdata" / "reconciliation_state.json"
    assert state.is_file() and "XCAGI.app" not in str(state)


def test_legacy_knowledge_index_does_not_cross_tenants() -> None:
    index = _KnowledgeIndex()

    def piece(text):
        return [SimpleNamespace(text=text, char_start=0, char_end=len(text), strategy="f")]

    index._chunker.split_by_fixed = lambda text, **_k: piece(text)
    index._chunker.split_by_semantic = piece
    index._retriever.retrieve = lambda _q: list(index._chunks)
    index.ingest("only-tenant-a", "a", "fixed", 100, 0, tenant_id="1")
    index.ingest("only-tenant-b", "b", "fixed", 100, 0, tenant_id="2")
    seen = " ".join(c.text for c in index.query("only", 5, tenant_id="1"))
    assert "only-tenant-a" in seen and "only-tenant-b" not in seen


def test_order_webhooks_are_listed_for_one_tenant(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.application.order_webhook_registry.get_data_dir", lambda: str(tmp_path)
    )
    raw = (
        '{"tenants":{"1":[{"url":"https://one.example/h"}],"2":[{"url":"https://two.example/h"}]}}'
    )
    (tmp_path / "order_webhooks.json").write_text(raw, encoding="utf-8")
    assert list_webhooks(1) == [{"url": "https://one.example/h"}]
    assert list_webhooks(9) == []


def test_label_products_allow_enterprise_tenant(monkeypatch) -> None:
    from app.fastapi_routes.print_routes import router

    monkeypatch.setattr(business_scope_gate, "resolve_product_sku", lambda: "enterprise")
    user = SimpleNamespace(id=7, tenant_id=11, role="user", tier="enterprise")
    denied = SimpleNamespace(id=7, tenant_id=None, role="user", tier="enterprise")
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(has_permission=lambda _u, code: code == "print.label"),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr(business_scope_gate, "resolve_session_user", lambda _r: denied)
    blocked = client.get("/api/print/label-jobs/products")
    assert blocked.status_code == 403 and "租户" in blocked.text
    monkeypatch.setattr(business_scope_gate, "resolve_session_user", lambda _r: user)
    assert client.get("/api/print/label-jobs/products").status_code != 403


def test_shipment_create_records_the_unit(monkeypatch) -> None:
    from app.services.tools_workflow_shipments_docs import _registered_router_business_event

    seen = {}

    def remember(payload):
        seen["unit"] = payload.get("unit_name")
        return {"success": True, "record_id": 42}

    monkeypatch.setattr(
        "app.services.tools_workflow_shipments_docs._remember_business_shipment", remember
    )
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.publish_neuro_event", lambda *_a, **_k: True
    )
    result = _registered_router_business_event(
        "shipment_create", {"unit_name": "MAC验收出货客户", "items": []}, {}, "admin", ""
    )
    assert result["published"] is True and result["record_id"] == 42
    assert seen["unit"] == "MAC验收出货客户"


def test_pdf_full_read_writes_requested_json(tmp_path: Path) -> None:
    pdf = tmp_path / "note.pdf"
    sheet = canvas.Canvas(str(pdf))
    sheet.drawString(72, 720, "SUNBIRD box 24")
    sheet.save()
    out = tmp_path / "outputs" / "pdf-read.json"
    rel = "mods/_employees/pdf-full-read-employee/backend/vendor/pdf_full_read/convert.py"
    path = Path(__file__).resolve().parents[2] / rel
    spec = importlib.util.spec_from_file_location("pdf_full_read_convert_round3", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    spec_json = {"default_output_relpath": "t.txt", "default_meta_relpath": "m.json"}
    asyncio.run(
        module.convert_file(pdf, out, template_path=None, payload={}, ctx={}, rule_spec=spec_json)
    )
    assert "SUNBIRD" in out.read_text(encoding="utf-8")
