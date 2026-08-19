# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.tools_workflow_registered')

def _registered_router_ocr(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    try:
        from app.fastapi_routes.ocr import _get_ocr_service
        if action == 'request':
            request_id = str(params.get('request_id') or '').strip()
            image_url = str(params.get('image_url') or '').strip()
            if not request_id:
                return {'success': False, 'message': '缺少 request_id'}
            if not image_url:
                return {'success': False, 'message': '缺少 image_url'}
            ocr_type = str(params.get('ocr_type') or 'general').strip() or 'general'
            user_id = str(params.get('user_id') or runtime_context.get('user_id') or 'system').strip()
            from app.neuro_bus.domains.ocr_domain import get_ocr_domain
            ok = get_ocr_domain().emit_ocr_requested(request_id=request_id, image_url=image_url, ocr_type=ocr_type, user_id=user_id or 'system')
            return {'success': bool(ok), 'message': 'OCR 请求已发布' if ok else 'OCR 请求发布失败', 'request_id': request_id, 'image_url': image_url, 'ocr_type': ocr_type, 'user_id': user_id or 'system', 'event': 'ocr.requested', 'published': bool(ok)}
        service = _get_ocr_service()
        if action == 'recognize':
            file_path = str(params.get('file_path') or '').strip()
            if not file_path:
                return {'success': False, 'message': '缺少 file_path'}
            result = dict(service.recognize_file(file_path) or {})
            if result.get('success'):
                text = str(result.get('text') or '')
                result.setdefault('artifacts', [])
                result['artifacts'] = list(result['artifacts']) + [_facade()._ocr_artifact_payload(text=text, file_path=str(result.get('file_path') or file_path), confidence=result.get('confidence', result.get('ocr_confidence', 0)))]
            return result
        if action == 'extract':
            text = str(params.get('text') or '').strip()
            if not text:
                return {'success': False, 'message': '缺少 text'}
            data = dict(service.extract_structured_data(text) or {})
            return {'success': True, 'message': '提取成功', 'data': data}
        if action == 'analyze':
            text = str(params.get('text') or '').strip()
            if not text:
                return {'success': False, 'message': '缺少 text'}
            data = dict(service.analyze_text(text) or {})
            return {'success': True, 'message': '分析成功', 'data': data}
        if action == 'recognize_and_extract':
            file_path = str(params.get('file_path') or '').strip()
            if not file_path:
                return {'success': False, 'message': '缺少 file_path'}
            recognize_result = dict(service.recognize_file(file_path) or {})
            if not recognize_result.get('success'):
                return recognize_result
            text = str(recognize_result.get('text') or '')
            structured_data = dict(service.extract_structured_data(text) or {})
            analysis = dict(service.analyze_text(text) or {})
            return {'success': True, 'message': '识别和提取成功', 'text': text, 'data': structured_data, 'analysis': analysis, 'artifacts': [_facade()._ocr_artifact_payload(text=text, file_path=str(recognize_result.get('file_path') or file_path), structured_data=structured_data, analysis=analysis, confidence=analysis.get('confidence', 0))]}
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.error('ocr 工具执行失败: %s', err, exc_info=True)
        return {'success': False, 'message': str(err), 'error_code': 'ocr_exception'}
    return {'success': False, 'message': f'未知 ocr action: {action}'}

def _execute_excel_import_records(records: list[dict[str, _facade().Any]]) -> dict:
    if not records:
        return {'success': False, 'message': '没有可导入的记录'}
    try:
        from app.bootstrap import get_products_service
        products_service = get_products_service()
        customer_service = None
        customer_service_error = ''
        try:
            from app.bootstrap import get_customer_app_service
            customer_service = get_customer_app_service()
        except _facade().RECOVERABLE_ERRORS as customer_err:
            customer_service_error = str(customer_err)
            _facade().logger.warning('客户服务不可用，降级为仅产品入库: %s', customer_err)
        created_units = 0
        created_products = 0
        skipped_products = 0
        touched_units: set[str] = set()
        for row in records:
            unit_name = str(row.get('unit_name') or '').strip()
            product_name = str(row.get('product_name') or '').strip()
            model_number = str(row.get('model_number') or '').strip().upper()
            unit_price = float(row.get('unit_price') or 0.0)
            touched_units.add(unit_name)
            if customer_service is not None:
                matched = customer_service.match_purchase_unit(unit_name)
                if not matched:
                    create_unit = customer_service.create({'customer_name': unit_name})
                    if create_unit.get('success'):
                        created_units += 1
            exists_result = products_service.get_products(unit_name=unit_name, model_number=model_number or None, keyword=product_name or model_number or None, page=1, per_page=5)
            existed = False
            if exists_result.get('success'):
                rows_data = exists_result.get('data') or []
                for item in rows_data:
                    item_name = str(item.get('name') or item.get('product_name') or '').strip()
                    item_model = str(item.get('model_number') or '').strip().upper()
                    if model_number and item_model == model_number:
                        existed = True
                        break
                    if product_name and item_name == product_name:
                        existed = True
                        break
            if existed:
                skipped_products += 1
                continue
            create_product = products_service.create_product({'name': product_name or model_number, 'product_name': product_name or model_number, 'product_code': model_number or None, 'model_number': model_number or None, 'unit_price': unit_price, 'price': unit_price, 'unit': unit_name})
            if create_product.get('success'):
                created_products += 1
        return {'success': True, 'message': 'Excel 导入完成', 'imported_count': len(records), 'data': {'result': {'records': len(records), 'touched_units': len(touched_units), 'created_units': created_units, 'created_products': created_products, 'skipped_products': skipped_products, 'unit_service_available': customer_service is not None, 'unit_service_error': customer_service_error}}}
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.error('Excel 导入执行失败: %s', err, exc_info=True)
        return {'success': False, 'message': f'导入执行失败：{str(err)}'}

def _registered_router_excel_import(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action in {'import_delivery_notes', 'execute_delivery_etl'}:
        file_path = str(params.get('file_path') or '').strip()
        notes = params.get('notes')
        if not file_path and (not isinstance(notes, list)):
            return {'success': False, 'message': '缺少 file_path 或 notes'}
        try:
            from app.application.shipment_excel_etl_app_service import get_shipment_excel_etl_app_service
            return get_shipment_excel_etl_app_service().execute(file_path or '', import_products=bool(params.get('import_products', True)), import_shipments=bool(params.get('import_shipments', True)), notes=notes if isinstance(notes, list) else None)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error('shipment delivery etl failed: %s', err, exc_info=True)
            return {'success': False, 'message': f'送货单闭环失败：{err}'}
    if action == 'preview_delivery_notes':
        file_path = str(params.get('file_path') or '').strip()
        if not file_path:
            return {'success': False, 'message': '缺少 file_path'}
        try:
            from app.application.shipment_excel_etl_app_service import get_shipment_excel_etl_app_service
            return get_shipment_excel_etl_app_service().preview(file_path)
        except _facade().RECOVERABLE_ERRORS as err:
            return {'success': False, 'message': str(err)}
    if action == 'execute_import':
        pending_import_id = str(params.get('pending_import_id') or '').strip()
        if not pending_import_id:
            return {'success': False, 'message': '缺少 pending_import_id 参数'}
        from app.application import get_ai_chat_app_service
        ai_chat_service = get_ai_chat_app_service()
        pending_imports = getattr(ai_chat_service, '_pending_excel_imports', {})
        import_data = pending_imports.get(pending_import_id)
        if not import_data:
            return {'success': False, 'message': '未找到待处理的导入数据或已过期'}
        if str(import_data.get('kind') or '') == 'shipment_delivery_etl':
            try:
                from app.application.shipment_excel_etl_app_service import get_shipment_excel_etl_app_service
                result = get_shipment_excel_etl_app_service().execute(str(import_data.get('file_path') or ''), notes=import_data.get('notes') if isinstance(import_data.get('notes'), list) else None)
                if result.get('success'):
                    pending_imports.pop(pending_import_id, None)
                return result
            except _facade().RECOVERABLE_ERRORS as err:
                return {'success': False, 'message': f'送货单闭环失败：{err}'}
        records = import_data.get('records', [])
        if not isinstance(records, list):
            return {'success': False, 'message': '待导入记录格式错误'}
        result = _facade()._execute_excel_import_records([r for r in records if isinstance(r, dict)])
        if result.get('success'):
            pending_imports.pop(pending_import_id, None)
        return result
    if action == 'import_records':
        records = params.get('records')
        if not isinstance(records, list):
            return {'success': False, 'message': 'records 必须是数组'}
        return _facade()._execute_excel_import_records([r for r in records if isinstance(r, dict)])
    return {'success': False, 'message': f'未知 excel_import action: {action}'}

def _registered_router_unit_products_import(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action != 'execute_import':
        return {'success': False, 'message': f'未知 unit_products_import action: {action}'}
    saved_name = str(params.get('saved_name') or '').strip()
    unit_name = str(params.get('unit_name') or '').strip()
    if not saved_name:
        return {'success': False, 'message': '缺少 saved_name 参数'}
    if not unit_name:
        return {'success': False, 'message': '缺少 unit_name 参数'}
    try:
        from app.application import get_unit_products_import_app_service
        service = get_unit_products_import_app_service()
        result = service.import_unit_products(saved_name=saved_name, unit_name=unit_name, create_purchase_unit=bool(params.get('create_purchase_unit', True)), skip_duplicates=bool(params.get('skip_duplicates', True)))
        if result.get('success'):
            created_unit = bool(result.get('created_unit', False))
            imported_count = int(result.get('created_products') or result.get('imported') or 0)
            result.setdefault('created_customers', 1 if created_unit else 0)
            result.setdefault('created_products', imported_count)
            data = result.get('data')
            if not isinstance(data, dict):
                data = {}
            data.setdefault('unit_name', unit_name)
            data.setdefault('saved_name', saved_name)
            data.setdefault('created_unit', created_unit)
            data.setdefault('imported', int(result.get('imported') or imported_count))
            data.setdefault('skipped_duplicates', int(result.get('skipped_duplicates') or 0))
            result['data'] = data
        return result
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.error('unit products 导入执行失败: %s', err, exc_info=True)
        return {'success': False, 'message': f'导入执行失败：{str(err)}'}

class _WorkflowRouterMap(dict):
    _hidden_keys = {'employee', 'business_db'}

    def keys(self):
        return [key for key in super().keys() if key not in self._hidden_keys]

def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None=None) -> dict:
    """统一 dispatcher（供 WorkflowEngine 与 /api/tools/execute 复用）。"""
    from app.application.normal_chat_dispatch import resolve_tool_execution_profile
    params = dict(params or {})
    runtime_context = dict(params.pop('_runtime_context', None) or {})
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get('message') or '').strip()
    router = _facade()._REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router is not None:
        result = router(action, params, runtime_context, profile, user_message)
        if tool_id == 'business_db' and action == 'write' and isinstance(result, dict):
            payload = params.get('payload')
            if isinstance(payload, dict):
                result = _facade()._remember_business_db_target(runtime_context, _facade()._normalize_business_db_entity(params.get('entity'), user_message), str(params.get('operation') or params.get('op') or 'create').strip().lower(), payload, result)
        return result
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool
        if is_employee_tool(tool_id):
            workspace_root = runtime_context.get('workspace_root')
            raw = execute_employee_tool(tool_id, {**params, 'task': params.get('task') or user_message}, str(workspace_root) if workspace_root else None)
            import json
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {'success': False, 'message': raw}
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug('employee tool direct dispatch skipped tool=%s', tool_id, exc_info=True)
    return {'success': False, 'message': f'未注册的工具动作: {tool_id}.{action}'}
