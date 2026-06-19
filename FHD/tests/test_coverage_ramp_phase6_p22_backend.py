"""COVERAGE_RAMP Phase 6 round 22: backend medium-coverage modules.

补充覆盖以下模块的未覆盖分支（已有部分覆盖于 phase6_p7-p11）：
- ``app/fastapi_routes/ai_assistant.py`` — 边界分支（doc_name 缺失、template_name 透传等）
- ``app/mod_sdk/industry_baseline.py`` — build_industry_baseline_plan 复杂分支
- ``app/mod_sdk/planner_tools.py`` — execute_planner_workflow_tool 多分支
- ``app/neuro_bus/domains/shipment_domain_handlers.py`` — handle_* 异常路径
- ``app/neuro_bus/domains/product_domain_handlers.py`` — handle_* 异常路径
- ``app/application/employee_runtime/agent.py`` — run() 多分支
- ``app/enterprise/mod_entitlements.py`` — sync/restore/persist 边界
- ``app/fastapi_routes/mods_routes.py`` — list_mods / get_mod_detail 边界

测试原则：
- 不 mock 被测函数本身，只 mock 外部依赖
- 测试独立、确定、可复现
- 命名：test_{method}_{scenario}_{expected}
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.employee_runtime.agent import EmployeeAgent
from app.application.employee_runtime.memory import MemoryContext
from app.enterprise import mod_entitlements
from app.fastapi_routes import ai_assistant
from app.mod_sdk import industry_baseline
from app.mod_sdk.industry_baseline import (
    _custom_line_spec,
    build_industry_baseline_plan,
    build_industry_baseline_plan_for_request,
    build_onboarding_industry_catalog,
    filter_onboarding_catalog_for_entitlements,
    industry_entitled_for_client_mods,
    load_industry_baseline_document,
)
from app.mod_sdk.planner_tools import (
    PLANNER_FACADE_MOD_ID,
    execute_planner_tool_from_body,
    execute_planner_workflow_tool,
    list_planner_tools_registry_detail,
    load_mod_planner_tool_extensions,
    resolve_planner_tool_executor,
)
from app.neuro_bus.domains.product_domain_handlers import (
    ProductDomainHandlers,
    get_product_domain_handlers,
    register_product_domain_handlers,
)
from app.neuro_bus.domains.shipment_domain_handlers import (
    ShipmentDomainHandlers,
    get_shipment_domain_handlers,
    register_shipment_domain_handlers,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_event(payload: dict[str, Any]) -> MagicMock:
    """构造一个最小可用的 event mock（payload + metadata.event_id）。"""
    ev = MagicMock()
    ev.payload = payload
    ev.metadata.event_id = "evt-123"
    return ev


def _ai_assistant_client() -> TestClient:
    app = FastAPI()
    app.include_router(ai_assistant.router)
    return TestClient(app)


class _FakeProductCacheInvalidatedEvent:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.payload = payload or {}
        self.source = source
        self.correlation_id = correlation_id


class _FakeProductPriceChangedEvent:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
        **kwargs: object,
    ) -> None:
        self.payload = payload or {}
        self.source = source
        self.correlation_id = correlation_id


@pytest.fixture
def patch_product_events() -> Iterator[None]:
    with (
        patch(
            "app.neuro_bus.domains.product_domain_handlers.ProductCacheInvalidatedEvent",
            _FakeProductCacheInvalidatedEvent,
        ),
        patch(
            "app.neuro_bus.domains.product_domain_handlers.ProductPriceChangedEvent",
            _FakeProductPriceChangedEvent,
        ),
    ):
        yield


@pytest.fixture
def mock_bus() -> MagicMock:
    """提供一个新的 MagicMock bus 实例。"""
    return MagicMock()


@pytest.fixture(autouse=True)
def _clear_industry_baseline_caches() -> Iterator[None]:
    load_industry_baseline_document.cache_clear()
    yield
    load_industry_baseline_document.cache_clear()


@pytest.fixture(autouse=True)
def _reset_entitlements_cache() -> Iterator[None]:
    mod_entitlements.clear_session_entitlements()
    yield
    mod_entitlements.clear_session_entitlements()


# ===========================================================================
# 1. ai_assistant — 未覆盖分支补充
# ===========================================================================


class TestAiAssistantBranches:
    """补充 ai_assistant 未覆盖分支。"""

    def test_compat_ai_generate_success_without_doc_name_uses_basename(self) -> None:
        """doc_name 缺失时使用 file_path 的 basename。"""
        client = _ai_assistant_client()
        with (
            patch("app.application.facades.tools_facade._parse_order_text") as mock_parse,
            patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
        ):
            mock_parse.return_value = {
                "success": True,
                "unit_name": "甲公司",
                "products": [{"name": "漆", "quantity": 1, "price": 10}],
            }
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {
                "success": True,
                "file_path": "/tmp/shipment/bar.docx",
                # doc_name 缺失 → 使用 basename
                "order_number": "ORD-2",
                "total_amount": 20.0,
                "total_quantity": 2,
            }
            mock_svc_get.return_value = mock_svc
            resp = client.post(
                "/api/generate",
                json={"order_text": "甲公司 漆 1 10"},
            )
        body = resp.json()
        assert body["data"]["doc_name"] == "bar.docx"
        assert body["data"]["download_url"] == "/api/shipment/download/bar.docx"

    def test_compat_ai_generate_success_no_file_path_no_doc_name(self) -> None:
        """file_path 和 doc_name 都缺失 → download_url 为 None。"""
        client = _ai_assistant_client()
        with (
            patch("app.application.facades.tools_facade._parse_order_text") as mock_parse,
            patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
        ):
            mock_parse.return_value = {
                "success": True,
                "unit_name": "甲公司",
                "products": [{"name": "漆", "quantity": 1, "price": 10}],
            }
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {
                "success": True,
                # 没有 file_path 也没有 doc_name
                "order_number": "ORD-3",
            }
            mock_svc_get.return_value = mock_svc
            resp = client.post(
                "/api/generate",
                json={"order_text": "甲公司 漆 1 10"},
            )
        body = resp.json()
        assert body["data"]["doc_name"] is None
        assert body["data"]["download_url"] is None
        assert body["data"]["file_path"] is None

    def test_compat_ai_generate_template_name_passed_through(self) -> None:
        """template_name 应透传到 service。"""
        client = _ai_assistant_client()
        with (
            patch("app.application.facades.tools_facade._parse_order_text") as mock_parse,
            patch.object(ai_assistant, "_shipment_svc") as mock_svc_get,
        ):
            mock_parse.return_value = {
                "success": True,
                "unit_name": "甲公司",
                "products": [{"name": "漆", "quantity": 1, "price": 10}],
            }
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {
                "success": True,
                "file_path": "/tmp/x.docx",
                "doc_name": "x.docx",
            }
            mock_svc_get.return_value = mock_svc
            client.post(
                "/api/generate",
                json={"order_text": "甲公司 漆 1 10", "template_name": "custom-tpl"},
            )
        # 验证 template_name 透传
        call_kwargs = mock_svc.generate_shipment_document.call_args.kwargs
        assert call_kwargs["template_name"] == "custom-tpl"

    def test_compat_ai_generate_parse_success_no_unit_name_returns_400(self) -> None:
        """解析成功但 unit_name 为空 → 400。"""
        client = _ai_assistant_client()
        with patch("app.application.facades.tools_facade._parse_order_text") as mock_parse:
            mock_parse.return_value = {
                "success": True,
                "unit_name": "",
                "products": [{"name": "漆"}],
            }
            resp = client.post("/api/generate", json={"order_text": "x"})
        assert resp.status_code == 400
        assert "空" in resp.json()["message"]

    def test_compat_ai_generate_parse_success_no_products_returns_400(self) -> None:
        """解析成功但 products 为空 → 400。"""
        client = _ai_assistant_client()
        with patch("app.application.facades.tools_facade._parse_order_text") as mock_parse:
            mock_parse.return_value = {
                "success": True,
                "unit_name": "甲公司",
                "products": [],
            }
            resp = client.post("/api/generate", json={"order_text": "x"})
        assert resp.status_code == 400

    def test_compat_ai_generate_parse_success_products_none_returns_400(self) -> None:
        """解析成功但 products 为 None → 400。"""
        client = _ai_assistant_client()
        with patch("app.application.facades.tools_facade._parse_order_text") as mock_parse:
            mock_parse.return_value = {
                "success": True,
                "unit_name": "甲公司",
                # products 缺失
            }
            resp = client.post("/api/generate", json={"order_text": "x"})
        assert resp.status_code == 400

    def test_compat_ai_generate_parse_no_message_uses_default(self) -> None:
        """解析失败但无 message → 使用默认错误信息。"""
        client = _ai_assistant_client()
        with patch("app.application.facades.tools_facade._parse_order_text") as mock_parse:
            mock_parse.return_value = {"success": False}  # 无 message
            resp = client.post("/api/generate", json={"order_text": "x"})
        assert resp.status_code == 400
        assert "订单解析失败" in resp.json()["message"]

    def test_compat_purchase_units_create_with_name_field(self) -> None:
        """payload 使用 name 字段而非 unit_name。"""
        client = _ai_assistant_client()
        with (
            patch(
                "app.application.facades.query_facade.find_purchase_unit",
                return_value=None,
            ),
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.models.PurchaseUnit") as mock_unit_cls,
        ):
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_unit = MagicMock()
            mock_unit.id = 99
            mock_unit.unit_name = "新单位"
            mock_unit_cls.return_value = mock_unit
            resp = client.post("/api/purchase_units", json={"name": "新单位"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == 99

    def test_compat_purchase_units_update_with_contact_fields(self) -> None:
        """更新联系人字段。"""
        client = _ai_assistant_client()
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.models.PurchaseUnit") as mock_unit_cls,
        ):
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_unit = MagicMock()
            mock_unit.id = 1
            mock_unit.unit_name = "old"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_unit
            resp = client.put(
                "/api/purchase_units/1",
                json={
                    "unit_name": "new-name",
                    "contact_person": "张三",
                    "contact_phone": "13800000000",
                    "address": "新地址",
                },
            )
        assert resp.status_code == 200
        assert mock_unit.unit_name == "new-name"
        assert mock_unit.contact_person == "张三"

    def test_compat_purchase_units_update_empty_unit_name_keeps_old(self) -> None:
        """更新时 unit_name 为空字符串 → 保持原值。"""
        client = _ai_assistant_client()
        with (
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.models.PurchaseUnit") as mock_unit_cls,
        ):
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_unit = MagicMock()
            mock_unit.id = 1
            mock_unit.unit_name = "原单位"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_unit
            resp = client.put(
                "/api/purchase_units/1",
                json={"unit_name": "   "},  # 空白字符串
            )
        assert resp.status_code == 200
        # unit_name 不应被修改
        assert mock_unit.unit_name == "原单位"

    def test_compat_print_shipment_file_with_printer_name(self) -> None:
        """打印文件时使用 printer_name 字段。"""
        client = _ai_assistant_client()
        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/app"),
            patch("os.path.exists", return_value=True),
            patch.object(ai_assistant, "_printer_svc") as mock_svc_get,
        ):
            mock_svc = MagicMock()
            mock_svc.print_document.return_value = {"success": True, "printed": 1}
            mock_svc_get.return_value = mock_svc
            resp = client.post(
                "/api/print/foo.docx",
                json={"printer_name": "HP-LaserJet"},
            )
        assert resp.status_code == 200
        call_kwargs = mock_svc.print_document.call_args.kwargs
        assert call_kwargs["printer_name"] == "HP-LaserJet"

    def test_compat_print_shipment_file_with_printer_field_fallback(self) -> None:
        """printer 字段作为 printer_name 的回退。"""
        client = _ai_assistant_client()
        with (
            patch("app.utils.path_utils.get_app_data_dir", return_value="/tmp/app"),
            patch("os.path.exists", return_value=True),
            patch.object(ai_assistant, "_printer_svc") as mock_svc_get,
        ):
            mock_svc = MagicMock()
            mock_svc.print_document.return_value = {"success": True}
            mock_svc_get.return_value = mock_svc
            resp = client.post(
                "/api/print/foo.docx",
                json={"printer": "Canon-123"},  # 使用 printer 字段
            )
        assert resp.status_code == 200
        call_kwargs = mock_svc.print_document.call_args.kwargs
        assert call_kwargs["printer_name"] == "Canon-123"

    def test_compat_print_single_label_quantity_above_100_defaults_to_1(self) -> None:
        """quantity > 100 → 默认为 1。

        注意：``/api/print/single_label`` 路由被先注册的 ``/api/print/{filename:path}``
        路径参数路由遮蔽，无法通过 HTTP 触发；这里直接调用函数以覆盖其函数体。
        """
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_svc_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True}
            mock_svc_get.return_value = mock_svc
            resp = ai_assistant.compat_print_single_label(
                {"model_number": "", "quantity": 200}
            )
        assert resp.status_code == 200
        call_kwargs = mock_svc.print_single_label.call_args.kwargs
        assert call_kwargs["quantity"] == 1

    def test_compat_print_single_label_quantity_negative_defaults_to_1(self) -> None:
        """quantity < 1 → 默认为 1。

        注意：``/api/print/single_label`` 路由被先注册的 ``/api/print/{filename:path}``
        路径参数路由遮蔽，无法通过 HTTP 触发；这里直接调用函数以覆盖其函数体。
        """
        with patch(
            "app.application.print_app_service.get_print_application_service"
        ) as mock_svc_get:
            mock_svc = MagicMock()
            mock_svc.print_single_label.return_value = {"success": True}
            mock_svc_get.return_value = mock_svc
            resp = ai_assistant.compat_print_single_label(
                {"model_number": "", "quantity": -5}
            )
        assert resp.status_code == 200
        call_kwargs = mock_svc.print_single_label.call_args.kwargs
        assert call_kwargs["quantity"] == 1

    def test_compat_tts_with_speaker_and_voice_params(self) -> None:
        """TTS 携带 speakerId / voice / rate / pitch 参数。"""
        client = _ai_assistant_client()
        with (
            patch(
                "app.application.facades.tts_facade.trigger_common_tts_warmup"
            ) as mock_warmup,
            patch(
                "app.application.facades.tts_facade.synthesize_to_data_uri"
            ) as mock_synth,
        ):
            mock_synth.return_value = {
                "audioBase64": "abc",
                "voice": "zh-CN-XiaoxiaoNeural",
                "lang": "zh",
            }
            resp = client.post(
                "/api/tts",
                json={
                    "text": "你好",
                    "speakerId": "spk-1",
                    "voice": "zh-CN-XiaoxiaoNeural",
                    "rate": 1.0,
                    "pitch": 1.0,
                    "lang": "ZH",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["audioBase64"] == "abc"
        assert body["data"]["speakerId"] == "spk-1"
        # lang 应被 lower()
        call_kwargs = mock_synth.call_args.kwargs
        assert call_kwargs["lang"] == "zh"


# ===========================================================================
# 2. industry_baseline — build_industry_baseline_plan 复杂分支
# ===========================================================================


class TestIndustryBaselinePlanBranches:
    """补充 build_industry_baseline_plan 未覆盖分支。"""

    def test_plan_with_industry_package_mod_id_returns_package_info(self) -> None:
        """industry_packages 中有 mod_id → 返回 industry_package 信息。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"涂料": {"industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {
                        "涂料": {"mod_id": "pkg-1", "product_name": "涂料包"}
                    },
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("涂料", installed_mod_ids=[])
        assert plan["industry_package"] == {"mod_id": "pkg-1", "product_name": "涂料包"}

    def test_plan_with_no_industry_package_mod_id_returns_none(self) -> None:
        """industry_packages 中无 mod_id → industry_package 为 None。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {"industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        assert plan["industry_package"] is None

    def test_plan_full_stack_ready_when_all_installed(self) -> None:
        """所有必需 mod 已安装 → full_stack_ready=True。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {},
                    "industries": {
                        "通用": {
                            "host_mod_ids": ["host-1"],
                            "industry_mod_ids": ["ind-1"],
                        }
                    },
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=["custom-1"],
            ),
        ):
            plan = build_industry_baseline_plan(
                "通用",
                installed_mod_ids=["core-1", "host-1", "ind-1", "custom-1"],
            )
        assert plan["host_baseline_ready"] is True
        assert plan["industry_mod_ready"] is True
        assert plan["account_custom_ready"] is True
        assert plan["full_stack_ready"] is True

    def test_plan_full_stack_not_ready_when_missing_industry(self) -> None:
        """缺少 industry mod → full_stack_ready=False。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {},
                    "industries": {
                        "通用": {
                            "host_mod_ids": ["host-1"],
                            "industry_mod_ids": ["ind-1"],
                        }
                    },
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan(
                "通用",
                installed_mod_ids=["core-1", "host-1"],  # 缺 ind-1
            )
        assert plan["industry_mod_ready"] is False
        assert plan["full_stack_ready"] is False
        assert "ind-1" in plan["missing_industry_mod_ids"]

    def test_plan_account_custom_ready_when_skip_gate(self) -> None:
        """skip_account_custom_gate=True → account_custom_ready=True 即使缺失。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {"industry_mod_ids": ["ind-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=["custom-1"],
            ),
        ):
            plan = build_industry_baseline_plan(
                "通用",
                installed_mod_ids=[],
                skip_account_custom_gate=True,
            )
        assert plan["account_custom_ready"] is True
        # 但 missing_account_custom_mod_ids 仍应列出
        assert "custom-1" in plan["missing_account_custom_mod_ids"]

    def test_plan_with_employee_extension_ids(self) -> None:
        """有 account_custom_base 时，employee_extension_ids 应被合并。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {
                        "通用": {
                            "industry_mod_ids": ["ind-1"],
                            "custom_employee_extension_mod_ids": ["emp-1", "emp-2"],
                        }
                    },
                    "industry_packages": {},
                    "custom_employee_extension_mod_ids": ["emp-3"],
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=["custom-1"],
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        # employee_extension_ids 应包含 doc 和 row 级别的
        assert "emp-1" in plan["custom_employee_extension_mod_ids"]
        assert "emp-2" in plan["custom_employee_extension_mod_ids"]
        assert "emp-3" in plan["custom_employee_extension_mod_ids"]

    def test_plan_no_employee_extension_when_no_account_custom(self) -> None:
        """无 account_custom_base 时，employee_extension_ids 应为空。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {
                        "通用": {
                            "industry_mod_ids": ["ind-1"],
                            "custom_employee_extension_mod_ids": ["emp-1"],
                        }
                    },
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],  # 无 account_custom_base
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        assert plan["custom_employee_extension_mod_ids"] == []

    def test_plan_optional_group_filtered_when_empty(self) -> None:
        """optional_ids 为空时，optional group 应被过滤掉（groups = [g for g if items]）。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {},
                    "industries": {"通用": {"host_mod_ids": ["host-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan(
                "通用",
                installed_mod_ids=["core-1", "host-1"],
            )
        group_ids = [g["id"] for g in plan["groups"]]
        # optional group 无 items → 不应出现
        assert "optional" not in group_ids

    def test_plan_industry_group_not_added_when_no_industry_mods(self) -> None:
        """无 industry_mod_ids 时，industry_package group 不应被添加。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": ["core-1"],
                    "mod_labels": {},
                    "industries": {"通用": {"host_mod_ids": ["host-1"]}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        group_ids = [g["id"] for g in plan["groups"]]
        assert "industry_package" not in group_ids

    def test_plan_summary_from_row(self) -> None:
        """summary 应从 row 中读取。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {"通用": {"summary": "  通用行业  "}},
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("通用", installed_mod_ids=[])
        assert plan["summary"] == "通用行业"

    def test_plan_unknown_industry_falls_back_to_default_row(self) -> None:
        """未知 industry_id → row 回退到通用，但 industry_key 保留原值。"""
        with (
            patch(
                "app.mod_sdk.industry_baseline.load_industry_baseline_document",
                return_value={
                    "schema_version": 1,
                    "core_mod_ids": [],
                    "mod_labels": {},
                    "industries": {
                        "通用": {"host_mod_ids": ["host-1"]},
                        "涂料": {"host_mod_ids": ["paint-1"]},
                    },
                    "industry_packages": {},
                },
            ),
            patch(
                "app.mod_sdk.customer_delivery.account_custom_mod_ids_for_industry",
                return_value=[],
            ),
        ):
            plan = build_industry_baseline_plan("未知行业", installed_mod_ids=[])
        # industry_key 保留原值（非空时不回退到通用）
        assert plan["industry_id"] == "未知行业"
        # 但 row 回退到通用 → required_ids 应包含 host-1
        assert "host-1" in plan["required_mod_ids"]

    def test_filter_onboarding_catalog_demoted_pkg_added_to_preview(self) -> None:
        """非 entitlement 的 open pkg 应被降级到 preview。"""
        catalog = {
            "open_packages": [
                {"industry_id": "open-1"},
                {"industry_id": "open-2"},
            ],
            "preview_packages": [{"industry_id": "preview-1"}],
        }
        # 假设 open-1 entitlement 通过，open-2 不通过
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            side_effect=lambda iid, entitled: iid == "open-1",
        ):
            result = filter_onboarding_catalog_for_entitlements(catalog, set())
        open_ids = [p["industry_id"] for p in result["open_packages"]]
        preview_ids = [p["industry_id"] for p in result["preview_packages"]]
        assert "open-1" in open_ids
        assert "open-2" not in open_ids
        assert "open-2" in preview_ids

    def test_filter_onboarding_catalog_demoted_already_in_preview_not_duplicated(
        self,
    ) -> None:
        """已降级的 pkg 已在 preview 中 → 不重复添加。"""
        catalog = {
            "open_packages": [{"industry_id": "shared"}],
            "preview_packages": [{"industry_id": "shared"}],
        }
        with patch(
            "app.mod_sdk.industry_baseline.industry_entitled_for_client_mods",
            return_value=False,
        ):
            result = filter_onboarding_catalog_for_entitlements(catalog, set())
        preview_ids = [p["industry_id"] for p in result["preview_packages"]]
        # 不应重复
        assert preview_ids.count("shared") == 1


# ===========================================================================
# 3. planner_tools — execute_planner_workflow_tool 多分支
# ===========================================================================


class TestPlannerToolsBranches:
    """补充 planner_tools 未覆盖分支。"""

    def test_execute_planner_workflow_tool_native_hit_returns_native(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """native_raw 不为 None → 直接返回 native。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with patch(
            "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
            return_value=("native-result", "native-mod"),
        ) as mock_native:
            result = execute_planner_workflow_tool("tool1", {"arg": 1}, "/ws")
        assert result == "native-result"
        mock_native.assert_called_once()

    def test_execute_planner_workflow_tool_employee_pack_hit_returns_emp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """native 为 None，employee pack 返回非 None → 返回 emp。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with (
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value="emp-result",
            ) as mock_emp,
        ):
            result = execute_planner_workflow_tool("tool1", {"arg": 1}, "/ws")
        assert result == "emp-result"
        mock_emp.assert_called_once()

    def test_execute_planner_workflow_tool_employee_pack_raises_falls_to_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """employee pack 抛出 RECOVERABLE_ERRORS → 回退到 host workflow。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with (
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                side_effect=RuntimeError("emp boom"),
            ),
            patch(
                "app.application.tools.workflow.execute_workflow_tool",
                return_value="host-result",
            ) as mock_host,
        ):
            result = execute_planner_workflow_tool("tool1", {"arg": 1}, "/ws")
        assert result == "host-result"
        mock_host.assert_called_once()

    def test_execute_planner_workflow_tool_falls_to_host_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """native 和 employee 都为 None → 走 host workflow。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with (
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
            ),
            patch(
                "app.application.tools.workflow.execute_workflow_tool",
                return_value="host-result",
            ) as mock_host,
        ):
            result = execute_planner_workflow_tool("tool1", {"arg": 1}, "/ws")
        assert result == "host-result"
        mock_host.assert_called_once()

    def test_execute_planner_tool_from_body_with_db_write_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """body 中包含 db_write_token → 透传到 executor。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", "/custom/ws")

        with patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value='{"success": true}',
        ) as mock_exec:
            result = execute_planner_tool_from_body(
                {
                    "tool_name": "tool1",
                    "arguments": {"a": 1},
                    "db_write_token": "tok-123",
                }
            )
        assert result["success"] is True
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["db_write_token"] == "tok-123"

    def test_execute_planner_tool_from_body_args_from_args_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """args 字段作为 arguments 的回退。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value='{"success": true}',
        ) as mock_exec:
            result = execute_planner_tool_from_body(
                {
                    "name": "tool1",
                    "args": {"b": 2},  # 使用 args 而非 arguments
                }
            )
        assert result["success"] is True
        # 验证 args 被透传
        call_args = mock_exec.call_args.args
        assert call_args[1] == {"b": 2}

    def test_execute_planner_tool_from_body_mod_native_with_source_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """result JSON 含 source: mod:xxx → execution_path=mod_native。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value='{"source": "mod:custom-mod", "data": "x"}',
        ):
            result = execute_planner_tool_from_body({"tool_name": "tool1"})
        assert result["execution_path"] == "mod_native"
        assert result["mod_id"] == "custom-mod"
        assert result["delegate"] is None

    def test_execute_planner_tool_from_body_mod_native_no_colon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """source: mod: 无后续字符 → mod_id 为 None（split 后为空字符串）。

        注意：source 必须以 "mod:" 开头才进入 mod_native 分支。
        "mod:" split(":", 1)[1] = "" → handler_mod = ""（falsy 但非 None）。
        """
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with patch(
            "app.application.tools.workflow.execute_workflow_tool",
            return_value='{"source": "mod:"}',  # mod: 后无字符
        ):
            result = execute_planner_tool_from_body({"tool_name": "tool1"})
        assert result["execution_path"] == "mod_native"
        # split(":", 1)[1] = "" → if ":" in src 为 True，handler_mod = ""
        assert result["mod_id"] == ""

    def test_resolve_planner_tool_executor_via_mod_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XCAGI_PLANNER_TOOLS_VIA_MOD=1 → 返回 execute_planner_workflow_tool。"""
        monkeypatch.setenv("XCAGI_PLANNER_TOOLS_VIA_MOD", "1")
        executor = resolve_planner_tool_executor()
        assert executor is execute_planner_workflow_tool

    def test_resolve_planner_tool_executor_via_host_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """XCAGI_DISABLE_PLANNER_MOD_TOOLS=1 → 返回 host workflow。"""
        monkeypatch.setenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", "1")
        from app.application.tools.workflow import execute_workflow_tool

        executor = resolve_planner_tool_executor()
        assert executor is execute_workflow_tool

    def test_list_planner_tools_registry_detail_native_with_tool_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """native_summary 有 tool_names → note 包含里程碑 F3。"""
        monkeypatch.delenv("XCAGI_DISABLE_PLANNER_MOD_TOOLS", raising=False)
        monkeypatch.delenv("XCAGI_PLANNER_TOOLS_VIA_MOD", raising=False)

        with (
            patch(
                "app.application.tools.workflow.get_workflow_tool_registry",
                return_value=[{"function": {"name": "t1"}}],
            ),
            patch(
                "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
                return_value=[],
            ),
            patch(
                "app.mod_sdk.planner_tools.is_planner_tools_via_mod_enabled",
                return_value=False,
            ),
            patch(
                "app.mod_sdk.planner_tools.load_planner_tools_config",
                return_value={"execution": {"mode": "auto"}},
            ),
            patch(
                "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
                return_value={"enabled": True, "tool_names": ["native-1"]},
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                return_value={"employee_pack_tools": []},
            ),
        ):
            detail = list_planner_tools_registry_detail()
        assert detail["success"] is True
        assert "里程碑 F3" in detail["note"]
        assert detail["execution_path"] == "mod_native"

    def test_list_planner_tools_registry_detail_via_mod_facade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """via_mod=True 且 native 未启用 → execution_path=mod_facade。"""
        monkeypatch.setenv("XCAGI_PLANNER_TOOLS_VIA_MOD", "1")

        with (
            patch(
                "app.application.tools.workflow.get_workflow_tool_registry",
                return_value=[],
            ),
            patch(
                "app.mod_sdk.planner_tools.load_mod_planner_tool_extensions",
                return_value=[],
            ),
            patch(
                "app.mod_sdk.planner_tools.load_planner_tools_config",
                return_value={},
            ),
            patch(
                "app.mod_sdk.planner_native_tools.list_native_planner_tools_summary",
                return_value={"enabled": False, "tool_names": []},
            ),
            patch(
                "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
                side_effect=RuntimeError("emp boom"),
            ),
        ):
            detail = list_planner_tools_registry_detail()
        assert detail["execution_via_mod_facade"] is True
        assert detail["execution_path"] == "mod_facade"
        assert detail["employee_planner"] == {}
        assert "里程碑 B" in detail["note"]


# ===========================================================================
# 4. shipment_domain_handlers — 异常路径补充
# ===========================================================================


class TestShipmentDomainHandlersBranches:
    """补充 shipment_domain_handlers 未覆盖分支。"""

    @pytest.mark.asyncio
    async def test_handle_shipment_created_core_returns_result_with_reply(
        self,
    ) -> None:
        """create_shipment 成功 → 调用 try_complete_command_reply。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event(
            {
                "shipment_id": "S1",
                "unit_name": "甲公司",
                "items": [{"name": "漆", "qty": 1}],
                "contact_person": "张三",
                "contact_phone": "13800000000",
            }
        )
        with (
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core"
            ) as mock_core_get,
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
            ) as mock_reply,
        ):
            mock_core = MagicMock()
            mock_core.create_shipment.return_value = {"success": True, "id": 1}
            mock_core_get.return_value = mock_core
            result = await handlers.handle_shipment_created(event)
        assert result["success"] is True
        mock_reply.assert_called_once()
        # 验证 reply 调用参数
        call_args = mock_reply.call_args.args
        assert call_args[0] is event
        assert call_args[1] == {"success": True, "id": 1}

    @pytest.mark.asyncio
    async def test_handle_shipment_created_empty_items_uses_default(
        self,
    ) -> None:
        """items 缺失 → 使用空列表。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "S1", "unit_name": "甲公司"})
        with (
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core"
            ) as mock_core_get,
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
            ),
        ):
            mock_core = MagicMock()
            mock_core.create_shipment.return_value = {"success": True}
            mock_core_get.return_value = mock_core
            await handlers.handle_shipment_created(event)
        call_kwargs = mock_core.create_shipment.call_args.kwargs
        assert call_kwargs["items_data"] == []
        assert call_kwargs["contact_person"] == ""
        assert call_kwargs["contact_phone"] == ""

    @pytest.mark.asyncio
    async def test_handle_printed_invalid_shipment_id_raises_propagates(
        self,
    ) -> None:
        """shipment_id 无法转 int → ValueError 抛出。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "not-a-number"})
        with (
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core"
            ),
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
            ) as mock_reply,
        ):
            with pytest.raises(ValueError):
                await handlers.handle_printed(event)
        # 错误时应调用 reply with error
        mock_reply.assert_called_once()
        call_args = mock_reply.call_args.args
        assert call_args[0] is event
        assert call_args[1] is None

    @pytest.mark.asyncio
    async def test_handle_cancelled_core_raises_propagates_with_reply(
        self,
    ) -> None:
        """cancel_shipment 抛出 → reply with error 并重新抛出。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "123"})
        with (
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core"
            ) as mock_core_get,
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
            ) as mock_reply,
        ):
            mock_core = MagicMock()
            mock_core.cancel_shipment.side_effect = RuntimeError("cancel failed")
            mock_core_get.return_value = mock_core
            with pytest.raises(RuntimeError, match="cancel failed"):
                await handlers.handle_cancelled(event)
        mock_reply.assert_called_once()
        call_kwargs = mock_reply.call_args.kwargs
        assert "error" in call_kwargs

    @pytest.mark.asyncio
    async def test_handle_deleted_success_with_reply(self) -> None:
        """delete_shipment 成功 → 调用 reply。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "456"})
        with (
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.get_shipment_application_service_core"
            ) as mock_core_get,
            patch(
                "app.neuro_bus.domains.shipment_domain_handlers.try_complete_command_reply"
            ) as mock_reply,
        ):
            mock_core = MagicMock()
            mock_core.delete_shipment.return_value = {"success": True}
            mock_core_get.return_value = mock_core
            result = await handlers.handle_deleted(event)
        assert result["success"] is True
        mock_reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_item_added_with_price_and_qty(self) -> None:
        """item_added 计算 amount_delta。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event(
            {
                "shipment_id": "S1",
                "product_id": "P1",
                "unit_price": 10.5,
                "quantity": 3,
            }
        )
        result = await handlers.handle_item_added(event)
        assert result["success"] is True
        assert result["amount_delta"] == 31.5
        assert "item_logged" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_item_added_default_price_qty(self) -> None:
        """item_added 缺失 price/qty → 默认 0。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "S1", "product_id": "P1"})
        result = await handlers.handle_item_added(event)
        assert result["success"] is True
        assert result["amount_delta"] == 0

    @pytest.mark.asyncio
    async def test_handle_exported_with_record_count(self) -> None:
        """exported 含 record_count。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event(
            {"file_path": "/tmp/export.xlsx", "record_count": 100}
        )
        result = await handlers.handle_exported(event)
        assert result["success"] is True
        assert "export_logged" in result["actions"]
        assert "export_stats_updated" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_inventory_deducted_with_items(self) -> None:
        """inventory_deducted 含 items 列表。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event(
            {
                "shipment_id": "S1",
                "items": [{"product_id": "P1", "qty": 2}],
            }
        )
        result = await handlers.handle_inventory_deducted(event)
        assert result["success"] is True
        assert "inventory_deducted" in result["actions"]
        assert "inventory_movement_logged" in result["actions"]
        assert "alert_checked" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_inventory_deducted_empty_items(self) -> None:
        """inventory_deducted items 为空。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "S1", "items": []})
        result = await handlers.handle_inventory_deducted(event)
        assert result["success"] is True
        assert "inventory_deducted" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_inventory_deducted_missing_items_key(self) -> None:
        """inventory_deducted 缺失 items key。"""
        handlers = ShipmentDomainHandlers()
        event = _make_event({"shipment_id": "S1"})
        result = await handlers.handle_inventory_deducted(event)
        assert result["success"] is True

    def test_shipment_handlers_bus_lazy_init(self) -> None:
        """bus 属性延迟初始化。"""
        handlers = ShipmentDomainHandlers()
        assert handlers._bus is None
        mock_bus = MagicMock()
        with patch(
            "app.neuro_bus.domains.shipment_domain_handlers.get_neuro_bus",
            return_value=mock_bus,
        ):
            assert handlers.bus is mock_bus
        # 第二次访问使用缓存
        assert handlers.bus is mock_bus

    def test_get_shipment_domain_handlers_singleton(self) -> None:
        """get_shipment_domain_handlers 返回单例。"""
        import app.neuro_bus.domains.shipment_domain_handlers as mod

        mod._shipment_handlers = None
        a = get_shipment_domain_handlers()
        b = get_shipment_domain_handlers()
        assert a is b
        mod._shipment_handlers = None

    def test_register_shipment_domain_handlers_subscribes_all(self) -> None:
        """register_shipment_domain_handlers 注册所有事件。"""
        mock_bus = MagicMock()
        register_shipment_domain_handlers(mock_bus)
        assert mock_bus.subscribe.call_count == 7
        events = [call.args[0] for call in mock_bus.subscribe.call_args_list]
        assert set(events) == {
            "shipment.created",
            "shipment.item_added",
            "shipment.printed",
            "shipment.cancelled",
            "shipment.deleted",
            "shipment.exported",
            "shipment.inventory_deducted",
        }
        import app.neuro_bus.domains.shipment_domain_handlers as mod

        mod._shipment_handlers = None


# ===========================================================================
# 5. product_domain_handlers — 异常路径补充
# ===========================================================================


class TestProductDomainHandlersBranches:
    """补充 product_domain_handlers 未覆盖分支。"""

    @pytest.mark.asyncio
    async def test_handle_product_created_with_bus_publish_success(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event(
            {"product_id": "P1", "unit_name": "甲公司", "product_name": "漆"}
        )
        result = await handlers.handle_product_created(event)
        assert result["success"] is True
        assert "cache_warmup_triggered" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_product_updated_price_change_triggers_event(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event(
            {
                "product_id": "P1",
                "changed_fields": ["price"],
                "old_price": 100,
                "price": 150,
            }
        )
        result = await handlers.handle_product_updated(event)
        assert result["success"] is True
        assert "price_change_event_triggered" in result["actions"]
        # 应发布 2 个事件
        assert mock_bus.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_handle_product_updated_no_price_change(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event(
            {"product_id": "P1", "changed_fields": ["name"]}
        )
        result = await handlers.handle_product_updated(event)
        assert result["success"] is True
        assert "price_change_event_triggered" not in result["actions"]
        # 只发布缓存失效事件
        assert mock_bus.publish.call_count == 1

    @pytest.mark.asyncio
    async def test_handle_product_deleted_success(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event({"product_id": "P1", "unit_name": "甲公司"})
        result = await handlers.handle_product_deleted(event)
        assert result["success"] is True
        assert "deletion_audit_logged" in result["actions"]
        assert "cache_invalidated" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_product_imported_with_count(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event({"unit_name": "甲公司", "count": 50})
        result = await handlers.handle_product_imported(event)
        assert result["success"] is True
        assert result["imported_count"] == 50
        assert "bulk_cache_invalidated" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_price_changed_with_delta(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event(
            {"product_id": "P1", "old_price": 100, "new_price": 150}
        )
        result = await handlers.handle_price_changed(event)
        assert result["success"] is True
        assert result["price_delta"] == 50
        assert "price_history_recorded" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_cache_invalidated_with_product_id(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event({"product_id": "P1", "reason": "manual"})
        result = await handlers.handle_cache_invalidated(event)
        assert result["success"] is True
        assert result["invalidated"]["product_id"] == "P1"
        assert "cache_cleared" in result["actions"]

    @pytest.mark.asyncio
    async def test_handle_cache_invalidated_with_unit_name_only(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event({"unit_name": "甲公司"})
        result = await handlers.handle_cache_invalidated(event)
        assert result["success"] is True
        assert result["invalidated"]["unit_name"] == "甲公司"

    @pytest.mark.asyncio
    async def test_handle_cache_invalidated_empty_payload(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        event = _make_event({})
        result = await handlers.handle_cache_invalidated(event)
        assert result["success"] is True
        assert result["invalidated"] == {}

    @pytest.mark.asyncio
    async def test_handle_product_created_publish_raises_recoverable(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        mock_bus.publish.side_effect = RuntimeError("bus down")
        event = _make_event({"product_id": "P1", "unit_name": "甲公司"})
        result = await handlers.handle_product_created(event)
        assert result["success"] is False
        assert "bus down" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_product_updated_publish_raises_recoverable(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        mock_bus.publish.side_effect = LookupError("lookup failed")
        event = _make_event({"product_id": "P1", "changed_fields": ["name"]})
        result = await handlers.handle_product_updated(event)
        assert result["success"] is False
        assert "lookup failed" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_product_deleted_publish_raises_recoverable(
        self,
        mock_bus: MagicMock,
        patch_product_events: None,
    ) -> None:
        handlers = ProductDomainHandlers()
        handlers._bus = mock_bus
        mock_bus.publish.side_effect = ValueError("invalid")
        event = _make_event({"product_id": "P1"})
        result = await handlers.handle_product_deleted(event)
        assert result["success"] is False
        assert "invalid" in result["error"]

    def test_product_handlers_bus_lazy_init(self) -> None:
        """bus 属性延迟初始化。"""
        handlers = ProductDomainHandlers()
        assert handlers._bus is None
        mock_bus = MagicMock()
        with patch(
            "app.neuro_bus.domains.product_domain_handlers.get_neuro_bus",
            return_value=mock_bus,
        ):
            assert handlers.bus is mock_bus
        assert handlers.bus is mock_bus

    def test_get_product_domain_handlers_singleton(self) -> None:
        import app.neuro_bus.domains.product_domain_handlers as mod

        mod._product_handlers = None
        a = get_product_domain_handlers()
        b = get_product_domain_handlers()
        assert a is b
        mod._product_handlers = None

    def test_register_product_domain_handlers_subscribes_all(self) -> None:
        mock_bus = MagicMock()
        register_product_domain_handlers(mock_bus)
        assert mock_bus.subscribe.call_count == 6
        events = [call.args[0] for call in mock_bus.subscribe.call_args_list]
        assert set(events) == {
            "product.created",
            "product.updated",
            "product.deleted",
            "product.imported",
            "product.price_changed",
            "product.cache_invalidated",
        }
        import app.neuro_bus.domains.product_domain_handlers as mod

        mod._product_handlers = None


# ===========================================================================
# 6. employee_runtime/agent.py — run() 多分支
# ===========================================================================


class TestEmployeeAgentBranches:
    """补充 EmployeeAgent.run() 未覆盖分支。"""

    def test_run_with_workspace_root_in_payload_not_overwritten(self) -> None:
        """payload 已有 workspace_root → 不被参数覆盖。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["direct_python"],
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ) as mock_actions,
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = MemoryContext()
            mock_mm.remember.return_value = None

            # payload 已有 workspace_root
            agent.run(
                "task",
                input_data={"file_path": "/tmp/f.txt", "workspace_root": "/payload-ws"},
                workspace_root="/param-ws",
            )
        # 验证 payload 中的 workspace_root 不被覆盖
        actions_call = mock_actions.call_args
        # workspace_root 参数应传给 _actions_fhd
        assert actions_call.args[5] == "/payload-ws"

    def test_run_direct_python_no_file_path_uses_cognition(self) -> None:
        """handler_list=['direct_python'] 但无 file_path → 走 cognition 路径。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        reasoning = {"reasoning": "thought", "input": {}}
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["direct_python"],  # direct_python 但无 file_path
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._memory_light",
                return_value={"session": {}},
            ) as mock_memory,
            patch(
                "app.application.employee_runtime.agent._ex._cognition_fhd",
                return_value=reasoning,
            ) as mock_cog,
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = MemoryContext()
            mock_mm.remember.return_value = None

            out = agent.run("task", input_data={})  # 无 file_path
        assert out["success"] is True
        # 应调用 cognition
        mock_cog.assert_called_once()
        mock_memory.assert_called_once()

    def test_run_cognition_error_with_direct_python_does_not_fail(self) -> None:
        """cognition 出错但 handler_list=['direct_python'] → 不走 cognition_failed 路径。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        reasoning_err = {"reasoning": "", "error": "llm timeout", "input": {}}
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["direct_python"],  # direct_python → 不走 failed 路径
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._memory_light",
                return_value={"session": {}},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._cognition_fhd",
                return_value=reasoning_err,
            ),
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = MemoryContext()
            mock_mm.remember.return_value = None

            out = agent.run("task", input_data={})
        # direct_python + cognition error → 不返回 cognition_failed
        assert out["success"] is True

    def test_run_upstream_collaboration_skipped_in_result(self) -> None:
        """upstream 返回 skipped → collaboration_upstream 为 None。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        upstream = {"skipped": True, "node_outputs": None}
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["echo"],
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch.object(
                EmployeeAgent,
                "_run_upstream_collaboration",
                return_value=upstream,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._memory_light",
                return_value={"session": {}},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._cognition_fhd",
                return_value={"reasoning": "t", "input": {}},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = MemoryContext()
            mock_mm.remember.return_value = None

            out = agent.run("task", input_data={})
        # upstream skipped → collaboration_upstream 为 None
        assert out["collaboration_upstream"] is None

    def test_run_upstream_collaboration_no_node_outputs_not_injected(self) -> None:
        """upstream 无 node_outputs → 不注入 payload。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        upstream = {"plan_id": "p1", "success": True}  # 无 node_outputs
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["echo"],
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch.object(
                EmployeeAgent,
                "_run_upstream_collaboration",
                return_value=upstream,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._memory_light",
                return_value={"session": {}},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._cognition_fhd",
                return_value={"reasoning": "t", "input": {}},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = MemoryContext()
            mock_mm.remember.return_value = None

            out = agent.run("task", input_data={})
        # upstream 无 node_outputs → collaboration_upstream 仍为 upstream（因为 not skipped）
        assert out["collaboration_upstream"] == upstream

    def test_run_memory_used_true_when_mem_ctx_has_content(self) -> None:
        """mem_ctx 有内容 → memory_used=True。"""
        agent = EmployeeAgent("emp-1")
        pack = {
            "pack_id": "emp-1",
            "version": "1.0.0",
            "manifest": {},
            "pack_dir": "/tmp/emp-1",
        }
        gate = {"ok": True, "risk_level": "low", "reason": "low"}
        mem_ctx = MemoryContext(long_term_prompt="记忆内容")
        with (
            patch(
                "app.application.employee_runtime.agent.load_employee_pack_from_disk",
                return_value=pack,
            ),
            patch(
                "app.application.employee_runtime.agent.parse_employee_config_v2",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._normalize_actions_cfg",
                return_value={},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handler_list",
                return_value=["direct_python"],
            ),
            patch(
                "app.application.employee_runtime.agent.gate_action_or_block",
                return_value=gate,
            ),
            patch(
                "app.application.employee_runtime.agent.MemoryScope.from_config"
            ) as mock_scope_cls,
            patch(
                "app.application.employee_runtime.agent.EmployeeMemoryManager"
            ) as mock_mm_cls,
            patch(
                "app.application.employee_runtime.agent.build_employee_context"
            ),
            patch.object(
                EmployeeAgent, "_perceive", return_value={"normalized_input": {}}
            ),
            patch(
                "app.application.employee_runtime.agent._ex._actions_fhd",
                return_value={"outputs": []},
            ),
            patch(
                "app.application.employee_runtime.agent._ex._handlers_execution_ok",
                return_value=True,
            ),
            patch(
                "app.application.employee_runtime.metrics.record_employee_run"
            ),
        ):
            mock_scope = MagicMock()
            mock_scope_cls.return_value = mock_scope
            mock_mm = MagicMock()
            mock_mm_cls.return_value = mock_mm
            mock_mm.recall.return_value = mem_ctx
            mock_mm.remember.return_value = None

            out = agent.run(
                "task",
                input_data={"file_path": "/tmp/f.txt"},
            )
        assert out["memory_used"] is True

    def test_run_recoverable_error_returns_error_result(self) -> None:
        """run 中抛出 RECOVERABLE_ERRORS → 返回 error 结果。"""
        agent = EmployeeAgent("emp-1")
        with patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            side_effect=RuntimeError("disk io"),
        ):
            out = agent.run("task", input_data={})
        assert out["success"] is False
        assert "disk io" in out["error"]
        assert out["employee_id"] == "emp-1"
        assert "duration_ms" in out
        assert "executed_at" in out

    def test_run_value_error_returns_error_result(self) -> None:
        """run 中抛出 ValueError → 返回 error 结果。"""
        agent = EmployeeAgent("emp-1")
        with patch(
            "app.application.employee_runtime.agent.load_employee_pack_from_disk",
            side_effect=ValueError("bad pack"),
        ):
            out = agent.run("task", input_data={})
        assert out["success"] is False
        assert "bad pack" in out["error"]

    def test_blocked_result_structure(self) -> None:
        """_blocked_result 返回结构正确。"""
        agent = EmployeeAgent("emp-1")
        pack = {"pack_id": "emp-1", "version": "1.0.0"}
        gate = {"ok": False, "reason": "blocked"}
        t0 = 0.0
        result = agent._blocked_result(pack, "task", ["echo"], gate, t0)
        assert result["success"] is False
        assert result["blocked_by_risk_gate"] is True
        assert result["result"]["summary"] == "blocked by risk middleware"
        assert result["result"]["risk_gate"] == gate
        assert result["pack"]["id"] == "emp-1"

    def test_cognition_failed_result_structure(self) -> None:
        """_cognition_failed_result 返回结构正确。"""
        agent = EmployeeAgent("emp-1")
        pack = {"pack_id": "emp-1", "version": "1.0.0"}
        reasoning = {"error": "llm timeout"}
        t0 = 0.0
        result = agent._cognition_failed_result(pack, "task", ["echo"], reasoning, t0)
        assert result["success"] is False
        assert result["result"]["summary"] == "cognition failed"
        assert result["result"]["cognition_error"] == "llm timeout"


