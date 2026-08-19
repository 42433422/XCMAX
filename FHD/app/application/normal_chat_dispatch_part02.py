# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.normal_chat_dispatch')

def build_inventory_alert_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """库存预警槽位响应（聚合 materials low-stock + inventory alert）。"""
    if route_result.get('intent') != 'inventory_alert':
        return None
    try:
        from app.application import get_material_application_service
        result = get_material_application_service().get_low_stock_materials()
        items = result.get('data') or []
        if not items:
            msg = '当前没有低库存原材料，库存状态正常。'
        else:
            lines = [f"- {m.get('name', '')} 当前库存 {m.get('quantity', 0)} {m.get('unit', '')}" for m in items[:10]]
            msg = f'⚠️ 发现 {len(items)} 种低库存原材料：\n' + '\n'.join(lines)
        return {'success': True, 'response': msg, 'data': {'intent': 'inventory_alert', 'low_stock_items': items[:20]}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('inventory_alert 失败: %s', e)
        return {'success': False, 'response': '库存查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_inventory_count_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """库存盘点：盘点为写/高风险操作，命中后引导提供产品/仓库/实盘数量并请求确认。"""
    if route_result.get('intent') != 'inventory_count':
        return None
    return {'success': True, 'response': '库存盘点需先确认：请提供产品（型号/名称）、仓库及实盘数量，例如「盘点 A001 主仓 实盘 120」。系统会核对账面数量并显示差异，确认后再执行调整。', 'data': {'intent': 'inventory_count', 'awaiting_params': ['product_id', 'warehouse_id', 'actual_quantity']}, 'requires_confirmation': True, 'normal_slot_dispatch': True}

def build_mrp_production_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """生产制造/工单：确定性调用 ManufacturingService.query_orders（吸收 Odoo 18 MRP）。"""
    if route_result.get('intent') != 'mrp_production':
        return None
    try:
        from app.services.manufacturing_service import ManufacturingService
        result = ManufacturingService().query_orders(page=1, per_page=20)
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '生产工单查询工具执行失败'), 'data': {'intent': 'mrp_production'}, 'normal_slot_dispatch': True}
        orders = result.get('data') or []
        total = int(result.get('total') or len(orders))
        if not orders:
            msg = '当前没有生产工单。'
        else:
            lines = [f"- {o.get('order_no', '')} {o.get('product_name', '')} ×{o.get('quantity', 0)}（{o.get('status', '')}）" for o in orders[:10]]
            msg = f'共 {total} 条生产工单：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 条请到「生产制造」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'mrp_production', 'orders': orders[:20], 'total': total}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('mrp.query_orders 工具失败: %s', e)
        return {'success': False, 'response': '生产工单查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_aging_report_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """账龄分析：无 party_id 时引导指定客户/供应商；有则确定性调用 accounting_services.aging_report。"""
    if route_result.get('intent') != 'aging_report':
        return None
    slots = route_result.get('slots') or {}
    account_type = str(slots.get('account_type') or '应收').strip()
    party_id = slots.get('party_id')
    if not party_id:
        return {'success': True, 'response': f'账龄分析（{account_type}）需要指定客户/供应商。请提供客户或供应商名称/ID，例如「查看 XX 客户的应收账龄」，我会按账期分组汇总未结余额。', 'data': {'intent': 'aging_report', 'account_type': account_type, 'party_id': None}, 'normal_slot_dispatch': True}
    try:
        from app.services.accounting_services import aging_report
        party_type = 'receivable' if account_type in ('应收', 'receivable', '客户') else 'payable'
        result = aging_report(party_type=party_type, party_id=int(party_id))
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '账龄分析工具执行失败'), 'data': {'intent': 'aging_report'}, 'normal_slot_dispatch': True}
        buckets = result.get('data') or []
        lines = [f"- {b.get('bucket', '')}：￥{_facade().format_money(_facade().safe_float(b.get('amount')))}" for b in buckets]
        msg = f"{account_type}账龄（截至 {result.get('as_of_date', '')}）：\n" + '\n'.join(lines) + f"\n未结合计 ￥{_facade().format_money(_facade().safe_float(result.get('total_outstanding')))}"
        return {'success': True, 'response': msg, 'data': {'intent': 'aging_report', **result}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('aging_report 工具失败: %s', e)
        return {'success': False, 'response': '账龄分析服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_label_print_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """标签打印槽位响应。"""
    if route_result.get('intent') != 'label_print':
        return None
    slots = route_result.get('slots') or {}
    model_number = str(slots.get('model_number') or '').strip()
    quantity = max(1, int(slots.get('quantity') or 1))
    if not model_number:
        return {'success': False, 'response': '请告诉我要打印哪款产品的标签？例如「打印 A001 标签 2 张」', 'data': {'intent': 'label_print'}, 'normal_slot_dispatch': True}
    try:
        from app.application.print_app_service import get_print_application_service
        result = get_print_application_service().print_single_label(product_name=model_number, model_number=model_number, quantity=quantity)
        if result.get('success'):
            msg = f'已发送打印任务：{model_number} × {quantity} 张。'
        else:
            msg = f"打印失败：{result.get('message', '未知错误')}。请检查打印机连接。"
        return {'success': result.get('success', False), 'response': msg, 'data': {'intent': 'label_print', **result}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('label_print 失败: %s', e)
        return {'success': False, 'response': '标签打印服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_materials_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """物料/原材料库查询：确定性调用 materials.query（list）。"""
    if route_result.get('intent') != 'materials_query':
        return None
    keyword = str((route_result.get('slots') or {}).get('keyword') or '').strip()
    try:
        from app.application import get_material_application_service
        result = get_material_application_service().get_all_materials(search=keyword or None, category=None, page=1, per_page=20)
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '物料查询工具执行失败'), 'data': {'intent': 'materials_query'}, 'normal_slot_dispatch': True}
        items = result.get('data') or []
        total = int(result.get('total') or len(items))
        if not items:
            msg = '当前物料库暂无数据。' if not keyword else f'没有查到与「{keyword}」匹配的物料。'
        else:
            lines = [f"- {m.get('name', '')} 库存 {m.get('quantity', 0)} {m.get('unit', '')}（{m.get('material_code', '')}）" for m in items[:10]]
            msg = f'当前共有 {total} 种物料：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 种请到「物料管理」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'materials_query', 'materials': items[:20], 'total': total}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('materials.query 工具失败: %s', e)
        return {'success': False, 'response': '物料查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_shipment_records_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """出货/发货记录查询：确定性调用 shipment_records.list。"""
    if route_result.get('intent') != 'shipment_records_query':
        return None
    keyword = str((route_result.get('slots') or {}).get('keyword') or '').strip()
    try:
        from app.bootstrap import get_shipment_app_service
        records = get_shipment_app_service().get_shipment_records(keyword or None, limit=100)
        if not records:
            msg = '当前没有出货记录。' if not keyword else f'没有查到与「{keyword}」相关的出货记录。'
        else:
            lines = []
            for r in records[:10]:
                unit = str(r.get('unit_name') or r.get('purchase_unit') or '') or '-'
                date = str(r.get('date') or r.get('created_at') or '')[:10]
                lines.append(f'- {date} {unit}')
            msg = f'共 {len(records)} 条出货记录：\n' + '\n'.join(lines)
            if len(records) > 10:
                msg += f'\n…其余 {len(records) - 10} 条请到「出货记录」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'shipment_records_query', 'records': records[:20]}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('shipment_records.list 工具失败: %s', e)
        return {'success': False, 'response': '出货记录查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_purchase_query_response_dict(route_result: dict[str, _facade().Any], *, message: str='') -> dict[str, _facade().Any] | None:
    """采购/供应商/进货查询：按关键词命中供应商或采购订单。"""
    if route_result.get('intent') != 'purchase_query':
        return None
    text = str(message or '').strip()
    try:
        from app.application.facades.inventory_facade import PurchaseService
        svc = PurchaseService()
        if '供应商' in text or '供应商' in str((route_result.get('slots') or {}).get('keyword') or ''):
            keyword = _facade().re.sub('(?:供应商|进货|采购|有哪些|哪些|一下|查询|查)', '', text).strip()
            result = svc.get_suppliers(keyword=keyword or None)
            suppliers = result.get('data') or []
            if not suppliers:
                msg = '当前没有供应商数据。' if not keyword else f'没有查到与「{keyword}」匹配的供应商。'
            else:
                lines = [f"- {s.get('name', '')} {s.get('contact_person', '')}".rstrip() for s in suppliers[:10]]
                msg = f'共 {len(suppliers)} 家供应商：\n' + '\n'.join(lines)
            return {'success': True, 'response': msg, 'data': {'intent': 'purchase_query', 'suppliers': suppliers[:20]}, 'normal_slot_dispatch': True}
        result = svc.get_purchase_orders(page=1, per_page=20)
        orders = result.get('data') or []
        total = int(result.get('total') or len(orders))
        if not orders:
            msg = '当前没有采购订单。'
        else:
            lines = [f"- {o.get('order_no', '')} {o.get('supplier_name', '')} ￥{_facade().format_money(_facade().safe_float(o.get('total_amount')))}" for o in orders[:10]]
            msg = f'共 {total} 条采购订单：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 条请到「采购管理」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'purchase_query', 'orders': orders[:20], 'total': total}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('purchase.query 工具失败: %s', e)
        return {'success': False, 'response': '采购查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_finance_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """财务/凭证/收支流水查询。"""
    if route_result.get('intent') != 'finance_query':
        return None
    try:
        from app.application.finance_app_service import FinanceAppService
        result = FinanceAppService().list_transactions(page=1, per_page=20)
        items = result.get('data') or []
        total = int(result.get('total') or len(items))
        if not items:
            msg = '当前没有财务收支记录。'
        else:
            lines = []
            for t in items[:10]:
                t_type = str(t.get('transaction_type') or '')
                direction = '收入' if 'in' in str(t_type).lower() or '收款' in str(t_type) else '支出'
                lines.append(f"- {str(t.get('transaction_date') or '')[:10]} {direction} ￥{_facade().format_money(_facade().safe_float(t.get('amount')))} {t.get('counterparty_name', '')}")
            msg = f'共 {total} 条收支记录：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 条请到「财务」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'finance_query', 'transactions': items[:20], 'total': total}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('finance.query 工具失败: %s', e)
        return {'success': False, 'response': '财务查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_knowledge_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """知识库/帮助文档：引导直达资料库（无数据库读取）。"""
    if route_result.get('intent') != 'knowledge_query':
        return None
    return {'success': True, 'response': '你可以在「知识库」查看产品型号说明、操作手册与常见问题。模块入口：产品 → 型号详情；设置 → 帮助中心。', 'data': {'intent': 'knowledge_query', 'autoAction': {'type': 'open_knowledge', 'feature': 'knowledge'}}, 'normal_slot_dispatch': True}

def build_sales_query_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """销售订单/报价单查询：确定性调用 sales.query（Sales-to-Payment 闭环）。"""
    if route_result.get('intent') != 'sales_query':
        return None
    keyword = str((route_result.get('slots') or {}).get('keyword') or '').strip()
    try:
        from app.application.sales_app_service import SalesAppService
        result = SalesAppService().query(keyword=keyword or None, page=1, per_page=20)
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '销售查询工具执行失败'), 'data': {'intent': 'sales_query'}, 'normal_slot_dispatch': True}
        orders = result.get('data') or []
        total = int(result.get('total') or len(orders))
        if not orders:
            msg = '当前没有销售订单。' if not keyword else f'没有查到与「{keyword}」匹配的销售订单。'
        else:
            lines = []
            for o in orders[:10]:
                status = str(o.get('status') or '')
                lines.append(f"- {o.get('order_no', '')} {o.get('customer_name', '')} ￥{_facade().format_money(_facade().safe_float(o.get('total_amount')))}（{status}）")
            msg = f'共 {total} 条销售订单：\n' + '\n'.join(lines)
            if total > 10:
                msg += f'\n…其余 {total - 10} 条请到「销售订单」查看'
        return {'success': True, 'response': msg, 'data': {'intent': 'sales_query', 'orders': orders[:20], 'total': total}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('sales.query 工具失败: %s', e)
        return {'success': False, 'response': '销售查询服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_reports_query_response_dict(route_result: dict[str, _facade().Any], *, message: str='') -> dict[str, _facade().Any] | None:
    """报表/汇总/看板查询：按关键词命中销售/库存/采购/经营看板报表。"""
    if route_result.get('intent') != 'reports_query':
        return None
    text = str(message or '').strip()
    try:
        from app.services.report_service import ReportService
        svc = ReportService()
        if '库存' in text or '库存报表' in text:
            result = svc.get_inventory_report()
            label = '库存'
        elif '采购' in text or '采购报表' in text:
            result = svc.get_purchase_report()
            label = '采购'
        elif '看板' in text or '经营' in text or '数据' in text:
            result = svc.get_dashboard_summary()
            label = '经营看板'
        else:
            result = svc.get_sales_report(group_by='product')
            label = '销售'
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '报表工具执行失败'), 'data': {'intent': 'reports_query'}, 'normal_slot_dispatch': True}
        rows = result.get('data') or []
        summary = result.get('summary') or {}
        if not rows:
            msg = f'当前{label}报表暂无数据。'
        else:
            lines = [f'- {r}' for r in [str(r) for r in rows[:5]]]
            msg = f'{label}报表共 {len(rows)} 条：\n' + '\n'.join(lines)
            if summary:
                bits = [f'{k}={v}' for (k, v) in summary.items()][:4]
                msg += f"\n汇总：{'，'.join(bits)}"
        return {'success': True, 'response': msg, 'data': {'intent': 'reports_query', 'report_type': label, 'rows': rows[:20], 'summary': summary}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('reports.* 工具失败: %s', e)
        return {'success': False, 'response': '报表服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}

def build_replenishment_suggest_response_dict(route_result: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
    """补货/采购建议：确定性调用 suggest_replenishment（吸收 Odoo 18 补货逻辑）。"""
    if route_result.get('intent') != 'replenishment_suggest':
        return None
    try:
        from app.services.replenishment_service import suggest_replenishment
        result = suggest_replenishment()
        if isinstance(result, dict) and result.get('success') is False:
            return {'success': False, 'response': str(result.get('message') or '补货建议工具执行失败'), 'data': {'intent': 'replenishment_suggest'}, 'normal_slot_dispatch': True}
        suggestions = result.get('data') or []
        summary = result.get('summary') or {}
        if not suggestions:
            msg = '当前没有需要补货的物料，库存状态正常。'
        else:
            lines = [f"- {s.get('name', '')} 当前 {s.get('current_quantity', 0)} {s.get('unit', '')}，建议补 {s.get('suggest_quantity', 0)}" for s in suggestions[:10]]
            msg = f'发现 {len(suggestions)} 种物料需要补货：\n' + '\n'.join(lines) + f"\n合计建议采购金额 ￥{_facade().format_money(_facade().safe_float(summary.get('total_suggest_amount')))}"
        return {'success': True, 'response': msg, 'data': {'intent': 'replenishment_suggest', 'suggestions': suggestions[:20], 'summary': summary}, 'normal_slot_dispatch': True}
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning('replenishment.suggest 工具失败: %s', e)
        return {'success': False, 'response': '补货建议服务暂时不可用，请稍后重试。', 'data': {}, 'normal_slot_dispatch': True}
