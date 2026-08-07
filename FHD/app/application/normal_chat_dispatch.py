"""
普通版聊天槽位路由与产品查询响应（与 unified_chat 行为一致）。

供 /api/ai/unified_chat、工作流 execute_registered_workflow_tool（tool_execution_profile=normal）
及 normal_slot_dispatch 工具复用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.utils.ai_helpers import format_money, safe_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def route_normal_mode_message(message: str) -> dict[str, Any]:
    """
    普通版轻量槽位提取与任务分流：
    - shipment: 发货单 / 开单 / 打印 / 出货单等单据语境
    - product_query: 产品库检索
    - customers_query: 客户/购买单位查询
    - inventory_alert: 库存预警
    - label_print: 标签打印
    - unknown: 未命中
    """
    text = (message or "").strip()
    lower = text.lower()

    shipment_keywords = ("发货单", "送货单", "出货单", "开单", "打单", "打印")
    number_style_order = bool(
        re.search(
            r"(?:\d+|[一二两三四五六七八九十零〇]+)\s*桶\s*[0-9A-Za-z-]+\s*规格\s*\d+(?:\.\d+)?",
            text,
        )
    )
    if any(k in text for k in shipment_keywords) or number_style_order:
        return {
            "intent": "shipment",
            "slots": {"number_style_order": number_style_order},
        }

    query_keywords = ("查询", "查一下", "查下", "查", "看看", "看下", "搜索", "找下", "找", "检索")
    model_signal = bool(re.search(r"(?:型号|编号)\s*[:：]?\s*([0-9A-Za-z-]{2,})", text))
    unit_model_signal = bool(re.search(r"([^\s，,。]{2,})\s*的\s*([0-9A-Za-z-]{2,})", text))
    # 客户/购买单位：实体路由到 Agent 工具 customers.query。
    # 禁止用正则把问句前缀抽成客户名 keyword（空泛计数/列表问法必须 keyword=""）。
    # 指名检索由 Agent 在工具参数里填 keyword；此处只负责选工具。
    customer_entity_markers = ("客户", "购买单位", "买家")
    if any(k in text for k in customer_entity_markers):
        return {
            "intent": "customers_query",
            "slots": {"keyword": ""},
        }

    # 删除/移除类操作
    delete_keywords = ("删除", "移除", "删掉", "删了")
    if any(k in text for k in delete_keywords):
        del_target = ""
        target_match = re.search(r"(?:删除|移除|删掉|删了)\s*([^\s，,。]{2,})", text)
        if target_match:
            del_target = target_match.group(1).strip()
        return {
            "intent": "delete_entity",
            "slots": {"keyword": del_target},
        }

    # 报表 / 汇总 / 看板（吸收 Odoo 18 报表中心）——须在销售/库存/采购之前，避免「销售报表」等被宽泛词截胡
    report_keywords = (
        "报表",
        "销售报表",
        "库存报表",
        "采购报表",
        "汇总",
        "经营看板",
        "数据看板",
        "统计",
    )
    if any(k in text for k in report_keywords):
        return {
            "intent": "reports_query",
            "slots": {"keyword": ""},
        }

    # 库存盘点（区别库存预警：盘点需确认，须在「库存」宽泛词之前判断，避免「库存盘点」被截胡）
    inventory_count_keywords = ("库存盘点", "盘点", "实盘")
    if any(k in text for k in inventory_count_keywords):
        return {
            "intent": "inventory_count",
            "slots": {"product_id": "", "warehouse_id": "", "actual_quantity": ""},
        }

    # 库存预警
    inventory_keywords = ("库存", "库存预警", "低库存", "库存不足", "缺货", "原材料库存", "仓库")
    if any(k in text for k in inventory_keywords):
        return {
            "intent": "inventory_alert",
            "slots": {},
        }

    # 标签打印
    print_label_keywords = ("标签", "打标签", "打印标签", "商标", "贴标")
    if any(k in text for k in print_label_keywords):
        model_m = re.search(r"([0-9A-Za-z-]{2,})", text)
        qty_m = re.search(r"(\d+)\s*(?:张|份|个|次|条)?", text)
        return {
            "intent": "label_print",
            "slots": {
                "model_number": (model_m.group(1) if model_m else "").strip().upper(),
                "quantity": int(qty_m.group(1)) if qty_m else 1,
            },
        }

    # 物料/原材料库
    material_keywords = ("物料", "原材料", "材料")
    if any(k in text for k in material_keywords):
        return {
            "intent": "materials_query",
            "slots": {"keyword": ""},
        }

    # 出货/发货记录（区别于 shipment：那是开单/打单流程）
    shipment_record_keywords = (
        "出货记录",
        "发货记录",
        "出货历史",
        "出货列表",
        "发货列表",
        "出货查询",
        "发货查询",
        "出货明细",
        "发货明细",
    )
    if any(k in text for k in shipment_record_keywords):
        return {
            "intent": "shipment_records_query",
            "slots": {"keyword": ""},
        }

    # 补货建议 / 采购建议（吸收 Odoo 18 补货逻辑）——须在采购之前，避免「采购建议」被采购词截胡
    replenish_keywords = ("补货", "补货建议", "采购建议", "建议采购", "补多少")
    if any(k in text for k in replenish_keywords):
        return {
            "intent": "replenishment_suggest",
            "slots": {},
        }

    # 生产制造 / 工单 / BOM（吸收 Odoo 18 MRP）——须在采购/财务/销售之前，避免「生产工单」被宽泛词截胡
    mrp_keywords = ("生产工单", "生产", "工单", "BOM", "领料", "完工")
    if any(k in text for k in mrp_keywords):
        return {
            "intent": "mrp_production",
            "slots": {"order_id": "", "bom_id": ""},
        }

    # 采购 / 供应商 / 进货
    purchase_keywords = ("采购", "供应商", "进货", "采购单", "采购订单", "采购入库")
    if any(k in text for k in purchase_keywords):
        return {
            "intent": "purchase_query",
            "slots": {"keyword": ""},
        }

    # 账龄分析（区别于财务流水：按账期分组未结余额，须在「应收/应付」财务词之前判断）
    aging_keywords = ("账龄", "应收账龄", "应付账龄")
    if any(k in text for k in aging_keywords):
        return {
            "intent": "aging_report",
            "slots": {"account_type": "应收", "days": 30},
        }

    # 财务 / 凭证 / 收支流水
    finance_keywords = (
        "财务",
        "凭证",
        "收支",
        "应收",
        "应付",
        "交易流水",
        "资金",
        "对账",
        "总账",
        "记账",
    )
    if any(k in text for k in finance_keywords):
        return {
            "intent": "finance_query",
            "slots": {},
        }

    # 销售 / 报价 / 销售订单（Sales-to-Payment 闭环，吸收 Odoo 18）
    sales_keywords = (
        "销售订单",
        "报价单",
        "销售单",
        "销售",
        "下单",
        "收款",
        "开票",
        "发货单确认",
        "销售明细",
    )
    if any(k in text for k in sales_keywords):
        return {
            "intent": "sales_query",
            "slots": {"keyword": ""},
        }

    # 知识库 / 帮助文档
    knowledge_keywords = ("知识库", "资料库", "帮助文档", "使用文档", "操作手册", "帮助中心")
    if any(k in text for k in knowledge_keywords):
        return {
            "intent": "knowledge_query",
            "slots": {},
        }

    if any(k in text for k in query_keywords) or model_signal or unit_model_signal:
        slots: dict[str, Any] = {}

        m_unit_model = re.search(r"([^\s，,。]{2,})\s*的\s*([0-9A-Za-z-]{2,})", text)
        if m_unit_model:
            slots["unit_name"] = (m_unit_model.group(1) or "").strip()
            slots["model_number"] = (m_unit_model.group(2) or "").strip().upper()

        m_model = re.search(r"(?:型号|编号)\s*[:：]?\s*([0-9A-Za-z-]{2,})", text)
        if m_model and not slots.get("model_number"):
            slots["model_number"] = (m_model.group(1) or "").strip().upper()

        if slots.get("unit_name"):
            slots["unit_name"] = re.sub(
                r"^(?:帮我|给我|请)?\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\s*",
                "",
                str(slots["unit_name"]),
                flags=re.IGNORECASE,
            ).strip()

        if not slots.get("model_number"):
            m_tail_model = re.search(r"\b([0-9A-Za-z-]{3,})\b", text)
            if m_tail_model:
                token = (m_tail_model.group(1) or "").strip().upper()
                if not re.fullmatch(r"(API|HTTP|JSON|XML)", token):
                    slots["model_number"] = token

        if not slots.get("keyword"):
            if slots.get("unit_name") and slots.get("model_number"):
                slots["keyword"] = f"{slots['unit_name']}{slots['model_number']}"
            elif slots.get("model_number"):
                tail = re.sub(
                    r"^(?:帮我|给我|请)?\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\s*",
                    "",
                    text,
                ).strip()
                m_combo = re.search(r"([\u4e00-\u9fff]{2,})([0-9A-Za-z-]{2,})", tail)
                if m_combo:
                    slots["keyword"] = (
                        f"{m_combo.group(1).strip()}{m_combo.group(2).strip().upper()}"
                    )
                else:
                    slots["keyword"] = slots.get("model_number")
            else:
                keyword = re.sub(
                    r"(?:帮我|给我|请|查询|查一下|查下|查|看看|看下|搜索|找下|找|检索|一下|一下子)",
                    " ",
                    lower,
                )
                keyword = re.sub(r"\s+", " ", keyword).strip()
                if keyword:
                    slots["keyword"] = keyword

        return {"intent": "product_query", "slots": slots}

    return {"intent": "unknown", "slots": {}}


def build_product_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """构造与 unified_chat 产品查询分支一致的响应 dict。"""
    if route_result.get("intent") != "product_query":
        return None

    route_slots = route_result.get("slots") or {}
    unit_name = str(route_slots.get("unit_name") or "").strip()
    model_number = str(route_slots.get("model_number") or "").strip().upper()
    keyword = str(route_slots.get("keyword") or "").strip()

    preview_lines = []
    preview_count = 0
    try:
        from app.bootstrap import get_products_service

        products_service = get_products_service()
        kw_preview = (keyword or "").strip() or (model_number or "").strip()
        result = (
            products_service.get_products(
                unit_name=None,
                model_number=None,
                keyword=kw_preview or None,
                page=1,
                per_page=5,
            )
            or {}
        )
        rows = result.get("data") or []
        preview_count = len(rows)
        for row in rows[:3]:
            m = (row.get("model_number") or "").strip()
            n = (row.get("name") or row.get("product_name") or "-").strip()
            p = safe_float(row.get("price"))
            preview_lines.append(f"- {m or '-'} / {n} / ￥{format_money(p)}")
    except RECOVERABLE_ERRORS as query_err:
        logger.warning("产品查询预览失败：%s", query_err, exc_info=True)

    query_desc_bits = []
    if unit_name:
        query_desc_bits.append(f"单位：{unit_name}")
    if model_number:
        query_desc_bits.append(f"型号：{model_number}")
    if keyword and keyword != model_number:
        query_desc_bits.append(f"关键词：{keyword}")
    query_desc = "，".join(query_desc_bits) if query_desc_bits else "按当前输入"
    preview_suffix = (
        f"\n预览命中 {preview_count} 条：\n" + "\n".join(preview_lines) if preview_lines else ""
    )

    return {
        "success": True,
        "message": "已在副窗打开产品查询",
        "response": (
            f"已帮你打开产品副窗并带入「{keyword or model_number or query_desc}」。"
            "你可以直接在卡片里查看和修改。"
            f"{preview_suffix}"
        ),
        "autoAction": {
            "type": "show_products_float",
            "feature": "products",
            "query": keyword or model_number,
        },
        "data": {
            "routing": "normal_slot_dispatch",
            "intent": "product_query",
            "slots": route_slots,
        },
    }


def run_workflow_products_query_normal_profile(
    user_message: str,
    node_params: dict[str, Any] | None = None,
    per_page: int = 20,
) -> dict[str, Any]:
    """工作流 products.query 在普通工具画像下：与普通版 product_query 相同 keyword 策略。"""
    node_params = dict(node_params or {})
    text = (user_message or "").strip()
    rr = route_normal_mode_message(text)
    kw_preview = ""
    if rr.get("intent") == "product_query":
        route_slots = rr.get("slots") or {}
        keyword = str(route_slots.get("keyword") or "").strip()
        model_number = str(route_slots.get("model_number") or "").strip().upper()
        kw_preview = (keyword or "").strip() or (model_number or "").strip()
    if not kw_preview:
        kw_preview = (
            str(node_params.get("keyword") or "").strip()
            or str(node_params.get("model_number") or "").strip().upper()
            or str(node_params.get("product_name") or node_params.get("name") or "").strip()
            or text
        )
    try:
        from app.bootstrap import get_products_service

        svc = get_products_service()
        result = (
            svc.get_products(
                unit_name=None,
                model_number=None,
                keyword=kw_preview or None,
                page=1,
                per_page=per_page,
            )
            or {}
        )
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
            "normal_tool_profile": True,
        }
    except RECOVERABLE_ERRORS as err:
        logger.warning("normal_profile products.query 失败：%s", err, exc_info=True)
        return {"success": False, "message": str(err), "data": [], "normal_tool_profile": True}


def resolve_tool_execution_profile(runtime_context: dict[str, Any] | None) -> str:
    """返回 normal | pro_default。"""
    rc = dict(runtime_context or {})
    explicit = str(rc.get("tool_execution_profile") or "").strip().lower()
    if explicit == "normal":
        return "normal"
    if explicit in ("pro_default", "pro", "professional"):
        return "pro_default"
    us = str(rc.get("ui_surface") or "").strip().lower()
    ic = str(rc.get("intent_channel") or "pro").strip().lower()
    if us == "normal" and ic == "pro":
        return "normal"
    return "pro_default"


def run_normal_slot_shipment_preview(order_text: str) -> dict[str, Any]:
    """
    normal_slot_dispatch.shipment_preview：与普通版 unified_chat shipment 分支同源（编号解析 + 预览任务）。
    延迟导入避免循环依赖。
    """
    text = (order_text or "").strip()
    if not text:
        return {"success": False, "message": "缺少 order_text", "data": {}}

    from app.application.facades.tools_facade import _parse_order_text

    parsed = _parse_order_text(text)
    if not parsed.get("success"):
        return {
            "success": True,
            "message": "处理完成",
            "response": str(parsed.get("message") or "订单信息不完整，请补充单位/桶数/型号/规格。"),
            "data": {
                "text": parsed.get("message"),
                "action": "followup",
                "data": {"parsed_data": parsed},
            },
            "normal_slot_dispatch": True,
        }

    from app.application import ai_chat_helpers as ai_chat_mod

    body = ai_chat_mod.build_shipment_preview_response_dict(
        parsed.get("unit_name", ""),
        parsed.get("products") or [],
        text,
    )
    body["normal_slot_dispatch"] = True
    return body


def run_normal_slot_product_query_from_message(message: str) -> dict[str, Any]:
    """normal_slot_dispatch.product_query：整段响应 dict（含 autoAction）。"""
    rr = route_normal_mode_message(message or "")
    body = build_product_query_response_dict(rr)
    if body is None:
        return {
            "success": False,
            "message": "当前话术未识别为普通版产品查询槽位",
            "data": {"intent": rr.get("intent"), "slots": rr.get("slots")},
        }
    body["normal_slot_dispatch"] = True
    return body


def _request_tenant_id(request: Any | None) -> int | None:
    """从 request 取 tenant_id（流式响应中 ContextVar 可能已被中间件 finally 清掉）。

    优先 ``request.state.tenant_id``；若为空再从 session Cookie 解析，避免市场 Bearer
    曾盖掉本地会话时中间件写入 None 导致 ORM fail-closed。
    """
    if request is None:
        return None
    try:
        value = getattr(getattr(request, "state", None), "tenant_id", None)
        if value is not None:
            return int(value)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        from app.infrastructure.auth.tenant_context import resolve_tenant_id

        return resolve_tenant_id(request)
    except Exception:  # noqa: BLE001
        return None


def try_normal_slot_read_payload(
    message: str,
    *,
    request: Any | None = None,
) -> dict[str, Any] | None:
    """普通版只读业务：命中则走确定性 Agent 工具（无 LLM 也可 tool-call）。

    客户类问题调用 customers.query（ERP list），写入 legacy_tool_records，
    避免 LLM 编造「没有数据」，也避免正则把问句当客户名。
    StreamingResponse 迭代时 IndustryContextMiddleware 可能已 reset 请求 ContextVar，
    因此这里显式恢复 request + tenant，避免租户 fail-closed 读空。
    """
    text = str(message or "").strip()
    if not text:
        return None

    req_token = None
    if request is not None:
        try:
            from app.infrastructure.request_context import set_current_request

            req_token = set_current_request(request)
        except Exception:  # noqa: BLE001
            req_token = None

    try:
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(_request_tenant_id(request)):
            rr = route_normal_mode_message(text)
            intent = str(rr.get("intent") or "").strip()
            if intent == "customers_query":
                payload = build_customers_query_response_dict(rr, request=request)
            elif intent == "product_query":
                payload = build_product_query_response_dict(rr)
            elif intent == "inventory_alert":
                payload = build_inventory_alert_response_dict(rr)
            elif intent == "inventory_count":
                payload = build_inventory_count_response_dict(rr)
            elif intent == "mrp_production":
                payload = build_mrp_production_response_dict(rr)
            elif intent == "aging_report":
                payload = build_aging_report_response_dict(rr)
            elif intent == "label_print":
                payload = build_label_print_response_dict(rr)
            elif intent == "materials_query":
                payload = build_materials_query_response_dict(rr)
            elif intent == "shipment_records_query":
                payload = build_shipment_records_query_response_dict(rr)
            elif intent == "purchase_query":
                payload = build_purchase_query_response_dict(rr, message=text)
            elif intent == "finance_query":
                payload = build_finance_query_response_dict(rr)
            elif intent == "knowledge_query":
                payload = build_knowledge_query_response_dict(rr)
            elif intent == "sales_query":
                payload = build_sales_query_response_dict(rr)
            elif intent == "reports_query":
                payload = build_reports_query_response_dict(rr, message=text)
            elif intent == "replenishment_suggest":
                payload = build_replenishment_suggest_response_dict(rr)
            else:
                return None
    finally:
        if req_token is not None:
            try:
                from app.infrastructure.request_context import reset_current_request

                reset_current_request(req_token)
            except Exception:  # noqa: BLE001
                pass

    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False and not payload.get("response"):
        return None
    return payload


def build_customers_query_response_dict(
    route_result: dict[str, Any],
    *,
    request: Any | None = None,
) -> dict[str, Any] | None:
    """客户查询：确定性调用 customers.query（ERP list），按 Agent 工具结果作答。

    无 LLM 时也可直接 tool-call 读库；禁止把用户原话当 keyword，空结果用中性「暂无/不匹配」文案。
    """
    if route_result.get("intent") != "customers_query":
        return None
    # 仅当上游 Agent 已给出干净检索词时才过滤；默认列表/计数问法 keyword 为空。
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    tool_params: dict[str, Any] = {"page": 1, "per_page": 50}
    if keyword:
        tool_params["keyword"] = keyword
    try:
        # 与 GET /api/customers 同源：优先 erp domain handler（桌面 REST 实际路径），
        # 再回退 facade。勿只走 facade——流式 ContextVar 丢失时会 fail-closed 读空，
        # 而 domain handler 与 UI 客户列表一致。
        from app.infrastructure.tenant_scope import tenant_scope
        from app.mod_sdk.erp_customers_facade import customers_list as customers_list_via_service
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
            if result is None:
                result = customers_list_via_service(
                    request,
                    page=1,
                    per_page=50,
                    keyword=keyword or None,
                )
        if isinstance(result, dict) and result.get("success") is False:
            msg = str(result.get("message") or result.get("response") or "客户查询工具执行失败")
            tool_record = {
                "tool_id": "customers",
                "action": "query",
                "params": tool_params,
                "output": result if isinstance(result, dict) else {"success": False},
                "tool_call_id": "tc-customers-query",
            }
            return {
                "success": False,
                "response": msg,
                "data": {
                    "intent": "customers_query",
                    "legacy_tool_records": [tool_record],
                },
                "legacy_tool_records": [tool_record],
                "agent_tool_dispatch": True,
                "normal_slot_dispatch": True,
            }
        customers = result.get("data", []) if isinstance(result, dict) else []
        if not isinstance(customers, list):
            customers = []
        total = (
            int(result.get("total") or len(customers))
            if isinstance(result, dict)
            else len(customers)
        )
        if not customers:
            msg = f"没有查到与「{keyword}」匹配的客户。" if keyword else "当前客户库暂无数据。"
        else:
            lines = [
                f"- {c.get('customer_name', '')} {c.get('contact_person', '')}".rstrip()
                for c in customers[:10]
            ]
            msg = f"当前共有 {total} 位客户：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 位请到「客户管理」查看"
        tool_output = {
            "success": True,
            "data": customers[:20],
            "total": total,
            "page": 1,
            "per_page": 50,
        }
        tool_record = {
            "tool_id": "customers",
            "action": "query",
            "params": tool_params,
            "output": tool_output,
            "tool_call_id": "tc-customers-query",
        }
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "customers_query",
                "customers": customers[:20],
                "legacy_tool_records": [tool_record],
            },
            "legacy_tool_records": [tool_record],
            "agent_tool_dispatch": True,
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("customers.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "客户查询工具暂时不可用，请稍后重试。",
            "data": {},
            "agent_tool_dispatch": True,
            "normal_slot_dispatch": True,
        }


def build_inventory_alert_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """库存预警槽位响应（聚合 materials low-stock + inventory alert）。"""
    if route_result.get("intent") != "inventory_alert":
        return None
    try:
        from app.application import get_material_application_service

        result = get_material_application_service().get_low_stock_materials()
        items = result.get("data") or []
        if not items:
            msg = "当前没有低库存原材料，库存状态正常。"
        else:
            lines = [
                f"- {m.get('name', '')} 当前库存 {m.get('quantity', 0)} {m.get('unit', '')}"
                for m in items[:10]
            ]
            msg = f"⚠️ 发现 {len(items)} 种低库存原材料：\n" + "\n".join(lines)
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "inventory_alert", "low_stock_items": items[:20]},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("inventory_alert 失败: %s", e)
        return {
            "success": False,
            "response": "库存查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_inventory_count_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """库存盘点：盘点为写/高风险操作，命中后引导提供产品/仓库/实盘数量并请求确认。"""
    if route_result.get("intent") != "inventory_count":
        return None
    return {
        "success": True,
        "response": (
            "库存盘点需先确认：请提供产品（型号/名称）、仓库及实盘数量，"
            "例如「盘点 A001 主仓 实盘 120」。系统会核对账面数量并显示差异，确认后再执行调整。"
        ),
        "data": {
            "intent": "inventory_count",
            "awaiting_params": ["product_id", "warehouse_id", "actual_quantity"],
        },
        "requires_confirmation": True,
        "normal_slot_dispatch": True,
    }


def build_mrp_production_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """生产制造/工单：确定性调用 ManufacturingService.query_orders（吸收 Odoo 18 MRP）。"""
    if route_result.get("intent") != "mrp_production":
        return None
    try:
        from app.services.manufacturing_service import ManufacturingService

        result = ManufacturingService().query_orders(page=1, per_page=20)
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "生产工单查询工具执行失败"),
                "data": {"intent": "mrp_production"},
                "normal_slot_dispatch": True,
            }
        orders = result.get("data") or []
        total = int(result.get("total") or len(orders))
        if not orders:
            msg = "当前没有生产工单。"
        else:
            lines = [
                f"- {o.get('order_no', '')} {o.get('product_name', '')} ×{o.get('quantity', 0)}"
                f"（{o.get('status', '')}）"
                for o in orders[:10]
            ]
            msg = f"共 {total} 条生产工单：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「生产制造」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "mrp_production", "orders": orders[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("mrp.query_orders 工具失败: %s", e)
        return {
            "success": False,
            "response": "生产工单查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_aging_report_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """账龄分析：无 party_id 时引导指定客户/供应商；有则确定性调用 accounting_services.aging_report。"""
    if route_result.get("intent") != "aging_report":
        return None
    slots = route_result.get("slots") or {}
    account_type = str(slots.get("account_type") or "应收").strip()
    party_id = slots.get("party_id")
    if not party_id:
        return {
            "success": True,
            "response": (
                f"账龄分析（{account_type}）需要指定客户/供应商。请提供客户或供应商名称/ID，"
                "例如「查看 XX 客户的应收账龄」，我会按账期分组汇总未结余额。"
            ),
            "data": {"intent": "aging_report", "account_type": account_type, "party_id": None},
            "normal_slot_dispatch": True,
        }
    try:
        from app.services.accounting_services import aging_report

        party_type = "receivable" if account_type in ("应收", "receivable", "客户") else "payable"
        result = aging_report(party_type=party_type, party_id=int(party_id))
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "账龄分析工具执行失败"),
                "data": {"intent": "aging_report"},
                "normal_slot_dispatch": True,
            }
        buckets = result.get("data") or []
        lines = [
            f"- {b.get('bucket', '')}：￥{format_money(safe_float(b.get('amount')))}"
            for b in buckets
        ]
        msg = (
            f"{account_type}账龄（截至 {result.get('as_of_date', '')}）：\n"
            + "\n".join(lines)
            + f"\n未结合计 ￥{format_money(safe_float(result.get('total_outstanding')))}"
        )
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "aging_report", **result},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("aging_report 工具失败: %s", e)
        return {
            "success": False,
            "response": "账龄分析服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_label_print_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """标签打印槽位响应。"""
    if route_result.get("intent") != "label_print":
        return None
    slots = route_result.get("slots") or {}
    model_number = str(slots.get("model_number") or "").strip()
    quantity = max(1, int(slots.get("quantity") or 1))
    if not model_number:
        return {
            "success": False,
            "response": "请告诉我要打印哪款产品的标签？例如「打印 A001 标签 2 张」",
            "data": {"intent": "label_print"},
            "normal_slot_dispatch": True,
        }
    try:
        from app.application.print_app_service import get_print_application_service

        result = get_print_application_service().print_single_label(
            product_name=model_number,
            model_number=model_number,
            quantity=quantity,
        )
        if result.get("success"):
            msg = f"已发送打印任务：{model_number} × {quantity} 张。"
        else:
            msg = f"打印失败：{result.get('message', '未知错误')}。请检查打印机连接。"
        return {
            "success": result.get("success", False),
            "response": msg,
            "data": {"intent": "label_print", **result},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("label_print 失败: %s", e)
        return {
            "success": False,
            "response": "标签打印服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_materials_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """物料/原材料库查询：确定性调用 materials.query（list）。"""
    if route_result.get("intent") != "materials_query":
        return None
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    try:
        from app.application import get_material_application_service

        result = get_material_application_service().get_all_materials(
            search=keyword or None,
            category=None,
            page=1,
            per_page=20,
        )
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "物料查询工具执行失败"),
                "data": {"intent": "materials_query"},
                "normal_slot_dispatch": True,
            }
        items = result.get("data") or []
        total = int(result.get("total") or len(items))
        if not items:
            msg = "当前物料库暂无数据。" if not keyword else f"没有查到与「{keyword}」匹配的物料。"
        else:
            lines = [
                f"- {m.get('name', '')} 库存 {m.get('quantity', 0)} {m.get('unit', '')}"
                f"（{m.get('material_code', '')}）"
                for m in items[:10]
            ]
            msg = f"当前共有 {total} 种物料：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 种请到「物料管理」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "materials_query", "materials": items[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("materials.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "物料查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_shipment_records_query_response_dict(
    route_result: dict[str, Any],
) -> dict[str, Any] | None:
    """出货/发货记录查询：确定性调用 shipment_records.list。"""
    if route_result.get("intent") != "shipment_records_query":
        return None
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    try:
        from app.bootstrap import get_shipment_app_service

        records = get_shipment_app_service().get_shipment_records(keyword or None, limit=100)
        if not records:
            msg = (
                "当前没有出货记录。" if not keyword else f"没有查到与「{keyword}」相关的出货记录。"
            )
        else:
            lines = []
            for r in records[:10]:
                unit = str(r.get("unit_name") or r.get("purchase_unit") or "") or "-"
                date = str(r.get("date") or r.get("created_at") or "")[:10]
                lines.append(f"- {date} {unit}")
            msg = f"共 {len(records)} 条出货记录：\n" + "\n".join(lines)
            if len(records) > 10:
                msg += f"\n…其余 {len(records) - 10} 条请到「出货记录」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "shipment_records_query", "records": records[:20]},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("shipment_records.list 工具失败: %s", e)
        return {
            "success": False,
            "response": "出货记录查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_purchase_query_response_dict(
    route_result: dict[str, Any],
    *,
    message: str = "",
) -> dict[str, Any] | None:
    """采购/供应商/进货查询：按关键词命中供应商或采购订单。"""
    if route_result.get("intent") != "purchase_query":
        return None
    text = str(message or "").strip()
    try:
        from app.application.facades.inventory_facade import PurchaseService

        svc = PurchaseService()
        if "供应商" in text or "供应商" in str(
            (route_result.get("slots") or {}).get("keyword") or ""
        ):
            keyword = re.sub(r"(?:供应商|进货|采购|有哪些|哪些|一下|查询|查)", "", text).strip()
            result = svc.get_suppliers(keyword=keyword or None)
            suppliers = result.get("data") or []
            if not suppliers:
                msg = (
                    "当前没有供应商数据。"
                    if not keyword
                    else f"没有查到与「{keyword}」匹配的供应商。"
                )
            else:
                lines = [
                    f"- {s.get('name', '')} {s.get('contact_person', '')}".rstrip()
                    for s in suppliers[:10]
                ]
                msg = f"共 {len(suppliers)} 家供应商：\n" + "\n".join(lines)
            return {
                "success": True,
                "response": msg,
                "data": {"intent": "purchase_query", "suppliers": suppliers[:20]},
                "normal_slot_dispatch": True,
            }
        result = svc.get_purchase_orders(page=1, per_page=20)
        orders = result.get("data") or []
        total = int(result.get("total") or len(orders))
        if not orders:
            msg = "当前没有采购订单。"
        else:
            lines = [
                f"- {o.get('order_no', '')} {o.get('supplier_name', '')} ￥{format_money(safe_float(o.get('total_amount')))}"
                for o in orders[:10]
            ]
            msg = f"共 {total} 条采购订单：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「采购管理」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "purchase_query", "orders": orders[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("purchase.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "采购查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_finance_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """财务/凭证/收支流水查询。"""
    if route_result.get("intent") != "finance_query":
        return None
    try:
        from app.application.finance_app_service import FinanceAppService

        result = FinanceAppService().list_transactions(page=1, per_page=20)
        items = result.get("data") or []
        total = int(result.get("total") or len(items))
        if not items:
            msg = "当前没有财务收支记录。"
        else:
            lines = []
            for t in items[:10]:
                t_type = str(t.get("transaction_type") or "")
                direction = (
                    "收入" if "in" in str(t_type).lower() or "收款" in str(t_type) else "支出"
                )
                lines.append(
                    f"- {str(t.get('transaction_date') or '')[:10]} {direction} "
                    f"￥{format_money(safe_float(t.get('amount')))} {t.get('counterparty_name', '')}"
                )
            msg = f"共 {total} 条收支记录：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「财务」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "finance_query", "transactions": items[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("finance.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "财务查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_knowledge_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """知识库/帮助文档：引导直达资料库（无数据库读取）。"""
    if route_result.get("intent") != "knowledge_query":
        return None
    return {
        "success": True,
        "response": (
            "你可以在「知识库」查看产品型号说明、操作手册与常见问题。"
            "模块入口：产品 → 型号详情；设置 → 帮助中心。"
        ),
        "data": {
            "intent": "knowledge_query",
            "autoAction": {"type": "open_knowledge", "feature": "knowledge"},
        },
        "normal_slot_dispatch": True,
    }


def build_sales_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """销售订单/报价单查询：确定性调用 sales.query（Sales-to-Payment 闭环）。"""
    if route_result.get("intent") != "sales_query":
        return None
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    try:
        from app.application.sales_app_service import SalesAppService

        result = SalesAppService().query(
            keyword=keyword or None,
            page=1,
            per_page=20,
        )
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "销售查询工具执行失败"),
                "data": {"intent": "sales_query"},
                "normal_slot_dispatch": True,
            }
        orders = result.get("data") or []
        total = int(result.get("total") or len(orders))
        if not orders:
            msg = (
                "当前没有销售订单。" if not keyword else f"没有查到与「{keyword}」匹配的销售订单。"
            )
        else:
            lines = []
            for o in orders[:10]:
                status = str(o.get("status") or "")
                lines.append(
                    f"- {o.get('order_no', '')} {o.get('customer_name', '')} "
                    f"￥{format_money(safe_float(o.get('total_amount')))}（{status}）"
                )
            msg = f"共 {total} 条销售订单：\n" + "\n".join(lines)
            if total > 10:
                msg += f"\n…其余 {total - 10} 条请到「销售订单」查看"
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "sales_query", "orders": orders[:20], "total": total},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("sales.query 工具失败: %s", e)
        return {
            "success": False,
            "response": "销售查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_reports_query_response_dict(
    route_result: dict[str, Any],
    *,
    message: str = "",
) -> dict[str, Any] | None:
    """报表/汇总/看板查询：按关键词命中销售/库存/采购/经营看板报表。"""
    if route_result.get("intent") != "reports_query":
        return None
    text = str(message or "").strip()
    try:
        from app.services.report_service import ReportService

        svc = ReportService()
        if "库存" in text or "库存报表" in text:
            result = svc.get_inventory_report()
            label = "库存"
        elif "采购" in text or "采购报表" in text:
            result = svc.get_purchase_report()
            label = "采购"
        elif "看板" in text or "经营" in text or "数据" in text:
            result = svc.get_dashboard_summary()
            label = "经营看板"
        else:
            result = svc.get_sales_report(group_by="product")
            label = "销售"

        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "报表工具执行失败"),
                "data": {"intent": "reports_query"},
                "normal_slot_dispatch": True,
            }
        rows = result.get("data") or []
        summary = result.get("summary") or {}
        if not rows:
            msg = f"当前{label}报表暂无数据。"
        else:
            lines = [f"- {r}" for r in [str(r) for r in rows[:5]]]
            msg = f"{label}报表共 {len(rows)} 条：\n" + "\n".join(lines)
            if summary:
                bits = [f"{k}={v}" for k, v in summary.items()][:4]
                msg += f"\n汇总：{'，'.join(bits)}"
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "reports_query",
                "report_type": label,
                "rows": rows[:20],
                "summary": summary,
            },
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("reports.* 工具失败: %s", e)
        return {
            "success": False,
            "response": "报表服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_replenishment_suggest_response_dict(
    route_result: dict[str, Any],
) -> dict[str, Any] | None:
    """补货/采购建议：确定性调用 suggest_replenishment（吸收 Odoo 18 补货逻辑）。"""
    if route_result.get("intent") != "replenishment_suggest":
        return None
    try:
        from app.services.replenishment_service import suggest_replenishment

        result = suggest_replenishment()
        if isinstance(result, dict) and result.get("success") is False:
            return {
                "success": False,
                "response": str(result.get("message") or "补货建议工具执行失败"),
                "data": {"intent": "replenishment_suggest"},
                "normal_slot_dispatch": True,
            }
        suggestions = result.get("data") or []
        summary = result.get("summary") or {}
        if not suggestions:
            msg = "当前没有需要补货的物料，库存状态正常。"
        else:
            lines = [
                f"- {s.get('name', '')} 当前 {s.get('current_quantity', 0)} {s.get('unit', '')}，"
                f"建议补 {s.get('suggest_quantity', 0)}"
                for s in suggestions[:10]
            ]
            msg = (
                f"发现 {len(suggestions)} 种物料需要补货：\n"
                + "\n".join(lines)
                + f"\n合计建议采购金额 ￥{format_money(safe_float(summary.get('total_suggest_amount')))}"
            )
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "replenishment_suggest",
                "suggestions": suggestions[:20],
                "summary": summary,
            },
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("replenishment.suggest 工具失败: %s", e)
        return {
            "success": False,
            "response": "补货建议服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }
