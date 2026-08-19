# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.tools_workflow_registered')

def _registered_router_normal_slot_dispatch(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.application.normal_chat_dispatch import run_normal_slot_product_query_from_message, run_normal_slot_shipment_preview
    if action == 'product_query':
        text = user_message or str(params.get('message') or '').strip()
        return run_normal_slot_product_query_from_message(text)
    if action == 'shipment_preview':
        order_text = str(params.get('order_text') or user_message or '').strip()
        return run_normal_slot_shipment_preview(order_text)
    return {'success': False, 'message': f'未注册的 normal_slot_dispatch 动作: {action}'}

def _registered_router_customers(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_customer_route':
        from app.fastapi_routes.domains.customer import routes as customer_routes
        return customer_routes._execute_customers_route_action(action, dict(params or {}))
    from app.application import get_customer_app_service
    svc = get_customer_app_service()
    unit_name = str(params.get('unit_name') or params.get('customer_name') or params.get('name') or '').strip()
    if action in {'create', 'ensure_exists', 'upsert'}:
        from app.services.business_db_customer_mutations import execute_customer_create_like
        return execute_customer_create_like(action, params, svc=svc, resolve_targets=_facade()._business_db_target_candidates)
    if action == 'query':
        keyword = str(params.get('keyword') or unit_name or '').strip()
        result = svc.get_all(keyword=keyword, page=1, per_page=20)
        return {'success': bool(result.get('success')), 'data': result.get('data', []), 'raw': result}
    if action == 'update':
        customer_id = int(params.get('id') or params.get('customer_id') or 0)
        if customer_id <= 0:
            return {'success': False, 'message': '缺少 id'}
        payload = {'customer_name': unit_name, 'contact_person': params.get('contact_person', ''), 'contact_phone': params.get('contact_phone', ''), 'contact_address': params.get('contact_address', params.get('address', ''))}
        payload = {k: v for (k, v) in payload.items() if v not in (None, '')}
        update_result = svc.update(customer_id, payload)
        if update_result.get('success'):
            return {'success': True, 'data': update_result.get('data', {})}
        return {'success': False, 'message': update_result.get('message') or '更新失败'}
    if action == 'delete':
        customer_id = int(params.get('id') or params.get('customer_id') or 0)
        if customer_id <= 0:
            return {'success': False, 'message': '缺少 id'}
        return dict(svc.delete(customer_id, force=bool(params.get('force', False))) or {})
    if action == 'batch_delete':
        raw_ids = params.get('ids') or params.get('customer_ids') or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {'success': False, 'message': 'ids 须为非空数组'}
        ids: list[int] = []
        skipped: list[str] = []
        for raw in raw_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                skipped.append(str(raw))
        if not ids:
            return {'success': False, 'message': 'ids 须包含有效数字'}
        result = dict(svc.batch_delete(ids, force=bool(params.get('force', False))) or {})
        if skipped:
            result['skipped'] = list(result.get('skipped') or []) + skipped
        return result
    if action == 'add_address':
        payload = dict(params or {})
        return dict(svc.add_address(payload) or {})
    if action == 'set_credit_limit':
        customer_id = int(params.get('customer_id') or params.get('id') or 0)
        if customer_id <= 0:
            return {'success': False, 'message': '缺少 customer_id'}
        return dict(svc.set_credit_limit(customer_id, params.get('credit_limit') or params.get('limit') or 0) or {})
    if action == 'get_addresses':
        customer_id = int(params.get('customer_id') or params.get('id') or 0)
        if customer_id <= 0:
            return {'success': False, 'message': '缺少 customer_id'}
        return dict(svc.get_addresses(customer_id) or {})
    return {'success': False, 'message': f'未注册的 customers 动作: {action}'}

def _registered_router_products(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.application.normal_chat_dispatch import run_workflow_products_query_normal_profile
    if str(runtime_context.get('service_source') or '') == 'fastapi_product_compat_route':
        import importlib
        route_module = str(runtime_context.get('route_module') or 'app.legacy.routes.product.compat_routes')
        module = importlib.import_module(route_module)
        execute_action = module._execute_products_compat_action
        return dict(execute_action(action, params) or {})
    is_fastapi_product_route = str(runtime_context.get('service_source') or '') == 'fastapi_product_route'
    if is_fastapi_product_route:
        from app.fastapi_routes.domains.product import routes as product_routes
        svc = product_routes._svc()
    else:
        from app.services import get_products_service
        svc = get_products_service()
    explicit_measure_unit = str(params.get('unit') or params.get('measure_unit') or '').strip()
    legacy_unit_name = str(params.get('unit_name') or '').strip()
    try:
        from app.infrastructure.repositories.product_query_helpers import TRIVIAL_MEASURE_UNITS
        legacy_measure_unit = legacy_unit_name if legacy_unit_name in TRIVIAL_MEASURE_UNITS else ''
    except _facade().RECOVERABLE_ERRORS:
        legacy_measure_unit = legacy_unit_name if legacy_unit_name in {'个', '件', '桶', '箱', 'kg', '公斤'} else ''
    measure_unit = explicit_measure_unit or legacy_measure_unit or '个'
    model_number = str(params.get('model_number') or '').strip().upper()
    product_name = str(params.get('product_name') or params.get('name') or '').strip()
    keyword = str(params.get('keyword') or product_name or model_number or '').strip()
    if action == 'query':
        if profile == 'normal':
            return run_workflow_products_query_normal_profile(user_message, node_params=params, per_page=20)
        result = svc.get_products(unit_name=measure_unit if explicit_measure_unit or legacy_measure_unit else None, model_number=model_number or None, keyword=keyword or None, page=1, per_page=20)
        return {'success': bool(result.get('success')), 'data': result.get('data', []), 'raw': result}
    if action == 'exists':
        result = svc.get_products(unit_name=measure_unit if explicit_measure_unit or legacy_measure_unit else None, model_number=model_number or None, keyword=keyword or None, page=1, per_page=10)
        rows = result.get('data') or []
        exists = False
        for row in rows:
            row_name = str(row.get('name') or row.get('product_name') or '').strip()
            row_model = str(row.get('model_number') or '').strip().upper()
            if model_number and row_model == model_number:
                exists = True
                break
            if product_name and row_name == product_name:
                exists = True
                break
        return {'success': True, 'exists': exists, 'matched_count': len(rows)}
    if action == 'create':
        if str(runtime_context.get('service_source') or '') == 'fastapi_product_route':
            payload = dict(params or {})
            return _facade().cast('dict[Any, Any]', svc.create_product(payload))
        name_or_model = str(params.get('name_or_model') or product_name or model_number).strip()
        if not name_or_model:
            return {'success': False, 'message': '缺少 name_or_model'}
        price = params.get('unit_price', params.get('price', 0.0))
        try:
            price = float(price)
        except _facade().RECOVERABLE_ERRORS:
            price = 0.0
        create_result = svc.create_product({'name': name_or_model, 'product_name': name_or_model, 'product_code': model_number or None, 'model_number': model_number or None, 'specification': params.get('specification'), 'unit_price': price, 'price': price, 'unit': measure_unit})
        if create_result.get('success'):
            return {'success': True, 'created': True, 'raw': create_result}
        return {'success': False, 'message': create_result.get('message') or '创建失败'}
    if action == 'update':
        product_id = int(params.get('id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'id'}
        if is_fastapi_product_route:
            return _facade().cast('dict[Any, Any]', svc.update_product(product_id, payload))
        if 'product_name' in payload and 'name' not in payload:
            payload['name'] = payload.pop('product_name')
        if 'unit_price' in payload and 'price' not in payload:
            payload['price'] = payload.pop('unit_price')
        if 'product_code' in payload and 'model_number' not in payload:
            payload['model_number'] = payload.pop('product_code')
        if 'measure_unit' in payload and 'unit' not in payload:
            payload['unit'] = payload.pop('measure_unit')
        legacy_update_unit = str(payload.pop('unit_name', '') or '').strip()
        if legacy_update_unit and 'unit' not in payload:
            payload['unit'] = legacy_update_unit if legacy_update_unit in {'个', '件', '桶', '箱', 'kg', '公斤', '吨', '米', '升'} else '个'
        return _facade().cast('dict[Any, Any]', svc.update_product(product_id, payload))
    if action == 'delete':
        return _facade().cast('dict[Any, Any]', svc.delete_product(int(params.get('id') or 0)))
    if action == 'batch_create':
        raw_products = params.get('products') or []
        if not isinstance(raw_products, list) or not raw_products:
            return {'success': False, 'message': 'products 必须为非空数组'}
        return _facade().cast('dict[Any, Any]', svc.batch_add_products([dict(item) for item in raw_products if isinstance(item, dict)]))
    if action == 'batch_delete':
        raw_ids = params.get('ids') or params.get('product_ids') or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return {'success': False, 'message': 'ids 须为非空数组'}
        ids: list[int] = []
        skipped: list = []
        for raw_id in raw_ids:
            try:
                ids.append(int(raw_id))
            except _facade().RECOVERABLE_ERRORS:
                skipped.append(raw_id)
        if not ids:
            return {'success': False, 'message': 'ids 须包含有效数字', 'skipped': skipped}
        batch_delete = getattr(svc, 'batch_delete_products', None)
        if callable(batch_delete):
            result = dict(batch_delete(ids) or {})
        else:
            result = dict(svc.batch_delete(ids) or {})
        if skipped:
            result['skipped'] = list(result.get('skipped') or []) + skipped
        return result
    return {'success': False, 'message': f'未注册的 products 动作: {action}'}

def _registered_router_materials(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_materials_route':
        from app.fastapi_routes import materials as materials_route
        svc = materials_route._svc()
    else:
        from app.application import get_material_application_service
        svc = get_material_application_service()
    if action in ('list', 'query'):
        result = svc.get_all_materials(search=str(params.get('search') or params.get('keyword') or '').strip(), category=str(params.get('category') or '').strip() or None, page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20))
        return _facade().cast('dict[Any, Any]', result)
    if action == 'create':
        payload = dict(params or {})
        payload.setdefault('name', str(payload.get('name') or payload.get('material_name') or '').strip())
        payload.setdefault('material_code', f'MAT-{_facade().uuid.uuid4().hex[:12].upper()}')
        return _facade().cast('dict[Any, Any]', svc.create_material(payload))
    if action == 'update':
        material_id = int(params.get('id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'id'}
        result = svc.update_material(material_id, **payload)
        if isinstance(result, dict):
            return result
        return {'success': True, 'message': '更新成功', 'data': {'id': material_id}}
    if action == 'delete':
        material_id = int(params.get('id') or 0)
        result = svc.delete_material(material_id)
        if isinstance(result, dict):
            result.setdefault('message', '删除成功')
            return result
        return {'success': True, 'message': '删除成功', 'data': {'id': material_id}}
    if action == 'batch_delete':
        raw_ids = params.get('ids') or params.get('material_ids') or []
        ids = [int(x) for x in raw_ids if str(x).strip()]
        try:
            result = svc.batch_delete_materials(ids)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error('批量删除原材料时 service 执行异常：%s', err)
            return {'success': True, 'message': f'已删除 {len(ids)} 条记录', 'deleted_count': len(ids), 'warning': str(err)}
        if isinstance(result, dict):
            result.setdefault('success', True)
            result.setdefault('deleted_count', len(ids))
            return result
        return {'success': True, 'message': f'已删除 {len(ids)} 条记录', 'deleted_count': len(ids)}
    if action == 'export':
        return _facade().cast('dict[Any, Any]', svc.export_to_excel(search=str(params.get('search') or params.get('keyword') or '').strip() or None, category=str(params.get('category') or '').strip() or None, template_id=params.get('template_id')))
    return {'success': False, 'message': f'未注册的 materials 动作: {action}'}

def _registered_router_inventory(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_inventory_route':
        from app.fastapi_routes import inventory as inventory_route
        svc = inventory_route._svc()
    else:
        from app.application.inventory_app_service import InventoryAppService
        svc = InventoryAppService()

    def _float_or_none(value: object) -> float | None:
        if value is None:
            return None
        return float(str(value))
    if action == 'create_storage_location':
        return _facade().cast('dict[Any, Any]', svc.create_storage_location(dict(params or {})))
    if action == 'update_storage_location':
        location_id = int(params.get('location_id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'location_id'}
        return _facade().cast('dict[Any, Any]', svc.update_storage_location(location_id, payload))
    if action == 'create_warehouse':
        return _facade().cast('dict[Any, Any]', svc.create_warehouse(dict(params or {})))
    if action == 'update_warehouse':
        warehouse_id = int(params.get('warehouse_id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'warehouse_id'}
        return _facade().cast('dict[Any, Any]', svc.update_warehouse(warehouse_id, payload))
    if action == 'delete_warehouse':
        return _facade().cast('dict[Any, Any]', svc.delete_warehouse(int(params.get('warehouse_id') or 0)))
    if action == 'stock_in':
        return _facade().cast('dict[Any, Any]', svc.inventory_in(product_id=params.get('product_id'), warehouse_id=params.get('warehouse_id'), quantity=float(params.get('quantity', 0)), batch_no=params.get('batch_no'), location_id=params.get('location_id'), unit_price=_float_or_none(params.get('unit_price')), reference_type=params.get('reference_type'), reference_id=params.get('reference_id'), operator=params.get('operator'), remark=params.get('remark')))
    if action == 'stock_out':
        return _facade().cast('dict[Any, Any]', svc.inventory_out(product_id=params.get('product_id'), warehouse_id=params.get('warehouse_id'), quantity=float(params.get('quantity', 0)), batch_no=params.get('batch_no'), location_id=params.get('location_id'), unit_price=_float_or_none(params.get('unit_price')), reference_type=params.get('reference_type'), reference_id=params.get('reference_id'), operator=params.get('operator'), remark=params.get('remark')))
    if action == 'transfer':
        return _facade().cast('dict[Any, Any]', svc.inventory_transfer(product_id=params.get('product_id'), from_warehouse_id=params.get('from_warehouse_id'), to_warehouse_id=params.get('to_warehouse_id'), quantity=float(params.get('quantity', 0)), batch_no=params.get('batch_no'), from_location_id=params.get('from_location_id'), to_location_id=params.get('to_location_id'), operator=params.get('operator'), remark=params.get('remark')))
    if action == 'low_stock_alert':
        from app.application.material_app_service import get_material_app_service
        threshold = params.get('threshold')
        return get_material_app_service().get_low_stock_materials(float(threshold) if threshold is not None else None)
    if action == 'replenishment_suggest':
        from app.services.replenishment_service import suggest_replenishment
        return suggest_replenishment(threshold=params.get('threshold'), per_page=int(params.get('per_page') or 50))
    if action == 'inventory_count':
        from app.services.inventory_service import InventoryService
        inv_svc = InventoryService()
        return inv_svc.inventory_count(product_id=int(params.get('product_id') or 0), warehouse_id=int(params.get('warehouse_id') or 0), actual_quantity=float(params.get('actual_quantity', 0)), batch_no=params.get('batch_no'), location_id=params.get('location_id'), operator=params.get('operator'), remark=params.get('remark'), confirmed=bool(params.get('confirmed', False)))
    if action == 'query_transactions':
        from app.services.inventory_service import InventoryService
        inv_svc = InventoryService()
        return inv_svc.query_transactions(product_id=params.get('product_id'), warehouse_id=params.get('warehouse_id'), start_date=params.get('start_date'), end_date=params.get('end_date'), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20))
    return {'success': False, 'message': f'未注册的 inventory 动作: {action}'}

def _registered_router_purchase(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_purchase_route':
        from app.fastapi_routes import purchase as purchase_route
        svc = purchase_route._svc()
    else:
        from app.application.facades.inventory_facade import PurchaseService
        svc = PurchaseService()
    if action in ('list_suppliers', 'get_suppliers', 'query_suppliers'):
        return _facade().cast('dict[Any, Any]', svc.get_suppliers(status=params.get('status'), keyword=str(params.get('keyword') or params.get('search') or '').strip() or None))
    if action in ('list_orders', 'get_orders', 'list_purchase_orders', 'query_orders'):
        return _facade().cast('dict[Any, Any]', svc.get_purchase_orders(supplier_id=params.get('supplier_id'), status=params.get('status'), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20)))
    if action in ('list_inbounds', 'get_inbounds', 'list_purchase_inbounds', 'query_inbounds'):
        return _facade().cast('dict[Any, Any]', svc.get_purchase_inbounds(supplier_id=params.get('supplier_id'), order_id=params.get('order_id'), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20)))
    if action == 'create_supplier':
        return _facade().cast('dict[Any, Any]', svc.create_supplier(dict(params or {})))
    if action == 'update_supplier':
        supplier_id = int(params.get('supplier_id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'supplier_id'}
        return _facade().cast('dict[Any, Any]', svc.update_supplier(supplier_id, payload))
    if action == 'delete_supplier':
        return _facade().cast('dict[Any, Any]', svc.delete_supplier(int(params.get('supplier_id') or 0)))
    if action == 'create_order':
        return _facade().cast('dict[Any, Any]', svc.create_purchase_order(dict(params or {})))
    if action == 'update_order':
        order_id = int(params.get('order_id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'order_id'}
        return _facade().cast('dict[Any, Any]', svc.update_purchase_order(order_id, payload))
    if action == 'approve_order':
        return _facade().cast('dict[Any, Any]', svc.approve_purchase_order(int(params.get('order_id') or 0), str(params.get('approver') or 'system')))
    if action == 'cancel_order':
        return _facade().cast('dict[Any, Any]', svc.cancel_purchase_order(int(params.get('order_id') or 0)))
    if action == 'create_inbound':
        return _facade().cast('dict[Any, Any]', svc.create_purchase_inbound(dict(params or {})))
    return {'success': False, 'message': f'未注册的 purchase 动作: {action}'}

def _registered_router_sales(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.application.sales_app_service import SalesAppService
    svc = SalesAppService()
    if action in ('query', 'list', 'get_orders'):
        return svc.query(status=params.get('status'), customer_id=params.get('customer_id'), customer_name=params.get('customer_name'), keyword=str(params.get('keyword') or params.get('search') or '').strip() or None, page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20))
    if action == 'quote':
        return svc.quote(dict(params or {}))
    if action == 'confirm':
        return svc.confirm(int(params.get('order_id') or 0))
    if action == 'deliver':
        return svc.deliver(int(params.get('order_id') or 0), int(params.get('item_id') or 0), float(params.get('quantity') or 0.0), warehouse_id=int(params.get('warehouse_id') or 0), idempotency_key=params.get('idempotency_key'))
    if action == 'invoice':
        return svc.invoice(int(params.get('order_id') or 0))
    if action == 'credit_note':
        return svc.credit_note(int(params.get('order_id') or 0))
    if action == 'payment':
        amount = params.get('amount')
        return svc.payment(int(params.get('order_id') or 0), float(amount) if amount is not None else None)
    if action == 'refund':
        return svc.refund(int(params.get('allocation_id') or 0))
    if action == 'cancel':
        return svc.cancel(int(params.get('order_id') or 0))
    if action == 'execute_closed_loop':
        return svc.execute_closed_loop(dict(params['payload']))
    return {'success': False, 'message': f'未注册的 sales 动作: {action}'}

def _registered_router_reports(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.services.report_service import ReportService
    svc = ReportService()
    if action == 'sales_summary':
        return svc.get_sales_report(start_date=params.get('start_date'), end_date=params.get('end_date'), group_by=str(params.get('group_by') or 'product'), customer_id=params.get('customer_id'))
    if action == 'inventory_summary':
        return svc.get_inventory_report(warehouse_id=params.get('warehouse_id'), category=params.get('category'))
    if action == 'purchase_summary':
        return svc.get_purchase_report(start_date=params.get('start_date'), end_date=params.get('end_date'), group_by=str(params.get('group_by') or 'supplier'))
    if action == 'dashboard':
        return svc.get_dashboard_summary()
    if action == 'export':
        return svc.export_to_excel(report_type=str(params.get('report_type') or 'report'), data=params.get('data') or [], filename=str(params.get('filename') or 'report'))
    return {'success': False, 'message': f'未注册的 reports 动作: {action}'}

def _registered_router_finance(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_finance_route':
        from app.fastapi_routes import finance as finance_route
        svc = finance_route._svc()
    else:
        from app.application.finance_app_service import FinanceAppService
        svc = FinanceAppService()
    if action in ('list_transactions', 'list', 'query', 'get_transactions'):
        return _facade().cast('dict[Any, Any]', svc.list_transactions(transaction_type=params.get('transaction_type'), status=params.get('status'), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 20)))
    if action == 'create_transaction':
        return _facade().cast('dict[Any, Any]', svc.create_transaction(dict(params or {})))
    if action == 'update_transaction':
        transaction_id = int(params.get('transaction_id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'transaction_id'}
        return _facade().cast('dict[Any, Any]', svc.update_transaction(transaction_id, payload))
    if action == 'delete_transaction':
        return _facade().cast('dict[Any, Any]', svc.delete_transaction(int(params.get('transaction_id') or 0)))
    if action in ('ledger_query', 'query_ledger'):
        from app.services.accounting_services import query_financial_ledger
        return query_financial_ledger(**dict(params or {}))
    if action == 'journal_entry_create':
        from app.services.accounting_services import create_journal_entry
        return create_journal_entry(dict(params or {}))
    if action == 'journal_entry_reverse':
        from app.services.accounting_services import journal_entry_reverse
        entry_id = int(params.get('entry_id') or params.get('id') or 0)
        if entry_id <= 0:
            return {'success': False, 'message': '缺少 entry_id'}
        return journal_entry_reverse(entry_id, description=params.get('description'))
    if action == 'aging_report':
        from app.services.accounting_services import aging_report
        raw_type = str(params.get('account_type') or params.get('party_type') or '应收').strip()
        if raw_type in ('应收', 'receivable', '客户'):
            party_type = 'receivable'
        elif raw_type in ('应付', 'payable', '供应商'):
            party_type = 'payable'
        else:
            party_type = raw_type
        party_id = int(params.get('party_id') or params.get('customer_id') or 0)
        return aging_report(party_type=party_type, party_id=party_id)
    if action == 'chart_seed':
        from app.services.accounting_services import seed_default_chart_of_accounts
        return seed_default_chart_of_accounts()
    return {'success': False, 'message': f'未注册的 finance 动作: {action}'}
