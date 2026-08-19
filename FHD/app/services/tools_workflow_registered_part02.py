# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.tools_workflow_registered')

def _registered_router_mrp(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.services.manufacturing_service import ManufacturingService
    svc = ManufacturingService()

    def _opt_int(value: _facade().Any) -> int | None:
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if action == 'create_bom':
        return svc.create_bom(dict(params or {}))
    if action == 'query_boms':
        return svc.query_boms(status=params.get('status'), product_id=_opt_int(params.get('product_id')), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 50))
    if action == 'get_bom':
        bom_id = int(params.get('bom_id') or params.get('id') or 0)
        if bom_id <= 0:
            return {'success': False, 'message': '缺少 bom_id'}
        return svc.get_bom(bom_id)
    if action == 'create_order':
        return svc.create_order(dict(params or {}))
    if action == 'confirm_order':
        order_id = int(params.get('order_id') or 0)
        if order_id <= 0:
            return {'success': False, 'message': '缺少 order_id'}
        return svc.confirm_order(order_id)
    if action == 'consume':
        order_id = int(params.get('order_id') or 0)
        warehouse_id = int(params.get('warehouse_id') or 0)
        if order_id <= 0:
            return {'success': False, 'message': '缺少 order_id'}
        return svc.consume(order_id=order_id, warehouse_id=warehouse_id, operator=params.get('operator'))
    if action == 'finish':
        order_id = int(params.get('order_id') or 0)
        warehouse_id = int(params.get('warehouse_id') or 0)
        if order_id <= 0:
            return {'success': False, 'message': '缺少 order_id'}
        return svc.finish(order_id=order_id, warehouse_id=warehouse_id, operator=params.get('operator'))
    if action == 'query_orders':
        return svc.query_orders(status=params.get('status'), product_id=_opt_int(params.get('product_id')), page=int(params.get('page') or 1), per_page=int(params.get('per_page') or 50))
    return {'success': False, 'message': f'未注册的 mrp 动作: {action}'}