# ===========================================================================
# 7. mod_entitlements — sync/restore/persist 边界
# ===========================================================================


class TestModEntitlementsBranches:
    """补充 mod_entitlements 未覆盖分支。"""

    def test_is_admin_account_session_true(self) -> None:
        """admin + market_is_admin → True。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="admin",
            entitled_client_mod_ids=set(),
            account_kind="admin",
            market_is_admin=True,
        )
        assert mod_entitlements.is_admin_account_session() is True

    def test_is_admin_account_session_false_when_not_admin_kind(self) -> None:
        """非 admin kind → False。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="user",
            entitled_client_mod_ids=set(),
            account_kind="enterprise",
            market_is_admin=True,
        )
        assert mod_entitlements.is_admin_account_session() is False

    def test_is_admin_account_session_false_when_not_admin_flag(self) -> None:
        """admin kind 但 market_is_admin=False → False。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="admin",
            entitled_client_mod_ids=set(),
            account_kind="admin",
            market_is_admin=False,
        )
        assert mod_entitlements.is_admin_account_session() is False

    def test_set_session_entitlements_empty_username(self) -> None:
        """空 username → 被清理为空字符串。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="",
            entitled_client_mod_ids={"m1"},
        )
        uid, uname = mod_entitlements.get_cached_market_identity()
        assert uid == 1
        assert uname == ""

    def test_set_session_entitlements_none_account_kind_defaults_enterprise(
        self,
    ) -> None:
        """account_kind=None → 默认 enterprise。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="u",
            entitled_client_mod_ids=set(),
            account_kind=None,
        )
        # 通过 is_admin_account_session 间接验证
        assert mod_entitlements.is_admin_account_session() is False

    def test_set_session_entitlements_empty_account_kind_defaults_enterprise(
        self,
    ) -> None:
        """account_kind="" → 默认 enterprise。"""
        mod_entitlements.set_session_entitlements(
            market_user_id=1,
            market_username="u",
            entitled_client_mod_ids=set(),
            account_kind="",
        )
        assert mod_entitlements.is_admin_account_session() is False

    @pytest.mark.asyncio
    async def test_sync_entitlements_for_session_inactive_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enterprise_mod_filter_active=False → 返回空 set。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: False,
        )
        result = await mod_entitlements.sync_entitlements_for_session("sid-1")
        assert result == set()

    @pytest.mark.asyncio
    async def test_sync_entitlements_for_session_empty_sid_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空 session_id → 返回空 set。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: True,
        )
        result = await mod_entitlements.sync_entitlements_for_session("")
        assert result == set()

    @pytest.mark.asyncio
    async def test_sync_entitlements_for_session_whitespace_sid_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空白 session_id → 返回空 set。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: True,
        )
        result = await mod_entitlements.sync_entitlements_for_session("   ")
        assert result == set()

    @pytest.mark.asyncio
    async def test_reload_enterprise_mods_after_login_inactive_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enterprise_mod_filter_active=False → 直接返回。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: False,
        )
        # 不应抛出异常
        await mod_entitlements.reload_enterprise_mods_after_login()

    @pytest.mark.asyncio
    async def test_sync_entitlements_from_request_inactive_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enterprise_mod_filter_active=False → 直接返回。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: False,
        )
        request = MagicMock()
        # 不应抛出异常
        await mod_entitlements.sync_entitlements_from_request(request)

    @pytest.mark.asyncio
    async def test_sync_entitlements_from_request_no_cookie(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无 cookie → 直接返回。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: True,
        )
        request = MagicMock()
        request.cookies = {}
        await mod_entitlements.sync_entitlements_from_request(request)

    def test_persist_entitlements_empty_session_id_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空 session_id → 直接返回。"""
        # 不应抛出异常
        mod_entitlements.persist_entitlements_to_session_row("", set())

    def test_persist_entitlements_whitespace_session_id_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空白 session_id → 直接返回。"""
        mod_entitlements.persist_entitlements_to_session_row("   ", set())

    def test_restore_entitlements_empty_session_id_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """空 session_id → 返回 False。"""
        assert mod_entitlements.restore_entitlements_from_session_row("") is False

    def test_restore_entitlements_inactive_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enterprise_mod_filter_active=False → 返回 False。"""
        monkeypatch.setattr(
            "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
            lambda: False,
        )
        assert mod_entitlements.restore_entitlements_from_session_row("sid") is False


# ===========================================================================
# 8. mods_routes — list_mods / get_mod_detail 边界
# ===========================================================================


def _build_mods_app() -> FastAPI:
    """构造一个仅挂载 mods_routes 的 FastAPI 子应用。"""
    from app.fastapi_routes import mods_routes

    mods_routes.router = None
    app = FastAPI()
    app.include_router(mods_routes.get_mods_router())
    return app


class TestModsRoutesBranches:
    """补充 mods_routes 未覆盖分支。"""

    def test_list_mods_with_all_param_returns_data(self) -> None:
        """?all=1 参数应正常返回。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._mods_scan_fingerprint.return_value = "fp-1"
        mock_mm.list_all_mods.return_value = [{"id": "m1", "name": "Mod1"}]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods", params={"all": "1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1

    def test_list_mods_trailing_slash_returns_data(self) -> None:
        """/api/mods/ 也应正常返回。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._mods_scan_fingerprint.return_value = "fp-1"
        mock_mm.list_all_mods.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_list_mods_etag_match_returns_304(self) -> None:
        """If-None-Match 匹配 → 返回 304。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._mods_scan_fingerprint.return_value = "fp-1"
        mock_mm.list_all_mods.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            # 第一次请求获取 etag
            resp1 = client.get("/api/mods")
            etag = resp1.headers.get("ETag", "").strip('"')
            # 第二次带 If-None-Match
            resp2 = client.get(
                "/api/mods", headers={"If-None-Match": etag}
            )
        assert resp2.status_code == 304

    def test_list_mods_etag_mismatch_returns_200(self) -> None:
        """If-None-Match 不匹配 → 返回 200。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._mods_scan_fingerprint.return_value = "fp-1"
        mock_mm.list_all_mods.return_value = []
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.get(
                "/api/mods", headers={"If-None-Match": "wrong-etag"}
            )
        assert resp.status_code == 200

    def test_list_mods_recoverable_error_returns_failure(self) -> None:
        """list_mods 抛出 RECOVERABLE_ERRORS → 返回 failure。"""
        app = _build_mods_app()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("mm boom"),
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_from_request",
                new=AsyncMock(),
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods")
        body = resp.json()
        assert body["success"] is False
        assert "mm boom" in body["error"]

    def test_loading_status_load_mismatch_when_scanned_but_not_loaded(self) -> None:
        """scanned > 0 但 mods_loaded=0 → load_mismatch=True。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._refresh_mods_root_if_needed.return_value = None
        mock_mod = MagicMock()
        mock_mod.id = "m1"
        mock_mod.primary = False
        mock_mm.scan_mods.return_value = [mock_mod]
        mock_mm.list_loaded_mods.return_value = []  # 未加载
        mock_mm._scan_manifest_errors = []
        mock_mm._blueprint_failures = []
        mock_mm._recent_load_failures = []
        mock_mm.mods_root = "/tmp/mods"
        mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
                side_effect=lambda ids: ids,
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/loading-status")
        body = resp.json()
        assert body["data"]["load_mismatch"] is True

    def test_loading_status_no_primary_mods_returns_none(self) -> None:
        """无 primary mod → primary_mod_id=None。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm._refresh_mods_root_if_needed.return_value = None
        mock_mod = MagicMock()
        mock_mod.id = "m1"
        mock_mod.primary = False
        mock_mm.scan_mods.return_value = [mock_mod]
        mock_mm.list_loaded_mods.return_value = []
        mock_mm._scan_manifest_errors = []
        mock_mm._blueprint_failures = []
        mock_mm._recent_load_failures = []
        mock_mm.mods_root = "/tmp/mods"
        mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
                side_effect=lambda ids: ids,
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/loading-status")
        body = resp.json()
        assert body["data"]["primary_mod_id"] is None
        assert body["data"]["primary_mod_count"] == 0

    def test_get_mod_detail_success(self) -> None:
        """get_mod_detail 成功返回。"""
        app = _build_mods_app()
        mock_mod = MagicMock()
        mock_mod.id = "m1"
        mock_mod.name = "Mod1"
        mock_mod.version = "1.0.0"
        mock_mod.author = "author"
        mock_mod.description = "desc"
        mock_mod.frontend_menu = []
        mock_mod.frontend_menu_overrides = {}
        mock_mod.comms_exports = []
        mock_mm = MagicMock()
        mock_mm.get_mod.return_value = mock_mod
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/m1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == "m1"
        assert body["data"]["name"] == "Mod1"

    def test_get_mod_detail_recoverable_error_returns_500(self) -> None:
        """get_mod_detail 抛出 RECOVERABLE_ERRORS → 500。"""
        app = _build_mods_app()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("mm boom"),
            ),
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/m1")
        assert resp.status_code == 500
        body = resp.json()
        assert body["success"] is False
        assert "mm boom" in body["error"]

    def test_uninstall_mod_success(self) -> None:
        """uninstall_mod 成功。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm.uninstall_mod.return_value = (True, "已卸载")
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
        ):
            client = TestClient(app)
            resp = client.delete("/api/mods/m1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == "m1"

    def test_uninstall_mod_recoverable_error_returns_500(self) -> None:
        """uninstall_mod 抛出 RECOVERABLE_ERRORS → 500。"""
        app = _build_mods_app()
        with (
            patch(
                "app.infrastructure.mods.mod_manager.is_mods_disabled",
                return_value=False,
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("uninstall boom"),
            ),
        ):
            client = TestClient(app)
            resp = client.delete("/api/mods/m1")
        assert resp.status_code == 500
        body = resp.json()
        assert body["success"] is False
        assert "uninstall boom" in body["message"]

    def test_employee_pack_config_preview_default_mods_root_import_error(
        self,
    ) -> None:
        """_default_mods_root 导入失败 → 返回 failure。

        通过 ``sys.modules`` 注入 ``None`` 强制 ``from ... import`` 抛出
        ``ImportError``（``RECOVERABLE_ERRORS`` 成员）。
        """
        import sys

        app = _build_mods_app()
        with patch.dict(
            sys.modules,
            {"app.infrastructure.mods.mod_manager": None},
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/employee-packs/p1/config-preview")
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_list_comms_endpoints_success(self) -> None:
        """list_comms_endpoints 成功。"""
        app = _build_mods_app()
        with patch(
            "app.infrastructure.mods.comms.get_mod_comms"
        ) as mock_get_comms:
            mock_comms = MagicMock()
            mock_comms.list_endpoints.return_value = [{"id": "ep1"}]
            mock_get_comms.return_value = mock_comms
            client = TestClient(app)
            resp = client.get("/api/mods/comms/endpoints")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1

    def test_list_routes_success(self) -> None:
        """list_routes 成功。"""
        app = _build_mods_app()
        mock_mm = MagicMock()
        mock_mm.get_routes.return_value = [{"path": "/api/x"}]
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ):
            client = TestClient(app)
            resp = client.get("/api/mods/routes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
