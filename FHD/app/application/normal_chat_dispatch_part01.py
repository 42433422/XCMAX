# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.normal_chat_dispatch')

def _as_closed_loop_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)

def _sales_write_idempotency_key(customer_name: str, product_name: str, quantity: int | float, unit: str, unit_price: int | float, request_invoice: bool, request_payment: bool) -> str:
    seed = _facade().json.dumps({'customer_name': customer_name, 'product_name': product_name, 'quantity': quantity, 'unit': unit, 'unit_price': unit_price, 'invoice': request_invoice, 'payment': request_payment}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'sw-' + _facade().hashlib.sha256(seed.encode('utf-8')).hexdigest()

def _first_marker(text: str, markers: tuple[str, ...], start: int=0) -> tuple[int, str]:
    matches = ((index, marker) for marker in markers if (index := text.find(marker, start)) >= 0)
    return min(matches, default=(-1, ''), key=lambda item: item[0])

def _decimal_prefix(text: str) -> tuple[float, str] | None:
    candidate = text.lstrip()
    allowed = '+-.0123456789'
    end = next((index for (index, char) in enumerate(candidate) if char not in allowed), len(candidate))
    try:
        return (float(candidate[:end]), candidate[end:])
    except ValueError:
        return None

def _parse_sales_write_request(text: str) -> dict[str, _facade().Any] | None:
    """线性解析销售闭环写意图；字段缺失或非正时 fail closed。"""
    if not any((marker in text for marker in _facade()._SALES_WRITE_SELL_MARKERS)):
        return None
    (head_index, head_marker) = _facade()._first_marker(text, ('把', '将'))
    if head_index < 0:
        return None
    product_start = head_index + len(head_marker)
    (sell_index, sell_marker) = _facade()._first_marker(text, _facade()._SALES_WRITE_SELL_MARKERS, product_start)
    if sell_index < 0:
        return None
    customer_start = sell_index + len(sell_marker)
    (delimiter_index, _) = _facade()._first_marker(text, tuple('，,；;'), customer_start)
    if delimiter_index < 0:
        return None
    product_name = text[product_start:sell_index].strip()
    customer_name = text[customer_start:delimiter_index].strip()
    if not product_name or not customer_name:
        return None
    tail = text[delimiter_index + 1:]
    quantity_scan = _facade()._decimal_prefix(tail)
    if quantity_scan is None:
        return None
    (quantity_raw, quantity_tail) = quantity_scan
    unit_text = quantity_tail.lstrip()
    unit_end = next((index for (index, char) in enumerate(unit_text) if char.isdigit() or char.isspace() or char in '，,。；;'), len(unit_text))
    unit = unit_text[:unit_end]
    if not 1 <= len(unit) <= 4:
        return None
    price_marker = tail.find('单价')
    if price_marker < 0:
        return None
    price_text = tail[price_marker + len('单价'):].lstrip(' \t\r\n:：')
    price_scan = _facade()._decimal_prefix(price_text)
    if price_scan is None:
        return None
    (unit_price_raw, _price_tail) = price_scan
    if quantity_raw <= 0 or unit_price_raw <= 0 or (not unit):
        return None
    quantity = _facade()._as_closed_loop_number(quantity_raw)
    unit_price = _facade()._as_closed_loop_number(unit_price_raw)
    total_amount = _facade()._as_closed_loop_number(quantity_raw * unit_price_raw)
    request_invoice = '开票' in text
    request_payment = '收款' in text
    idem_key = _facade()._sales_write_idempotency_key(customer_name, product_name, quantity, unit, unit_price, request_invoice, request_payment)
    return {'idempotency_key': idem_key, 'order': {'customer_name': customer_name, 'customer_id': None, 'customer_resolution': 'current_tenant_exact_name', 'currency': 'CNY', 'items': [{'product_name': product_name, 'product_id': None, 'product_resolution': 'current_tenant_exact_name', 'quantity': quantity, 'unit': unit, 'unit_price': unit_price, 'line_total': total_amount}], 'total_amount': total_amount}, 'fulfillment': {'requested': True, 'quantity': quantity, 'unit': unit, 'warehouse_id': None, 'warehouse_resolution': 'current_tenant_default'}, 'invoice': {'requested': request_invoice, 'amount': total_amount, 'currency': 'CNY'}, 'payment_allocation': {'requested': request_payment, 'amount': total_amount, 'currency': 'CNY'}}

def _is_sales_closed_loop_write(text: str) -> bool:
    """供规则规划器复用同源、无副作用的销售闭环写判定。"""
    return _facade()._parse_sales_write_request(text) is not None

def route_normal_mode_message(message: str) -> dict[str, _facade().Any]:
    """普通版轻量槽位提取与任务分流。"""
    text = (message or '').strip()
    lower = text.lower()
    shipment_keywords = ('发货单', '送货单', '出货单', '开单', '打单', '打印')
    number_style_order = bool(_facade().re.search('(?:\\d+|[一二两三四五六七八九十零〇]+)\\s*桶\\s*[0-9A-Za-z-]+\\s*规格\\s*\\d+(?:\\.\\d+)?', text))
    if any((k in text for k in shipment_keywords)) or number_style_order:
        return {'intent': 'shipment', 'slots': {'number_style_order': number_style_order}}
    sales_write_payload = _facade()._parse_sales_write_request(text)
    if sales_write_payload is not None:
        return {'intent': 'sales_write', 'action': 'execute_closed_loop', 'payload': sales_write_payload}
    query_keywords = ('查询', '查一下', '查下', '查', '看看', '看下', '搜索', '找下', '找', '检索')
    model_signal = bool(_facade().re.search('(?:型号|编号)\\s*[:：]?\\s*([0-9A-Za-z-]{2,})', text))
    unit_model_signal = bool(_facade().re.search('([^\\s，,。]{2,})\\s*的\\s*([0-9A-Za-z-]{2,})', text))
    customer_entity_markers = ('客户', '购买单位', '买家')
    if any((k in text for k in customer_entity_markers)):
        return {'intent': 'customers_query', 'slots': {'keyword': ''}}
    delete_keywords = ('删除', '移除', '删掉', '删了')
    if any((k in text for k in delete_keywords)):
        del_target = ''
        target_match = _facade().re.search('(?:删除|移除|删掉|删了)\\s*([^\\s，,。]{2,})', text)
        if target_match:
            del_target = target_match.group(1).strip()
        return {'intent': 'delete_entity', 'slots': {'keyword': del_target}}
    report_keywords = ('报表', '销售报表', '库存报表', '采购报表', '汇总', '经营看板', '数据看板', '统计')
    if any((k in text for k in report_keywords)):
        return {'intent': 'reports_query', 'slots': {'keyword': ''}}
    inventory_count_keywords = ('库存盘点', '盘点', '实盘')
    if any((k in text for k in inventory_count_keywords)):
        return {'intent': 'inventory_count', 'slots': {'product_id': '', 'warehouse_id': '', 'actual_quantity': ''}}
    inventory_keywords = ('库存', '库存预警', '低库存', '库存不足', '缺货', '原材料库存', '仓库')
    if any((k in text for k in inventory_keywords)):
        return {'intent': 'inventory_alert', 'slots': {}}
    print_label_keywords = ('标签', '打标签', '打印标签', '商标', '贴标')
    if any((k in text for k in print_label_keywords)):
        model_m = _facade().re.search('([0-9A-Za-z-]{2,})', text)
        qty_m = _facade().re.search('(\\d+)\\s*(?:张|份|个|次|条)?', text)
        return {'intent': 'label_print', 'slots': {'model_number': (model_m.group(1) if model_m else '').strip().upper(), 'quantity': int(qty_m.group(1)) if qty_m else 1}}
    material_keywords = ('物料', '原材料', '材料')
    if any((k in text for k in material_keywords)):
        return {'intent': 'materials_query', 'slots': {'keyword': ''}}
    shipment_record_keywords = ('出货记录', '发货记录', '出货历史', '出货列表', '发货列表', '出货查询', '发货查询', '出货明细', '发货明细')
    if any((k in text for k in shipment_record_keywords)):
        return {'intent': 'shipment_records_query', 'slots': {'keyword': ''}}
    replenish_keywords = ('补货', '补货建议', '采购建议', '建议采购', '补多少')
    if any((k in text for k in replenish_keywords)):
        return {'intent': 'replenishment_suggest', 'slots': {}}
    mrp_keywords = ('生产工单', '生产', '工单', 'BOM', '领料', '完工')
    if any((k in text for k in mrp_keywords)):
        return {'intent': 'mrp_production', 'slots': {'order_id': '', 'bom_id': ''}}
    purchase_keywords = ('采购', '供应商', '进货', '采购单', '采购订单', '采购入库')
    if any((k in text for k in purchase_keywords)):
        return {'intent': 'purchase_query', 'slots': {'keyword': ''}}
    aging_keywords = ('账龄', '应收账龄', '应付账龄')
    if any((k in text for k in aging_keywords)):
        return {'intent': 'aging_report', 'slots': {'account_type': '应收', 'days': 30}}
    finance_keywords = ('财务', '凭证', '收支', '应收', '应付', '交易流水', '资金', '对账', '总账', '记账')
    if any((k in text for k in finance_keywords)):
        return {'intent': 'finance_query', 'slots': {}}
    sales_keywords = ('销售订单', '报价单', '销售单', '下单', '收款', '开票', '发货单确认', '销售明细')
    if any((k in text for k in sales_keywords)):
        return {'intent': 'sales_query', 'slots': {'keyword': ''}}
    knowledge_keywords = ('知识库', '资料库', '帮助文档', '使用文档', '操作手册', '帮助中心')
    if any((k in text for k in knowledge_keywords)):
        return {'intent': 'knowledge_query', 'slots': {}}
    if any((k in text for k in query_keywords)) or model_signal or unit_model_signal:
        slots: dict[str, _facade().Any] = {}
        m_unit_model = _facade().re.search('([^\\s，,。]{2,})\\s*的\\s*([0-9A-Za-z-]{2,})', text)
        if m_unit_model:
            slots['unit_name'] = (m_unit_model.group(1) or '').strip()
            slots['model_number'] = (m_unit_model.group(2) or '').strip().upper()
        m_model = _facade().re.search('(?:型号|编号)\\s*[:：]?\\s*([0-9A-Za-z-]{2,})', text)
        if m_model and (not slots.get('model_number')):
            slots['model_number'] = (m_model.group(1) or '').strip().upper()
        if slots.get('unit_name'):
            slots['unit_name'] = _facade().re.sub('^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*', '', str(slots['unit_name']), flags=_facade().re.IGNORECASE).strip()
        if not slots.get('model_number'):
            m_tail_model = _facade().re.search('\\b([0-9A-Za-z-]{3,})\\b', text)
            if m_tail_model:
                token = (m_tail_model.group(1) or '').strip().upper()
                if not _facade().re.fullmatch('(API|HTTP|JSON|XML)', token):
                    slots['model_number'] = token
        if not slots.get('keyword'):
            if slots.get('unit_name') and slots.get('model_number'):
                slots['keyword'] = f"{slots['unit_name']}{slots['model_number']}"
            elif slots.get('model_number'):
                tail = _facade().re.sub('^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*', '', text).strip()
                m_combo = _facade().re.search('([\\u4e00-\\u9fff]{2,})([0-9A-Za-z-]{2,})', tail)
                if m_combo:
                    slots['keyword'] = f'{m_combo.group(1).strip()}{m_combo.group(2).strip().upper()}'
                else:
                    slots['keyword'] = slots.get('model_number')
            else:
                keyword = _facade().re.sub('(?:帮我|给我|请|查询|查一下|查下|查|看看|看下|搜索|找下|找|检索|一下|一下子)', ' ', lower)
                keyword = _facade().re.sub('\\s+', ' ', keyword).strip()
                keyword = '' if _facade().is_full_product_list_phrase(keyword) else keyword
                if keyword:
                    slots['keyword'] = keyword
        return {'intent': 'product_query', 'slots': slots}
    return {'intent': 'unknown', 'slots': {}}

def build_product_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """构造与 unified_chat 产品查询分支一致的响应 dict。"""
    if route_result.get('intent') != 'product_query':
        return None
    route_slots = route_result.get('slots') or {}
    unit_name = str(route_slots.get('unit_name') or '').strip()
    model_number = str(route_slots.get('model_number') or '').strip().upper()
    keyword = str(route_slots.get('keyword') or '').strip()
    preview_lines = []
    preview_count = 0
    try:
        from app.bootstrap import get_products_service
        products_service = get_products_service()
        kw_preview = (keyword or '').strip() or (model_number or '').strip()
        result = products_service.get_products(unit_name=None, model_number=None, keyword=kw_preview or None, page=1, per_page=5) or {}
        rows = result.get('data') or []
        preview_count = len(rows)
        for row in rows[:3]:
            m = (row.get('model_number') or '').strip()
            n = (row.get('name') or row.get('product_name') or '-').strip()
            p = _facade().safe_float(row.get('price'))
            preview_lines.append(f"- {m or '-'} / {n} / ￥{_facade().format_money(p)}")
    except _facade().RECOVERABLE_ERRORS as query_err:
        _facade().logger.warning('产品查询预览失败：%s', query_err, exc_info=True)
    query_desc_bits = []
    if unit_name:
        query_desc_bits.append(f'单位：{unit_name}')
    if model_number:
        query_desc_bits.append(f'型号：{model_number}')
    if keyword and keyword != model_number:
        query_desc_bits.append(f'关键词：{keyword}')
    query_desc = '，'.join(query_desc_bits) if query_desc_bits else '按当前输入'
    preview_suffix = f'\n预览命中 {preview_count} 条：\n' + '\n'.join(preview_lines) if preview_lines else ''
    return {'success': True, 'message': '已在副窗打开产品查询', 'response': f'已帮你打开产品副窗并带入「{keyword or model_number or query_desc}」。你可以直接在卡片里查看和修改。{preview_suffix}', 'autoAction': {'type': 'show_products_float', 'feature': 'products', 'query': keyword or model_number}, 'data': {'routing': 'normal_slot_dispatch', 'intent': 'product_query', 'slots': route_slots}}

def run_workflow_products_query_normal_profile(user_message: str, node_params: dict[str, _facade().Any] | None=None, per_page: int=20) -> dict[str, _facade().Any]:
    node_params = dict(node_params or {})
    text = (user_message or '').strip()
    rr = _facade().route_normal_mode_message(text)
    kw_preview = ''
    if rr.get('intent') == 'product_query':
        route_slots = rr.get('slots') or {}
        kw_preview = str(route_slots.get('keyword') or route_slots.get('model_number') or '').strip()
    if not kw_preview and rr.get('intent') != 'product_query':
        kw_preview = str(node_params.get('keyword') or '').strip() or str(node_params.get('model_number') or '').strip().upper() or str(node_params.get('product_name') or node_params.get('name') or '').strip() or text
    try:
        from app.bootstrap import get_products_service
        svc = get_products_service()
        result = svc.get_products(unit_name=None, model_number=None, keyword=kw_preview or None, page=1, per_page=per_page) or {}
        return {'success': bool(result.get('success')), 'data': result.get('data', []), 'raw': result, 'normal_tool_profile': True}
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.warning('normal_profile products.query 失败：%s', err, exc_info=True)
        return {'success': False, 'message': str(err), 'data': [], 'normal_tool_profile': True}

def resolve_tool_execution_profile(runtime_context: dict[str, _facade().Any] | None) -> str:
    """返回 normal | pro_default。"""
    rc = dict(runtime_context or {})
    explicit = str(rc.get('tool_execution_profile') or '').strip().lower()
    if explicit == 'normal':
        return 'normal'
    if explicit in ('pro_default', 'pro', 'professional'):
        return 'pro_default'
    us = str(rc.get('ui_surface') or '').strip().lower()
    ic = str(rc.get('intent_channel') or 'pro').strip().lower()
    if us == 'normal' and ic == 'pro':
        return 'normal'
    return 'pro_default'

def run_normal_slot_shipment_preview(order_text: str) -> dict[str, _facade().Any]:
    """
    normal_slot_dispatch.shipment_preview：与普通版 unified_chat shipment 分支同源（编号解析 + 预览任务）。
    延迟导入避免循环依赖。
    """
    text = (order_text or '').strip()
    if not text:
        return {'success': False, 'message': '缺少 order_text', 'data': {}}
    from app.application.facades.tools_facade import _parse_order_text
    parsed = _parse_order_text(text)
    if not parsed.get('success'):
        return {'success': True, 'message': '处理完成', 'response': str(parsed.get('message') or '订单信息不完整，请补充单位/桶数/型号/规格。'), 'data': {'text': parsed.get('message'), 'action': 'followup', 'data': {'parsed_data': parsed}}, 'normal_slot_dispatch': True}
    from app.application import ai_chat_helpers as ai_chat_mod
    body = ai_chat_mod.build_shipment_preview_response_dict(parsed.get('unit_name', ''), parsed.get('products') or [], text)
    body['normal_slot_dispatch'] = True
    return body

def run_normal_slot_product_query_from_message(message: str) -> dict[str, _facade().Any]:
    """normal_slot_dispatch.product_query：整段响应 dict（含 autoAction）。"""
    rr = _facade().route_normal_mode_message(message or '')
    body = _facade().build_product_query_response_dict(rr)
    if body is None:
        return {'success': False, 'message': '当前话术未识别为普通版产品查询槽位', 'data': {'intent': rr.get('intent'), 'slots': rr.get('slots')}}
    body['normal_slot_dispatch'] = True
    return body

def _request_tenant_id(request: _facade().Any | None) -> int | None:
    """从 request 取 tenant_id（流式响应中 ContextVar 可能已被中间件 finally 清掉）。

    优先 ``request.state.tenant_id``；若为空再从 session Cookie 解析，避免市场 Bearer
    曾盖掉本地会话时中间件写入 None 导致 ORM fail-closed。
    """
    if request is None:
        return None
    try:
        value = getattr(getattr(request, 'state', None), 'tenant_id', None)
        if value is not None:
            return int(value)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        from app.infrastructure.auth.tenant_context import resolve_tenant_id
        return resolve_tenant_id(request)
    except _facade().RECOVERABLE_ERRORS:
        return None

def try_normal_slot_read_payload(message: str, *, request: _facade().Any | None=None) -> dict[str, _facade().Any] | None:
    """普通版只读业务：命中则走确定性 Agent 工具（无 LLM 也可 tool-call）。

    客户类问题调用 customers.query 并写入 legacy_tool_records，避免 LLM 编造或误提关键词。
    StreamingResponse 迭代时显式恢复 request + tenant，避免 ContextVar 重置后租户读空。
    """
    text = str(message or '').strip()
    if not text:
        return None
    if _facade().looks_like_explicit_workflow_tool_intent(text):
        return None
    req_token = None
    if request is not None:
        try:
            from app.infrastructure.request_context import set_current_request
            req_token = set_current_request(request)
        except _facade().RECOVERABLE_ERRORS:
            req_token = None
    try:
        from app.infrastructure.tenant_scope import tenant_scope
        with tenant_scope(_facade()._request_tenant_id(request)):
            rr = _facade().route_normal_mode_message(text)
            intent = str(rr.get('intent') or '').strip()
            if intent == 'customers_query':
                payload = _facade().build_customers_query_response_dict(rr, request=request)
            elif intent == 'product_query':
                payload = _facade().build_product_query_response_dict(rr)
            elif intent == 'inventory_alert':
                payload = _facade().build_inventory_alert_response_dict(rr)
            elif intent == 'inventory_count':
                payload = _facade().build_inventory_count_response_dict(rr)
            elif intent == 'mrp_production':
                payload = _facade().build_mrp_production_response_dict(rr)
            elif intent == 'aging_report':
                payload = _facade().build_aging_report_response_dict(rr)
            elif intent == 'label_print':
                payload = _facade().build_label_print_response_dict(rr)
            elif intent == 'materials_query':
                payload = _facade().build_materials_query_response_dict(rr)
            elif intent == 'shipment_records_query':
                payload = _facade().build_shipment_records_query_response_dict(rr)
            elif intent == 'purchase_query':
                payload = _facade().build_purchase_query_response_dict(rr, message=text)
            elif intent == 'finance_query':
                payload = _facade().build_finance_query_response_dict(rr)
            elif intent == 'knowledge_query':
                payload = _facade().build_knowledge_query_response_dict(rr)
            elif intent == 'sales_query':
                payload = _facade().build_sales_query_response_dict(rr)
            elif intent == 'reports_query':
                payload = _facade().build_reports_query_response_dict(rr, message=text)
            elif intent == 'replenishment_suggest':
                payload = _facade().build_replenishment_suggest_response_dict(rr)
            else:
                return None
    finally:
        if req_token is not None:
            try:
                from app.infrastructure.request_context import reset_current_request
                reset_current_request(req_token)
            except _facade().RECOVERABLE_ERRORS:
                pass
    if not isinstance(payload, dict):
        return None
    if payload.get('success') is False and (not payload.get('response')):
        return None
    return payload

def build_customers_query_response_dict(route_result: dict[str, _facade().Any], *, request: _facade().Any | None=None) -> dict[str, _facade().Any] | None:
    """客户查询：确定性调用 customers.query（ERP list），按 Agent 工具结果作答。

    无 LLM 时也可直接 tool-call 读库；禁止把用户原话当 keyword，空结果用中性「暂无/不匹配」文案。
    """
    if route_result.get('intent') != 'customers_query':
        return None
    keyword = str((route_result.get('slots') or {}).get('keyword') or '').strip()
    tool_params: dict[str, _facade().Any] = {'page': 1, 'per_page': 50}
    if keyword:
        tool_params['keyword'] = keyword
    try:
        from app.infrastructure.tenant_scope import tenant_scope
        from app.mod_sdk.erp_customers_facade import customers_list as customers_list_via_service
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler
        with tenant_scope(_facade()._request_tenant_id(request)):
            result = try_invoke_erp_domain_handler('customers', 'list', request=request, page=1, per_page=50, keyword=keyword or None)
            if result is None:
                result = customers_list_via_service(request, page=1, per_page=50, keyword=keyword or None)
        if isinstance(result, dict) and result.get('success') is False:
            msg = str(result.get('message') or result.get('response') or '客户查询工具执行失败')
            tool_record = {'tool_id': 'customers', 'action': 'query', 'params': tool_params, 'output': result if isinstance(result, dict) else {'success': False}, 'tool_call_id': 'tc-customers-query'}
            return {'success': False, 'response': msg, 'data': {'intent': 'customers_query', 'legacy_tool_records': [tool_record]}, 'legacy_tool_records': [tool_record], 'agent_tool_dispatch': True, 'normal_slot_dispatch': True}
        customers = result.get('data', []) if isinstance(result, dict) else []
        if not isinstance(customers, list):
            customers = []
        total = int(result.get('total') or len(customers)) if isinstance(result, dict) else len(customers)
        if not customers:
            msg = f'没有查到与「{keyword}」匹配的客户。' if keyword else '当前客户库暂无数据。'
        else:
            lines = [f"- {c.get('customer_name', '')} {c.get('contact_person', '')}".rstrip() for c in customers[:10]]
            msg = f'当前共有 {total} 位客户：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 位请到「客户管理」查看'
        tool_output = {'success': True, 'data': customers[:20], 'total': total, 'page': 1, 'per_page': 50}
        tool_record = {'tool_id': 'customers', 'action': 'query', 'params': tool_params, 'output': tool_output, 'tool_call_id': 'tc-customers-query'}
        return {'success': True, 'response': msg, 'data': {'intent': 'customers_query', 'customers': customers[:20], 'legacy_tool_records': [tool_record]}, 'legacy_tool_records': [tool_record], 'agent_tool_dispatch': True, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('customers.query 工具失败: %s', e)
        return {'success': False, 'response': '客户查询工具暂时不可用，请稍后重试。', 'data': {}, 'agent_tool_dispatch': True, 'normal_slot_dispatch': True}
