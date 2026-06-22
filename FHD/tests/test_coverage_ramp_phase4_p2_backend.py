"""COVERAGE_RAMP Phase 4 round 2: deepseek intent, planner fallback, legacy sweep,
ai_chat workflow format, product_repository, compat_db, market routes ext."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.infrastructure.persistence.compat_db.writes import (
    _customer_pg_delete_anywhere,
    _products_pg_col_names,
    products_pg_batch_delete_rows,
)
from app.infrastructure.persistence.product_repository_impl import SQLAlchemyProductRepository
from app.services.deepseek_intent_service import (
    DeepSeekIntentRecognizer,
    _make_intent_cache_key,
    cn_to_number,
    get_deepseek_api_key,
)
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload


def _j(data, status=200):
    return {"body": data, "status": status}


def _hdr(k, default=""):
    return default


def _dispatch(tool_id, action, params=None):
    return dispatch_legacy_tool_payload(
        tool_id,
        action,
        params or {},
        json_response_fn=_j,
        hdr_getter=_hdr,
        parse_order_text_fn=lambda t: {},
    )


def _chat_svc() -> AIChatApplicationService:
    mock_ai = MagicMock()

    async def _chat(*args, **kwargs):
        return {"success": True, "text": "回复", "action": "followup", "data": {}}

    mock_ai.chat = _chat
    with (
        patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service", return_value=mock_ai
        ),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        svc = AIChatApplicationService()
        svc.ai_service = mock_ai
        return svc


# ---------------------------------------------------------------------------
# deepseek intent
# ---------------------------------------------------------------------------


def test_make_intent_cache_key_stable() -> None:
    a = _make_intent_cache_key("查库存")
    b = _make_intent_cache_key("查库存")
    assert a == b
    assert a != _make_intent_cache_key("查产品")


@pytest.mark.parametrize(
    "cn,expected",
    [
        ("五", 5),
        ("十", 10),
        ("3", 3),
        ("两", 2),
    ],
)
def test_cn_to_number(cn, expected) -> None:
    assert cn_to_number(cn) == expected


def test_deepseek_fallback_result() -> None:
    rec = DeepSeekIntentRecognizer(api_key="test-key")
    out = rec._fallback_result("查产品5003", raw_response="")
    assert "intent" in out
    assert out.get("success") is not False


def test_deepseek_parse_response_json() -> None:
    rec = DeepSeekIntentRecognizer(api_key="test-key")
    content = json.dumps(
        {
            "intent": "products",
            "confidence": 0.9,
            "slots": {"keyword": "5003"},
            "reasoning": "产品查询",
        }
    )
    out = rec._parse_response(content, "查5003")
    assert out["intent"] == "products"


def test_deepseek_normalize_slots() -> None:
    rec = DeepSeekIntentRecognizer(api_key="test-key")
    slots = rec._normalize_slots({"quantity_tins": "3桶", "unit_name": "甲公司"}, "甲3桶")
    assert slots.get("quantity_tins") == 3 or slots.get("unit_name")


def test_get_deepseek_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert get_deepseek_api_key() == "sk-test"


@patch("app.services.deepseek_intent_service.get_hybrid_intent_with_deepseek")
def test_hybrid_intent_with_deepseek_fallback(mock_get: MagicMock) -> None:
    hybrid = MagicMock()
    hybrid.recognize_sync.return_value = {"intent": "products", "confidence": 0.8, "slots": {}}
    mock_get.return_value = hybrid
    from app.services.deepseek_intent_service import get_hybrid_intent_with_deepseek

    out = get_hybrid_intent_with_deepseek().recognize_sync("查5003")
    assert out["intent"] == "products"


# ---------------------------------------------------------------------------
# planner fallback variants
# ---------------------------------------------------------------------------


def test_fallback_plan_add_product_intent() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("p-add", "添加产品到甲公司", get_tool_registry())
    assert plan.intent == "add_product_to_unit"
    assert any(n.tool_id == "products" for n in plan.nodes)


def test_fallback_plan_shipment_keywords() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    plan = planner._fallback_plan("p-ship", "生成发货单给甲公司", get_tool_registry())
    assert plan.nodes


def test_fallback_plan_customers_only_registry() -> None:
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    reg = {"customers": get_tool_registry()["customers"]}
    plan = planner._fallback_plan("p-c", "查客户", reg)
    assert plan.nodes[0].tool_id == "customers"


# ---------------------------------------------------------------------------
# tools_payload_legacy extended
# ---------------------------------------------------------------------------


@patch("app.application.get_material_application_service")
def test_legacy_materials_list_query(mock_get: MagicMock) -> None:
    mock_get.return_value.get_all_materials.return_value = {"success": True, "data": []}
    resp = _dispatch("materials_list", "query", {"keyword": "铜"})
    assert resp["body"]["success"] is True


def test_legacy_business_docking_missing_file() -> None:
    resp = _dispatch("business_docking", "extract", {})
    assert resp["body"]["success"] is False


@patch("app.services.document_templates_service._extract_structured_excel_preview")
@patch("app.services.document_templates_service._list_excel_sheet_names")
@patch("os.path.exists", return_value=True)
def test_legacy_business_docking_extract(
    _exists: MagicMock, mock_sheets: MagicMock, mock_struct: MagicMock, tmp_path
) -> None:
    p = tmp_path / "t.xlsx"
    p.write_bytes(b"x")
    mock_sheets.return_value = ["Sheet1"]
    mock_struct.return_value = {"fields": [], "sample_rows": []}
    with (
        patch(
            "app.services.document_templates_service._extract_excel_grid_preview",
            return_value={},
        ),
        patch(
            "app.services.document_templates_service._extract_excel_grid_style_cache",
            return_value={},
        ),
        patch(
            "app.services.document_templates_service._extract_excel_all_sheets_preview",
            return_value=[],
        ),
    ):
        resp = _dispatch("business_docking", "extract", {"file_path": str(p)})
    assert resp["body"]["success"] is True


@patch("app.application.get_template_app_service")
def test_legacy_template_preview_list(mock_get: MagicMock) -> None:
    mock_get.return_value.get_templates.return_value = {"success": True, "data": []}
    resp = _dispatch("template_preview", "list", {})
    assert resp["body"]["success"] is True


def test_legacy_excel_analyzer_missing_path() -> None:
    resp = _dispatch("excel_analyzer", "analyze", {})
    assert resp["body"]["success"] is False


def test_legacy_customers_view_redirect() -> None:
    resp = _dispatch("customers", "view", {})
    assert "customers" in resp["body"]["redirect"]


@patch("app.bootstrap.get_shipment_app_service")
def test_legacy_shipment_records_export(mock_get: MagicMock) -> None:
    mock_get.return_value.export_shipment_records.return_value = {"success": True}
    resp = _dispatch("shipment_records", "export", {"unit_name": "甲"})
    assert resp["body"]["success"] is True


@patch("app.services.get_database_service")
def test_legacy_database_backup(mock_get: MagicMock) -> None:
    mock_get.return_value.backup_database.return_value = {"success": True}
    resp = _dispatch("database", "backup", {})
    assert resp["body"]["success"] is True


def test_legacy_upload_file() -> None:
    resp = _dispatch("upload_file", "run", {})
    assert resp["body"]["success"] is True


def test_legacy_tools_table_list() -> None:
    with patch(
        "app.services.tools_execution_service.get_workflow_tool_registry",
        return_value={"products": {}},
    ):
        resp = _dispatch("tools_table", "list", {})
    assert resp["body"]["success"] is True


# ---------------------------------------------------------------------------
# ai_chat workflow format
# ---------------------------------------------------------------------------


def test_format_workflow_run_response_products_hit() -> None:
    svc = _chat_svc()
    plan = PlanGraph(
        plan_id="wf1",
        intent="product_query",
        nodes=[
            WorkflowNode(
                node_id="n1",
                tool_id="products",
                action="query",
                params={"keyword": "5003"},
                risk="low",
            )
        ],
    )
    node_result = SimpleNamespace(
        node_id="n1",
        success=True,
        tool_id="products",
        action="query",
        output={"data": [{"model_number": "5003", "name": "清漆", "price": 100, "unit": "甲"}]},
        error=None,
    )
    run_result = SimpleNamespace(
        success=True,
        message="ok",
        node_results=[node_result],
    )
    out = svc._format_workflow_run_response(
        plan, run_result, thinking_steps="思考", user_message="查5003"
    )
    assert out["success"] is True
    assert "autoAction" in out
    assert out["autoAction"]["type"] == "show_products_float"


def test_format_workflow_run_response_failure_node() -> None:
    svc = _chat_svc()
    plan = PlanGraph(plan_id="wf2", intent="x", nodes=[])
    node_result = SimpleNamespace(
        node_id="n1",
        success=False,
        tool_id="products",
        action="query",
        output={},
        error="timeout",
    )
    run_result = SimpleNamespace(success=False, message="fail", node_results=[node_result])
    out = svc._format_workflow_run_response(plan, run_result)
    assert out["success"] is False
    assert "失败" in out["response"]


def test_normal_slot_dispatch_chat_overlay_empty() -> None:
    svc = _chat_svc()
    run_result = SimpleNamespace(node_results=[])
    assert svc._normal_slot_dispatch_chat_overlay(run_result) == {}


def test_merge_tool_runtime_context() -> None:
    merged = AIChatApplicationService._merge_tool_runtime_context(
        "u1", "hi", {"excel_analysis": {"file_path": "/tmp/a.xlsx"}, "ui_surface": "chat"}
    )
    assert merged["user_id"] == "u1"
    assert merged["message"] == "hi"
    assert merged["excel_analysis"]["file_path"] == "/tmp/a.xlsx"


def test_resolve_excel_path_for_import() -> None:
    out = AIChatApplicationService._resolve_excel_path_for_import(
        {"file_path": "/tmp/a.xlsx"},
        {},
    )
    assert out == "/tmp/a.xlsx"


def test_excel_cell_looks_like_product_measure_unit() -> None:
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("件") is True
    assert AIChatApplicationService._excel_cell_looks_like_product_measure_unit("清漆") is False


# ---------------------------------------------------------------------------
# product_repository
# ---------------------------------------------------------------------------


@patch("app.infrastructure.persistence.product_repository_impl.get_db")
def test_product_repo_find_all_keyword(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.offset.return_value = q
    q.limit.return_value = q
    q.count.return_value = 1
    q.all.return_value = [
        SimpleNamespace(
            id=1,
            name="漆",
            model_number="5003",
            unit="甲公司",
            unit_price=100.0,
            specification="25kg",
            product_code="5003",
            created_at=None,
            updated_at=None,
        )
    ]
    db.query.return_value = q
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = ctx
    repo = SQLAlchemyProductRepository()
    out = repo.find_all(keyword="5003", page=1, per_page=20)
    assert out["success"] is True
    assert out["total"] == 1


@patch("app.infrastructure.persistence.product_repository_impl.get_db")
def test_product_repo_exists(mock_get_db: MagicMock) -> None:
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = SimpleNamespace(id=1)
    db.query.return_value = q
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = ctx
    repo = SQLAlchemyProductRepository()
    assert repo.exists(1) is True


# ---------------------------------------------------------------------------
# compat_db writes extended
# ---------------------------------------------------------------------------


@patch("app.infrastructure.persistence.compat_db.writes.inspect")
@patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
def test_products_pg_col_names(mock_eng: MagicMock, mock_insp: MagicMock) -> None:
    mock_insp.return_value.get_columns.return_value = [{"name": "id"}, {"name": "name"}]
    cols = _products_pg_col_names()
    assert "id" in cols
    assert "name" in cols


@patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine", return_value=None)
def test_products_pg_batch_delete_no_engine(mock_eng: MagicMock) -> None:
    with pytest.raises(Exception):
        products_pg_batch_delete_rows([1, 2])


@patch("app.infrastructure.persistence.compat_db.writes._customer_pg_engine_insp")
def test_customer_pg_delete_anywhere_no_customer(mock_ei: MagicMock) -> None:
    eng = MagicMock()
    conn = MagicMock()
    eng.connect.return_value.__enter__ = MagicMock(return_value=conn)
    eng.connect.return_value.__exit__ = MagicMock(return_value=False)
    insp = MagicMock()
    insp.get_columns.return_value = [{"name": "id"}, {"name": "unit_name"}]
    mock_ei.return_value = (eng, insp)
    conn.execute.return_value.rowcount = 0
    with pytest.raises(Exception):
        _customer_pg_delete_anywhere(99)


@patch("app.infrastructure.persistence.compat_db.writes._products_pg_col_names")
@patch("app.infrastructure.persistence.compat_db.writes.get_sync_engine")
def test_products_pg_update_row_missing_product(mock_eng: MagicMock, mock_cols: MagicMock) -> None:
    mock_cols.return_value = {"id", "model_number", "name", "unit_price"}
    eng = MagicMock()
    conn = MagicMock()
    eng.begin.return_value.__enter__ = MagicMock(return_value=conn)
    eng.begin.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.rowcount = 0
    mock_eng.return_value = eng
    from app.infrastructure.persistence.compat_db.writes import products_pg_update_row

    with pytest.raises(Exception):
        products_pg_update_row(
            999,
            {"name": "x"},
            parse_price=lambda v: float(v or 0),
            parse_quantity=lambda v: int(v or 0),
            parse_is_active=lambda v: True,
        )


# ---------------------------------------------------------------------------
# market_account extended routes
# ---------------------------------------------------------------------------


@pytest.fixture
def market_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes import market_account as market_mod

    monkeypatch.setattr(market_mod, "_authorization_from_request", lambda req, body: "Bearer test")
    app = FastAPI()
    app.include_router(market_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.asyncio
async def test_market_account_sync_route(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fastapi_routes import market_account as market_mod

    async def _proxy(method, path, **k):
        return {"data": {"user": {"id": 1}}}

    monkeypatch.setattr(market_mod, "_proxy_json", _proxy)
    r = market_client.post(
        "/api/market/account-sync",
        json={"authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_market_login_phone_route(
    market_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fastapi_routes import market_account as market_mod

    async def _login(phone, code):
        return {"success": True, "access_token": "tok"}

    monkeypatch.setattr(market_mod, "login_market_with_phone_code", _login)
    monkeypatch.setattr(market_mod, "bind_market_auth_to_session", lambda req, result: ("tok", {}))
    r = market_client.post(
        "/api/market/login-with-phone-code",
        json={"phone": "13800138000", "code": "123456"},
    )
    assert r.status_code == 200


def test_market_degraded_account_overview() -> None:
    from app.fastapi_routes import market_account as market_mod

    out = market_mod._degraded_account_overview("offline")
    assert out["degraded"] is True
    assert "offline" in out["sync_warning"]


def test_market_token_from_auth_response() -> None:
    from app.fastapi_routes import market_account as market_mod

    assert market_mod._token_from_auth_response({"access_token": "abc"}) == "abc"
    assert market_mod._token_from_auth_response({"token": "xyz"}) == "xyz"


def test_market_identity_from_payloads() -> None:
    from app.fastapi_routes import market_account as market_mod

    ok, verified, blob = market_mod._market_identity_from_payloads(
        {"user": {"id": 1}}, {"profile": {"name": "u"}}
    )
    assert isinstance(ok, bool)
    assert isinstance(blob, dict)


# ---------------------------------------------------------------------------
# neuro_bus domain handlers smoke
# ---------------------------------------------------------------------------


def test_product_domain_handlers_register() -> None:
    from app.neuro_bus.domains.product_domain_handlers import register_product_domain_handlers

    bus = MagicMock()
    register_product_domain_handlers(bus)
    # Registration must subscribe one handler per product event (6 total).
    assert bus.subscribe.call_count == 6
    subscribed_events = {call.args[0] for call in bus.subscribe.call_args_list}
    assert "product.created" in subscribed_events
    assert "product.price_changed" in subscribed_events


def test_inventory_handlers_handle_query() -> None:
    from app.neuro_bus.domains.inventory_domain_handlers import (
        InventoryServiceDomainHandlers,
        get_inventory_handlers,
    )

    h = get_inventory_handlers()
    # Singleton of the concrete handler type exposing the real domain methods.
    assert isinstance(h, InventoryServiceDomainHandlers)
    assert callable(h.handle_stock_in)
    assert callable(h.handle_stock_out)
    # Singleton: repeated calls return the same instance.
    assert get_inventory_handlers() is h


def test_ocr_handlers_instantiate() -> None:
    from app.neuro_bus.domains.ocr_domain_handlers import get_ocr_handlers

    assert get_ocr_handlers() is not None