def _registered_router_suppliers(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.application.facades.inventory_facade import PurchaseService
    svc = PurchaseService()
    if action in ('query', 'query_suppliers', 'list', 'list_suppliers'):
        return svc.get_suppliers(status=params.get('status'), keyword=str(params.get('keyword') or params.get('search') or '').strip() or None)
    if action == 'get_supplier':
        supplier_id = int(params.get('supplier_id') or params.get('id') or 0)
        if supplier_id <= 0:
            return {'success': False, 'message': '缺少 supplier_id'}
        result = svc.get_supplier(supplier_id)
        if isinstance(result, dict):
            return result
        return {'success': True, 'data': result}
    return {'success': False, 'message': f'未注册的 suppliers 动作: {action}'}

def _registered_router_shipment_records(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_shipment_records_route':
        from app.fastapi_routes import shipment_orders
        svc = shipment_orders._svc()
    else:
        from app.bootstrap import get_shipment_app_service
        svc = get_shipment_app_service()
    if action in ('list', 'query'):
        unit = str(params.get('unit') or params.get('unit_name') or '').strip() or None
        return {'success': True, 'data': svc.get_shipment_records(unit)}
    if action == 'create':
        unit_name = str(params.get('unit_name') or params.get('purchase_unit') or '').strip()
        if not unit_name:
            return {'success': False, 'message': '缺少 unit_name'}
        products = params.get('products') or params.get('items') or []
        if not isinstance(products, list):
            products = []
        return _facade().cast('dict[Any, Any]', svc.create_shipment(unit_name=unit_name, items_data=products, contact_person=params.get('contact_person'), contact_phone=params.get('contact_phone')))
    if action == 'update':
        record_id = int(params.get('id') or 0)
        payload = {k: v for (k, v) in params.items() if k != 'id'}
        return _facade().cast('dict[Any, Any]', svc.update_shipment_record(record_id=record_id, **payload))
    if action == 'delete':
        return _facade().cast('dict[Any, Any]', svc.delete_shipment_record(int(params.get('id') or 0)))
    if action == 'export':
        return _facade().cast('dict[Any, Any]', svc.export_shipment_records(unit_name=str(params.get('unit') or params.get('unit_name') or '').strip() or None, template_id=params.get('template_id'), status_filter=params.get('status')))
    return {'success': False, 'message': f'未注册的 shipment_records 动作: {action}'}

def _registered_router_shipment_orders(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if str(runtime_context.get('service_source') or '') == 'fastapi_shipment_orders_route':
        from app.fastapi_routes import shipment_orders
        svc = shipment_orders._svc()
    else:
        from app.bootstrap import get_shipment_app_service
        svc = get_shipment_app_service()
    if action == 'generate':
        unit_name = str(params.get('unit_name') or params.get('purchase_unit') or '').strip()
        products = params.get('products') or params.get('items') or []
        if not unit_name:
            return {'success': False, 'message': '缺少 unit_name'}
        if not isinstance(products, list) or not products:
            return {'success': False, 'message': 'products 须为非空数组'}
        gen_kwargs: dict[str, _facade().Any] = {'unit_name': unit_name, 'products': products, 'date': params.get('date')}
        if params.get('template_name'):
            gen_kwargs['template_name'] = params.get('template_name')
        elif params.get('template'):
            gen_kwargs['template_name'] = params.get('template')
        if params.get('template_id'):
            gen_kwargs['template_id'] = params.get('template_id')
        if params.get('preferred_template') or params.get('template'):
            gen_kwargs['preferred_template'] = params.get('preferred_template') or params.get('template')
        if params.get('order_number'):
            gen_kwargs['order_number'] = params.get('order_number')
        return _facade().cast('dict[Any, Any]', svc.generate_shipment_document(**gen_kwargs))
    if action == 'generate_batch':
        shipments = params.get('shipments') or []
        if not isinstance(shipments, list) or not shipments:
            return {'success': False, 'message': 'shipments 不能为空'}
        ok_count = 0
        errors: list[dict[str, _facade().Any]] = []
        for (idx, shipment) in enumerate(shipments):
            if not isinstance(shipment, dict):
                errors.append({'index': idx, 'error': '条目必须是对象'})
                continue
            unit_name = str(shipment.get('unit_name') or shipment.get('customer_name') or '').strip()
            products = shipment.get('products') or shipment.get('items') or []
            if not unit_name:
                errors.append({'index': idx, 'error': '单位名称不能为空'})
                continue
            if not products:
                errors.append({'index': idx, 'error': '产品列表不能为空'})
                continue
            try:
                batch_kwargs: dict[str, _facade().Any] = {'unit_name': unit_name, 'products': products, 'date': shipment.get('date')}
                if shipment.get('template_name'):
                    batch_kwargs['template_name'] = shipment.get('template_name')
                if shipment.get('template_id'):
                    batch_kwargs['template_id'] = shipment.get('template_id')
                result = svc.generate_shipment_document(**batch_kwargs)
                if result.get('success'):
                    ok_count += 1
                else:
                    errors.append({'index': idx, 'error': result.get('message', '生成失败')})
            except _facade().RECOVERABLE_ERRORS as err:
                _facade().logger.exception('shipment_orders.generate_batch[%s]: %s', idx, err)
                errors.append({'index': idx, 'error': str(err)})
        return {'success': ok_count > 0 or not errors, 'data': {'processed': ok_count, 'total': len(shipments), 'errors': errors}}
    if action == 'print':
        file_path = str(params.get('file_path') or '').strip()
        if not file_path:
            return {'success': False, 'message': '文件路径不能为空'}
        order_id = params.get('order_id')
        if order_id:
            shipment_id = int(order_id)
            result = dict(svc.mark_as_printed(shipment_id, printer_name=str(params.get('printer_name') or '')))
            result['file_path'] = file_path
            if 'updated' not in result:
                result['updated'] = bool(result.get('success'))
            return result
        return {'success': True, 'message': '发货单打印请求已完成，但未更新记录（缺少 order_id）', 'printed_at': _facade().datetime.now().isoformat(), 'file_path': file_path, 'updated': False, 'warning': '缺少 order_id，已跳过数据库状态更新'}
    if action == 'clear_shipment':
        purchase_unit = str(params.get('purchase_unit') or params.get('unit_name') or '').strip()
        if not purchase_unit:
            return {'success': False, 'message': '缺少购买单位参数'}
        result = dict(svc.clear_shipment_by_unit(purchase_unit) or {})
        result.setdefault('purchase_unit', purchase_unit)
        return result
    if action == 'set_sequence':
        sequence = int(params.get('sequence', 1))
        result = dict(svc.set_order_sequence(sequence) or {})
        result.setdefault('sequence', sequence)
        return result
    if action == 'reset_sequence':
        return dict(svc.reset_order_sequence() or {})
    if action == 'clear_all':
        return dict(svc.clear_all_orders() or {})
    if action == 'delete':
        shipment_id = int(params.get('id') or params.get('shipment_id') or params.get('order_id') or 0)
        result = dict(svc.delete_shipment(shipment_id) or {})
        result.setdefault('deleted_id', shipment_id)
        return result
    return {'success': False, 'message': f'未注册的 shipment_orders 动作: {action}'}

def _registered_router_business_docking_family(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action in ('view',):
        return {'success': True, 'redirect': '/console?view=business-docking'}
    file_path = str(params.get('file_path') or '').strip()
    if not file_path:
        return {'success': False, 'message': '缺少参数：file_path'}
    from app.services.document_templates_service import _extract_excel_all_sheets_preview, _extract_excel_grid_preview, _extract_excel_grid_style_cache, _extract_structured_excel_preview, _list_excel_sheet_names
    if not _facade().os.path.exists(file_path):
        return {'success': False, 'message': f'文件不存在：{file_path}'}
    sheet_name = str(params.get('sheet_name') or '').strip() or None
    structured = _extract_structured_excel_preview(file_path, sheet_name=sheet_name, sample_limit=8)
    grid_preview = _extract_excel_grid_preview(file_path, sheet_name=sheet_name, max_rows=24, max_cols=14)
    style_cache = _extract_excel_grid_style_cache(file_path, sheet_name=sheet_name, max_rows=24, max_cols=14)
    all_sheets = _extract_excel_all_sheets_preview(file_path, sample_limit=8, max_rows=24, max_cols=14)
    artifact: dict[str, _facade().Any] = {'artifact_type': 'template_analysis', 'name': _facade().os.path.basename(file_path) or 'template-analysis', 'source': f'{action}.template_extract', 'uri': file_path, 'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'summary': 'Excel 模板结构分析结果', 'fields': structured.get('fields') or [], 'preview': {'sample_rows': structured.get('sample_rows') or [], 'grid_preview': grid_preview, 'sheet_names': _list_excel_sheet_names(file_path)}, 'metadata': {'parser_used': 'template_extract', 'sheet_name': sheet_name or ''}}
    return {'success': True, 'file_path': file_path, 'sheet_names': artifact['preview']['sheet_names'], 'fields': structured.get('fields') or [], 'sample_rows': structured.get('sample_rows') or [], 'grid_preview': grid_preview, 'grid_style_cache': style_cache, 'sheets': all_sheets, 'artifacts': [artifact]}

def _registered_router_business_event(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action == 'print_label':
        from app.neuro_bus.domains.print_domain import get_print_domain
        job_id = str(params.get('job_id') or '').strip() or str(_facade().uuid.uuid4())
        document_name = str(params.get('document_name') or 'document').strip() or 'document'
        printer_id = str(params.get('printer_id') or 'default').strip() or 'default'
        copies = max(1, int(params.get('copies') or 1))
        ok = get_print_domain().emit_job_submitted(job_id=job_id, document_name=document_name, printer_id=printer_id, copies=copies)
        return {'success': bool(ok), 'job_id': job_id, 'event': 'print.job.submitted'}
    if action == 'inventory_update':
        from app.neuro_bus.domains.inventory_domain import get_inventory_domain
        ok = get_inventory_domain().emit_stock_changed(product_id=str(params.get('product_id') or '').strip(), warehouse_id=str(params.get('warehouse_id') or 'default').strip() or 'default', delta=int(params.get('delta') or 0), reason=str(params.get('reason') or 'api_business'), new_quantity=int(params.get('new_quantity') or 0))
        return {'success': bool(ok), 'event': 'inventory.changed'}
    if action == 'shipment_create':
        from app.neuro_bus.application_neuro_bridge import publish_neuro_event
        payload = {'unit_name': str(params.get('unit_name') or '').strip(), 'items': list(params.get('items') or []), 'contact_person': str(params.get('contact_person') or '').strip(), 'contact_phone': str(params.get('contact_phone') or '').strip()}
        ok = publish_neuro_event('shipment.created', payload, 'shipment')
        if not ok:
            _facade().logger.info('business shipment.create: neuro publish skipped or failed (stack off?)')
        return {'success': bool(ok), 'published': ok, 'event': 'shipment.created'}
    return {'success': False, 'message': f'未知 business_event action: {action}'}

def _registered_router_system_maintenance(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action in {'set_default_printer', 'enable_startup', 'disable_startup'}:
        from app.application.facades.session_facade import get_system_service
        system_svc = get_system_service()
        if action == 'set_default_printer':
            result = dict(system_svc.set_default_printer(str(params.get('printer_name') or '').strip()))
            result['http_status_code'] = 200 if result.get('success') else 500
            return result
        if action == 'enable_startup':
            result = dict(system_svc.enable_startup())
            result['http_status_code'] = 200 if result.get('success') else 500
            return result
        result = dict(system_svc.disable_startup())
        result['http_status_code'] = 200 if result.get('success') else 500
        return result
    if action in {'backup_database', 'delete_database_backup', 'restore_database'}:
        from app.application.facades.session_facade import get_database_service
        database_svc = get_database_service()
        if action == 'backup_database':
            result = dict(database_svc.backup_database())
            result['http_status_code'] = 200 if result.get('success') else 500
            return result
        if action == 'delete_database_backup':
            result = dict(database_svc.delete_backup(str(params.get('backup_file') or '').strip()))
            result['http_status_code'] = 200 if result.get('success') else 500
            return result
        result = dict(database_svc.restore_database(str(params.get('backup_file') or '').strip()))
        result['http_status_code'] = 200 if result.get('success') else 400
        return result
    if action == 'clear_performance_cache':
        from app.utils.performance.performance_initializer import get_performance_optimizer
        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {'success': False, 'message': 'Redis 缓存未初始化', 'http_status_code': 503}
        pattern = str(params.get('pattern') or '').strip()
        if pattern:
            cleared = optimizer.redis_cache.clear_pattern(pattern)
            message = f"已清除模式 '{pattern}' 的缓存 ({cleared} 个键)"
        else:
            optimizer.redis_cache.clear_local_cache()
            message = '已清除本地缓存'
        return {'success': True, 'message': message, 'http_status_code': 200}
    if action == 'invalidate_performance_cache':
        from app.utils.performance.performance_initializer import get_performance_optimizer
        optimizer = get_performance_optimizer()
        if not optimizer.redis_cache:
            return {'success': False, 'message': 'Redis 缓存未初始化', 'http_status_code': 503}
        keys = list(params.get('keys') or [])
        deleted = optimizer.redis_cache.delete(*keys)
        return {'success': True, 'data': {'deleted_count': deleted, 'requested_keys': len(keys)}, 'message': f'已删除 {deleted} 个缓存键', 'http_status_code': 200}
    if action == 'reinitialize_performance':
        from app.utils.performance.performance_initializer import init_performance_optimization
        optimizer = init_performance_optimization()
        return {'success': True, 'message': '性能优化系统已重新初始化', 'data': optimizer.get_status(), 'http_status_code': 200}
    return {'success': False, 'message': f'未知 system_maintenance action: {action}'}

def _registered_router_excel_analyzer(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action != 'analyze':
        return {'success': False, 'message': f'未知 excel_analyzer action: {action}'}
    file_path = str(params.get('file_path') or '').strip()
    if not file_path:
        return {'success': False, 'message': 'excel_analyzer.analyze 缺少 file_path 参数'}
    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import get_excel_analyzer_skill
    except ImportError:
        return {'success': False, 'message': 'Excel Analyzer Skill 未正确安装'}
    result = get_excel_analyzer_skill().execute(file_path=file_path, sheet_name=params.get('sheet_name'), output_json=params.get('output_json'))
    if isinstance(result, dict):
        result.setdefault('file_path', file_path)
    return result if isinstance(result, dict) else {'success': False, 'message': '技能返回值无效'}

def _registered_router_excel_toolkit(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    normalized = str(action or 'view').strip().lower() or 'view'
    if normalized not in {'view', 'merged', 'styles', 'structure'}:
        return {'success': False, 'message': f'未知 excel_toolkit action: {action}'}
    file_path = str(params.get('file_path') or '').strip()
    if not file_path:
        return {'success': False, 'message': f'excel_toolkit.{normalized} 缺少 file_path 参数'}
    try:
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {'success': False, 'message': 'Excel Toolkit Skill 未正确安装'}
    kwargs = {}
    if params.get('max_rows') is not None:
        kwargs['max_rows'] = params.get('max_rows')
    result = get_excel_toolkit_skill().execute(file_path=file_path, action=normalized, sheet_name=params.get('sheet_name'), **kwargs)
    if isinstance(result, dict):
        result.setdefault('file_path', file_path)
    return result if isinstance(result, dict) else {'success': False, 'message': '技能返回值无效'}

def _registered_router_label_template_generator(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action != 'execute':
        return {'success': False, 'message': f'未知 label_template_generator action: {action}'}
    image_path = str(params.get('image_path') or '').strip()
    if not image_path:
        return {'success': False, 'message': 'label_template_generator.execute 缺少 image_path 参数'}
    try:
        from app.infrastructure.skills.label_template_generator import get_label_template_generator_skill
    except ImportError:
        return {'success': False, 'message': 'Label Template Generator Skill 未正确安装'}
    result = get_label_template_generator_skill().execute(image_path=image_path, class_name=params.get('class_name') or 'LabelTemplateGenerator', output_file=params.get('output_file'), enable_ocr=bool(params.get('enable_ocr', True)), verbose=bool(params.get('verbose', False)))
    if isinstance(result, dict):
        result.setdefault('image_path', image_path)
    return result if isinstance(result, dict) else {'success': False, 'message': '技能返回值无效'}

def _registered_router_document_template(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    payload = dict(params or {})
    if action == 'create':
        from app.legacy.routes.document_templates_compat import run_archive_template_create
        (data, status_code) = run_archive_template_create(payload)
    elif action == 'update':
        from app.legacy.routes.document_templates_compat import run_archive_template_update
        (data, status_code) = run_archive_template_update(payload)
    elif action == 'delete':
        from app.legacy.routes.document_templates_compat import run_archive_template_delete
        (data, status_code) = run_archive_template_delete(payload, base_dir=str(runtime_context.get('template_base_dir') or '') or None)
    elif action in ('ingest', 'upload'):
        from app.application.office_template_ingest_app_service import ingest_office_bytes_to_template_library, ingest_office_path_to_template_library
        file_path = str(payload.get('file_path') or payload.get('original_file_path') or '').strip()
        file_body = payload.get('file_body')
        template_name = str(payload.get('template_name') or payload.get('name') or '').strip()
        template_scope = str(payload.get('template_scope') or payload.get('business_scope') or '').strip()
        source = str(payload.get('source') or 'document_template_ingest').strip() or 'document_template_ingest'
        if isinstance(file_body, (bytes, bytearray)):
            (data, status_code) = ingest_office_bytes_to_template_library(file_body=bytes(file_body), filename=str(payload.get('filename') or 'upload.bin'), template_name=template_name, template_scope=template_scope, source=source)
        elif file_path:
            (data, status_code) = ingest_office_path_to_template_library(file_path, template_name=template_name, template_scope=template_scope, source=source)
        else:
            return {'success': False, 'message': '缺少 file_path 或 file_body'}
    else:
        return {'success': False, 'message': f'未知 document_template action: {action}'}
    result = dict(data or {})
    result['http_status_code'] = int(status_code or (200 if result.get('success') else 400))
    return result
