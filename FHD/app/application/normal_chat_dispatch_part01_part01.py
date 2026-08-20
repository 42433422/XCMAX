# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


def _as_closed_loop_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def _sales_write_idempotency_key(
    customer_name: str,
    product_name: str,
    quantity: int | float,
    unit: str,
    unit_price: int | float,
    request_invoice: bool,
    request_payment: bool,
) -> str:
    seed = _facade().json.dumps(
        {
            "customer_name": customer_name,
            "product_name": product_name,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
            "invoice": request_invoice,
            "payment": request_payment,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sw-" + _facade().hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _first_marker(text: str, markers: tuple[str, ...], start: int = 0) -> tuple[int, str]:
    matches = ((index, marker) for marker in markers if (index := text.find(marker, start)) >= 0)
    return min(matches, default=(-1, ""), key=lambda item: item[0])


def _decimal_prefix(text: str) -> tuple[float, str] | None:
    candidate = text.lstrip()
    allowed = "+-.0123456789"
    end = next(
        (index for index, char in enumerate(candidate) if char not in allowed), len(candidate)
    )
    try:
        return (float(candidate[:end]), candidate[end:])
    except ValueError:
        return None


def _parse_sales_write_request(text: str) -> dict[str, _facade().Any] | None:
    """线性解析销售闭环写意图；字段缺失或非正时 fail closed。"""
    if not any(marker in text for marker in _facade()._SALES_WRITE_SELL_MARKERS):
        return None
    head_index, head_marker = _facade()._first_marker(text, ("把", "将"))
    if head_index < 0:
        return None
    product_start = head_index + len(head_marker)
    sell_index, sell_marker = _facade()._first_marker(
        text, _facade()._SALES_WRITE_SELL_MARKERS, product_start
    )
    if sell_index < 0:
        return None
    customer_start = sell_index + len(sell_marker)
    delimiter_index, _ = _facade()._first_marker(text, tuple("，,；;"), customer_start)
    if delimiter_index < 0:
        return None
    product_name = text[product_start:sell_index].strip()
    customer_name = text[customer_start:delimiter_index].strip()
    if not product_name or not customer_name:
        return None
    tail = text[delimiter_index + 1 :]
    quantity_scan = _facade()._decimal_prefix(tail)
    if quantity_scan is None:
        return None
    quantity_raw, quantity_tail = quantity_scan
    unit_text = quantity_tail.lstrip()
    unit_end = next(
        (
            index
            for index, char in enumerate(unit_text)
            if char.isdigit() or char.isspace() or char in "，,。；;"
        ),
        len(unit_text),
    )
    unit = unit_text[:unit_end]
    if not 1 <= len(unit) <= 4:
        return None
    price_marker = tail.find("单价")
    if price_marker < 0:
        return None
    price_text = tail[price_marker + len("单价") :].lstrip(" \t\r\n:：")
    price_scan = _facade()._decimal_prefix(price_text)
    if price_scan is None:
        return None
    unit_price_raw, _price_tail = price_scan
    if quantity_raw <= 0 or unit_price_raw <= 0 or (not unit):
        return None
    quantity = _facade()._as_closed_loop_number(quantity_raw)
    unit_price = _facade()._as_closed_loop_number(unit_price_raw)
    total_amount = _facade()._as_closed_loop_number(quantity_raw * unit_price_raw)
    request_invoice = "开票" in text
    request_payment = "收款" in text
    idem_key = _facade()._sales_write_idempotency_key(
        customer_name, product_name, quantity, unit, unit_price, request_invoice, request_payment
    )
    return {
        "idempotency_key": idem_key,
        "order": {
            "customer_name": customer_name,
            "customer_id": None,
            "customer_resolution": "current_tenant_exact_name",
            "currency": "CNY",
            "items": [
                {
                    "product_name": product_name,
                    "product_id": None,
                    "product_resolution": "current_tenant_exact_name",
                    "quantity": quantity,
                    "unit": unit,
                    "unit_price": unit_price,
                    "line_total": total_amount,
                }
            ],
            "total_amount": total_amount,
        },
        "fulfillment": {
            "requested": True,
            "quantity": quantity,
            "unit": unit,
            "warehouse_id": None,
            "warehouse_resolution": "current_tenant_default",
        },
        "invoice": {"requested": request_invoice, "amount": total_amount, "currency": "CNY"},
        "payment_allocation": {
            "requested": request_payment,
            "amount": total_amount,
            "currency": "CNY",
        },
    }


def _is_sales_closed_loop_write(text: str) -> bool:
    """供规则规划器复用同源、无副作用的销售闭环写判定。"""
    return _facade()._parse_sales_write_request(text) is not None


def route_normal_mode_message(message: str) -> dict[str, _facade().Any]:
    """普通版轻量槽位提取与任务分流。"""
    text = (message or "").strip()
    lower = text.lower()
    shipment_keywords = ("发货单", "送货单", "出货单", "开单", "打单", "打印")
    number_style_order = bool(
        _facade().re.search(
            "(?:\\d+|[一二两三四五六七八九十零〇]+)\\s*桶\\s*[0-9A-Za-z-]+\\s*规格\\s*\\d+(?:\\.\\d+)?",
            text,
        )
    )
    if any(k in text for k in shipment_keywords) or number_style_order:
        return {"intent": "shipment", "slots": {"number_style_order": number_style_order}}
    sales_write_payload = _facade()._parse_sales_write_request(text)
    if sales_write_payload is not None:
        return {
            "intent": "sales_write",
            "action": "execute_closed_loop",
            "payload": sales_write_payload,
        }
    query_keywords = ("查询", "查一下", "查下", "查", "看看", "看下", "搜索", "找下", "找", "检索")
    model_signal = bool(_facade().re.search("(?:型号|编号)\\s*[:：]?\\s*([0-9A-Za-z-]{2,})", text))
    unit_model_signal = bool(
        _facade().re.search("([^\\s，,。]{2,})\\s*的\\s*([0-9A-Za-z-]{2,})", text)
    )
    customer_entity_markers = ("客户", "购买单位", "买家")
    if any(k in text for k in customer_entity_markers):
        return {"intent": "customers_query", "slots": {"keyword": ""}}
    delete_keywords = ("删除", "移除", "删掉", "删了")
    if any(k in text for k in delete_keywords):
        del_target = ""
        target_match = _facade().re.search("(?:删除|移除|删掉|删了)\\s*([^\\s，,。]{2,})", text)
        if target_match:
            del_target = target_match.group(1).strip()
        return {"intent": "delete_entity", "slots": {"keyword": del_target}}
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
        return {"intent": "reports_query", "slots": {"keyword": ""}}
    inventory_count_keywords = ("库存盘点", "盘点", "实盘")
    if any(k in text for k in inventory_count_keywords):
        return {
            "intent": "inventory_count",
            "slots": {"product_id": "", "warehouse_id": "", "actual_quantity": ""},
        }
    inventory_keywords = ("库存", "库存预警", "低库存", "库存不足", "缺货", "原材料库存", "仓库")
    if any(k in text for k in inventory_keywords):
        return {"intent": "inventory_alert", "slots": {}}
    print_label_keywords = ("标签", "打标签", "打印标签", "商标", "贴标")
    if any(k in text for k in print_label_keywords):
        model_m = _facade().re.search("([0-9A-Za-z-]{2,})", text)
        qty_m = _facade().re.search("(\\d+)\\s*(?:张|份|个|次|条)?", text)
        return {
            "intent": "label_print",
            "slots": {
                "model_number": (model_m.group(1) if model_m else "").strip().upper(),
                "quantity": int(qty_m.group(1)) if qty_m else 1,
            },
        }
    material_keywords = ("物料", "原材料", "材料")
    if any(k in text for k in material_keywords):
        return {"intent": "materials_query", "slots": {"keyword": ""}}
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
        return {"intent": "shipment_records_query", "slots": {"keyword": ""}}
    replenish_keywords = ("补货", "补货建议", "采购建议", "建议采购", "补多少")
    if any(k in text for k in replenish_keywords):
        return {"intent": "replenishment_suggest", "slots": {}}
    mrp_keywords = ("生产工单", "生产", "工单", "BOM", "领料", "完工")
    if any(k in text for k in mrp_keywords):
        return {"intent": "mrp_production", "slots": {"order_id": "", "bom_id": ""}}
    purchase_keywords = ("采购", "供应商", "进货", "采购单", "采购订单", "采购入库")
    if any(k in text for k in purchase_keywords):
        return {"intent": "purchase_query", "slots": {"keyword": ""}}
    aging_keywords = ("账龄", "应收账龄", "应付账龄")
    if any(k in text for k in aging_keywords):
        return {"intent": "aging_report", "slots": {"account_type": "应收", "days": 30}}
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
        return {"intent": "finance_query", "slots": {}}
    sales_keywords = (
        "销售订单",
        "报价单",
        "销售单",
        "下单",
        "收款",
        "开票",
        "发货单确认",
        "销售明细",
    )
    if any(k in text for k in sales_keywords):
        return {"intent": "sales_query", "slots": {"keyword": ""}}
    knowledge_keywords = ("知识库", "资料库", "帮助文档", "使用文档", "操作手册", "帮助中心")
    if any(k in text for k in knowledge_keywords):
        return {"intent": "knowledge_query", "slots": {}}
    if any(k in text for k in query_keywords) or model_signal or unit_model_signal:
        slots: dict[str, _facade().Any] = {}
        m_unit_model = _facade().re.search("([^\\s，,。]{2,})\\s*的\\s*([0-9A-Za-z-]{2,})", text)
        if m_unit_model:
            slots["unit_name"] = (m_unit_model.group(1) or "").strip()
            slots["model_number"] = (m_unit_model.group(2) or "").strip().upper()
        m_model = _facade().re.search("(?:型号|编号)\\s*[:：]?\\s*([0-9A-Za-z-]{2,})", text)
        if m_model and (not slots.get("model_number")):
            slots["model_number"] = (m_model.group(1) or "").strip().upper()
        if slots.get("unit_name"):
            slots["unit_name"] = (
                _facade()
                .re.sub(
                    "^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*",
                    "",
                    str(slots["unit_name"]),
                    flags=_facade().re.IGNORECASE,
                )
                .strip()
            )
        if not slots.get("model_number"):
            m_tail_model = _facade().re.search("\\b([0-9A-Za-z-]{3,})\\b", text)
            if m_tail_model:
                token = (m_tail_model.group(1) or "").strip().upper()
                if not _facade().re.fullmatch("(API|HTTP|JSON|XML)", token):
                    slots["model_number"] = token
        if not slots.get("keyword"):
            if slots.get("unit_name") and slots.get("model_number"):
                slots["keyword"] = f"{slots['unit_name']}{slots['model_number']}"
            elif slots.get("model_number"):
                tail = (
                    _facade()
                    .re.sub(
                        "^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*",
                        "",
                        text,
                    )
                    .strip()
                )
                m_combo = _facade().re.search("([\\u4e00-\\u9fff]{2,})([0-9A-Za-z-]{2,})", tail)
                if m_combo:
                    slots["keyword"] = (
                        f"{m_combo.group(1).strip()}{m_combo.group(2).strip().upper()}"
                    )
                else:
                    slots["keyword"] = slots.get("model_number")
            else:
                keyword = _facade().re.sub(
                    "(?:帮我|给我|请|查询|查一下|查下|查|看看|看下|搜索|找下|找|检索|一下|一下子)",
                    " ",
                    lower,
                )
                keyword = _facade().re.sub("\\s+", " ", keyword).strip()
                keyword = "" if _facade().is_full_product_list_phrase(keyword) else keyword
                if keyword:
                    slots["keyword"] = keyword
        return {"intent": "product_query", "slots": slots}
    return {"intent": "unknown", "slots": {}}
