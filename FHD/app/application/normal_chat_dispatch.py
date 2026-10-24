"""Public composition root for normal chat routing and deterministic tools."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from app.application.normal_chat import presentation, product_queries
from app.application.normal_chat.dispatch import dispatch_read, request_scope
from app.application.normal_chat.dispatch import request_tenant_id as _request_tenant_id
from app.application.normal_chat.product_queries import (
    resolve_tool_execution_profile as resolve_tool_execution_profile,
)
from app.application.normal_chat.query_execution import JsonObject, QueryExecutor, slot_reply
from app.application.normal_chat.routing import RoutingPorts, route_message
from app.application.normal_chat.sales_intent import (
    _as_closed_loop_number as _as_closed_loop_number,
)
from app.application.normal_chat.sales_intent import _decimal_prefix as _decimal_prefix
from app.application.normal_chat.sales_intent import _first_marker as _first_marker
from app.application.normal_chat.sales_intent import (
    _is_sales_closed_loop_write as _is_sales_closed_loop_write,
)
from app.application.normal_chat.sales_intent import (
    _parse_sales_write_request as _parse_sales_write_request,
)
from app.application.normal_chat.sales_intent import (
    _sales_write_idempotency_key as _sales_write_idempotency_key,
)
from app.application.product_query_context import is_full_product_list_phrase
from app.domain.services.conversation.chat_tool_intent import (
    is_negated_action_request as _is_negated_action_request,
)
from app.domain.services.conversation.chat_tool_intent import (
    looks_like_explicit_workflow_tool_intent,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _llm_route(text: str) -> JsonObject | None:
    from app.application.llm_intent_gate import llm_route_message

    return llm_route_message(text)


def _label_slots(text: str) -> JsonObject:
    from app.application.label_print_inputs import extract_label_print_slots

    return extract_label_print_slots(text)


def route_normal_mode_message(message: str) -> dict[str, Any]:
    from app.application.workflow.sql_execution_policy import database_maintenance_request
    from app.desktop_automation.service import desktop_action_request
    from app.services.intent_service import is_negation

    return route_message(
        message,
        RoutingPorts(
            database_maintenance_request,
            desktop_action_request,
            is_negation,
            _is_negated_action_request,
            _parse_sales_write_request,
            _label_slots,
            is_full_product_list_phrase,
            _llm_route,
            logger,
        ),
    )


def _query_products(keyword: str | None, per_page: int) -> JsonObject:
    from app.bootstrap import get_products_service

    return cast(
        JsonObject,
        get_products_service().get_products(
            unit_name=None,
            model_number=None,
            keyword=keyword,
            page=1,
            per_page=per_page,
        ),
    )


def build_product_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    return product_queries.product_window(route_result, _query_products, logger)


def run_workflow_products_query_normal_profile(
    user_message: str, node_params: dict[str, Any] | None = None, per_page: int = 20
) -> dict[str, Any]:
    return product_queries.workflow_products(
        user_message,
        node_params,
        per_page,
        route_message=route_normal_mode_message,
        query=_query_products,
        logger=logger,
    )


def run_normal_slot_shipment_preview(order_text: str) -> dict[str, Any]:
    def parse_order(text: str) -> JsonObject:
        from app.application.facades.tools_facade import _parse_order_text

        return cast(JsonObject, _parse_order_text(text))

    def build_preview(unit: str, products: list[JsonObject], text: str) -> JsonObject:
        from app.application.ai_chat_helpers import build_shipment_preview_response_dict

        return build_shipment_preview_response_dict(unit, products, text)

    return product_queries.shipment_preview(order_text, parse_order, build_preview)


def run_normal_slot_product_query_from_message(message: str) -> dict[str, Any]:
    return product_queries.product_from_message(
        message,
        route_normal_mode_message,
        build_product_query_response_dict,
    )


def _has_pending_workflow(user_id: str) -> bool:
    from app.application import get_ai_chat_app_service

    return user_id in get_ai_chat_app_service()._pending_workflows


def try_normal_slot_read_payload(
    message: str, *, request: Any | None = None, user_id: str | None = None
) -> dict[str, Any] | None:
    """Resolve the current public callbacks, then dispatch inside one request scope."""
    text = str(message or "").strip()
    return dispatch_read(
        text,
        request=request,
        user_id=user_id,
        route_message=route_normal_mode_message,
        has_pending_workflow=_has_pending_workflow,
        explicit_workflow_intent=looks_like_explicit_workflow_tool_intent,
        scope=lambda req: request_scope(req, _request_tenant_id),
        handlers={
            "clarify": build_clarify_response_dict,
            "customers_query": lambda route: build_customers_query_response_dict(
                route, request=request
            ),
            "product_query": build_product_query_response_dict,
            "inventory_alert": build_inventory_alert_response_dict,
            "inventory_count": build_inventory_count_response_dict,
            "mrp_production": build_mrp_production_response_dict,
            "aging_report": build_aging_report_response_dict,
            "label_print": build_label_print_response_dict,
            "materials_query": build_materials_query_response_dict,
            "shipment_records_query": build_shipment_records_query_response_dict,
            "purchase_query": lambda route: build_purchase_query_response_dict(route, message=text),
            "finance_query": build_finance_query_response_dict,
            "knowledge_query": build_knowledge_query_response_dict,
            "sales_query": build_sales_query_response_dict,
            "reports_query": lambda route: build_reports_query_response_dict(route, message=text),
            "replenishment_suggest": build_replenishment_suggest_response_dict,
        },
        logger=logger,
    )


def _keyword(route: JsonObject) -> str:
    return str((route.get("slots") or {}).get("keyword") or "").strip()


def build_customers_query_response_dict(
    route_result: dict[str, Any], *, request: Any | None = None
) -> dict[str, Any] | None:
    if route_result.get("intent") != "customers_query":
        return None
    keyword = _keyword(route_result)

    def fetch() -> object:
        from app.infrastructure.tenant_scope import tenant_scope
        from app.mod_sdk.erp_customers_facade import customers_list
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        with tenant_scope(_request_tenant_id(request)):
            result = try_invoke_erp_domain_handler(
                "customers",
                "list",
                request=request,
                page=1,
                per_page=50,
                keyword=keyword or None,
            )
            return (
                customers_list(request, page=1, per_page=50, keyword=keyword or None)
                if result is None
                else result
            )

    return QueryExecutor(logger).run(
        route_result,
        intent="customers_query",
        fetch=fetch,
        present=lambda result: presentation.customers(result, keyword),
        reject=lambda result: presentation.rejected_customers(result, keyword),
        failed="客户查询工具执行失败",
        unavailable="客户查询工具暂时不可用，请稍后重试。",
        log_name="customers.query 工具",
        agent_tool=True,
    )


def build_inventory_alert_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    def fetch() -> JsonObject:
        from app.application import get_material_application_service

        return get_material_application_service().get_low_stock_materials()

    return QueryExecutor(logger).run(
        route_result,
        intent="inventory_alert",
        fetch=fetch,
        present=presentation.inventory_alert,
        failed="库存查询工具执行失败",
        unavailable="库存查询服务暂时不可用，请稍后重试。",
        log_name="inventory_alert",
    )


def build_inventory_count_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "inventory_count":
        return None
    return slot_reply(
        "inventory_count",
        "库存盘点需先确认：请提供产品（型号/名称）、仓库及实盘数量，例如「盘点 A001 主仓 实盘 120」。系统会核对账面数量并显示差异，确认后再执行调整。",
        data={"awaiting_params": ["product_id", "warehouse_id", "actual_quantity"]},
        requires_confirmation=True,
    )


def build_mrp_production_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    def fetch() -> JsonObject:
        from app.services.manufacturing_service import ManufacturingService

        return ManufacturingService().query_orders(page=1, per_page=20)

    return QueryExecutor(logger).run(
        route_result,
        intent="mrp_production",
        fetch=fetch,
        present=presentation.manufacturing,
        failed="生产工单查询工具执行失败",
        unavailable="生产工单查询服务暂时不可用，请稍后重试。",
        log_name="mrp.query_orders 工具",
    )


def build_aging_report_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "aging_report":
        return None
    slots = route_result.get("slots") or {}
    account_type = str(slots.get("account_type") or "应收").strip()
    party_id = slots.get("party_id")
    if not party_id:
        return slot_reply(
            "aging_report",
            f"账龄分析（{account_type}）需要指定客户/供应商。请提供客户或供应商名称/ID，例如「查看 XX 客户的应收账龄」，我会按账期分组汇总未结余额。",
            data={"account_type": account_type, "party_id": None},
        )

    def fetch() -> JsonObject:
        from app.services.accounting_services import aging_report

        party_type = "receivable" if account_type in ("应收", "receivable", "客户") else "payable"
        return aging_report(party_type=party_type, party_id=int(party_id))

    return QueryExecutor(logger).run(
        route_result,
        intent="aging_report",
        fetch=fetch,
        present=lambda result: presentation.aging(result, account_type),
        failed="账龄分析工具执行失败",
        unavailable="账龄分析服务暂时不可用，请稍后重试。",
        log_name="aging_report 工具",
    )


def build_label_print_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "label_print":
        return None
    slots = route_result.get("slots") or {}
    model = str(slots.get("model_number") or "").strip()
    quantity = max(1, int(slots.get("quantity") or 1))
    if not model:
        return slot_reply(
            "label_print",
            "请告诉我要打印哪款产品的标签？例如「打印 A001 标签 2 张」",
            success=False,
        )
    try:
        from app.application.print_app_service import get_print_application_service

        result = get_print_application_service().print_single_label(
            product_name=model, model_number=model, quantity=quantity
        )
        message = (
            f"已发送打印任务：{model} × {quantity} 张。"
            if result.get("success")
            else f"打印失败：{result.get('message', '未知错误')}。请检查打印机连接。"
        )
        return slot_reply("label_print", message, data=result, success=result.get("success", False))
    except RECOVERABLE_ERRORS as error:
        logger.warning("label_print 失败: %s", error)
        return {
            "success": False,
            "response": "标签打印服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_materials_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "materials_query":
        return None
    keyword = _keyword(route_result)

    def fetch() -> JsonObject:
        from app.application import get_material_application_service

        return get_material_application_service().get_all_materials(
            search=keyword or None, category=None, page=1, per_page=20
        )

    return QueryExecutor(logger).run(
        route_result,
        intent="materials_query",
        fetch=fetch,
        present=lambda result: presentation.materials(result, keyword),
        failed="物料查询工具执行失败",
        unavailable="物料查询服务暂时不可用，请稍后重试。",
        log_name="materials.query 工具",
    )


def build_shipment_records_query_response_dict(
    route_result: dict[str, Any],
) -> dict[str, Any] | None:
    if route_result.get("intent") != "shipment_records_query":
        return None
    keyword = _keyword(route_result)

    def fetch() -> list[JsonObject]:
        from app.bootstrap import get_shipment_app_service

        records = get_shipment_app_service().get_shipment_records(keyword or None, limit=100)
        if not isinstance(records, list):
            raise ValueError("shipment query returned a non-list result")
        return cast(list[JsonObject], records)

    return QueryExecutor(logger).run(
        route_result,
        intent="shipment_records_query",
        fetch=fetch,
        present=lambda result: presentation.shipments(result, keyword),
        failed="出货记录查询工具执行失败",
        unavailable="出货记录查询服务暂时不可用，请稍后重试。",
        log_name="shipment_records.list 工具",
    )


def build_purchase_query_response_dict(
    route_result: dict[str, Any], *, message: str = ""
) -> dict[str, Any] | None:
    if route_result.get("intent") != "purchase_query":
        return None
    text = str(message or "").strip()
    suppliers = "供应商" in text or "供应商" in _keyword(route_result)
    keyword = (
        re.sub("(?:供应商|进货|采购|有哪些|哪些|一下|查询|查)", "", text).strip()
        if suppliers
        else ""
    )

    def fetch() -> JsonObject:
        from app.application.facades.inventory_facade import PurchaseService

        service = PurchaseService()
        return cast(
            JsonObject,
            service.get_suppliers(keyword=keyword or None)
            if suppliers
            else service.get_purchase_orders(page=1, per_page=20),
        )

    return QueryExecutor(logger).run(
        route_result,
        intent="purchase_query",
        fetch=fetch,
        present=lambda result: (
            presentation.suppliers(result, keyword)
            if suppliers
            else presentation.purchase_orders(result)
        ),
        failed="采购查询工具执行失败",
        unavailable="采购查询服务暂时不可用，请稍后重试。",
        log_name="purchase.query 工具",
    )


def build_finance_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    def fetch() -> JsonObject:
        from app.application.finance_app_service import FinanceAppService

        return FinanceAppService().list_transactions(page=1, per_page=20)

    return QueryExecutor(logger).run(
        route_result,
        intent="finance_query",
        fetch=fetch,
        present=presentation.finance,
        failed="财务查询工具执行失败",
        unavailable="财务查询服务暂时不可用，请稍后重试。",
        log_name="finance.query 工具",
    )


def build_knowledge_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "knowledge_query":
        return None
    return slot_reply(
        "knowledge_query",
        "你可以在「知识库」查看产品型号说明、操作手册与常见问题。模块入口：产品 → 型号详情；设置 → 帮助中心。",
        data={"autoAction": {"type": "open_knowledge", "feature": "knowledge"}},
    )


def build_clarify_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "clarify":
        return None
    slots = route_result.get("slots") or {}
    question = str(slots.get("question") or "").strip()
    if not question:
        return None
    return slot_reply(
        "clarify",
        question,
        data={
            "text": question,
            "action": "followup",
            "data": {"candidates": slots.get("candidates") or [], "llm_routed": True},
        },
    )


def build_sales_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    if route_result.get("intent") != "sales_query":
        return None
    keyword = _keyword(route_result)

    def fetch() -> JsonObject:
        from app.application.sales_app_service import SalesAppService

        return SalesAppService().query(keyword=keyword or None, page=1, per_page=20)

    return QueryExecutor(logger).run(
        route_result,
        intent="sales_query",
        fetch=fetch,
        present=lambda result: presentation.sales(result, keyword),
        failed="销售查询工具执行失败",
        unavailable="销售查询服务暂时不可用，请稍后重试。",
        log_name="sales.query 工具",
    )


def build_reports_query_response_dict(
    route_result: dict[str, Any], *, message: str = ""
) -> dict[str, Any] | None:
    text = str(message or "").strip()
    label = (
        "库存"
        if "库存" in text
        else "采购"
        if "采购" in text
        else "经营看板"
        if any(word in text for word in ("看板", "经营", "数据"))
        else "销售"
    )

    def fetch() -> JsonObject:
        from app.services.report_service import ReportService

        service = ReportService()
        if label == "库存":
            return service.get_inventory_report()
        if label == "采购":
            return service.get_purchase_report()
        if label == "经营看板":
            return service.get_dashboard_summary()
        return service.get_sales_report(group_by="product")

    return QueryExecutor(logger).run(
        route_result,
        intent="reports_query",
        fetch=fetch,
        present=lambda result: presentation.reports(result, label),
        failed="报表工具执行失败",
        unavailable="报表服务暂时不可用，请稍后重试。",
        log_name="reports.* 工具",
    )


def build_replenishment_suggest_response_dict(
    route_result: dict[str, Any],
) -> dict[str, Any] | None:
    def fetch() -> JsonObject:
        from app.services.replenishment_service import suggest_replenishment

        return suggest_replenishment()

    return QueryExecutor(logger).run(
        route_result,
        intent="replenishment_suggest",
        fetch=fetch,
        present=presentation.replenishment,
        failed="补货建议工具执行失败",
        unavailable="补货建议服务暂时不可用，请稍后重试。",
        log_name="replenishment.suggest 工具",
    )
