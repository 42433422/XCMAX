# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.services.tools_workflow_registered')

def _registered_router_template_preview(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action == 'view':
        return {'success': True, 'redirect': '/console?view=template-preview'}
    from app.application import get_template_app_service
    svc = get_template_app_service()
    if action in ('list', 'query'):
        result = svc.get_templates()
        if isinstance(result, dict):
            return result
        return {'success': True, 'data': result}
    if action == 'create':
        import json
        import re
        import uuid
        from datetime import datetime
        from sqlalchemy import text
        from app.db.session import get_db
        from app.services.document_templates_service import _ensure_template_tables_ready, _infer_business_scope, _validate_required_terms
        excel_analysis = params.get('excel_analysis')
        if not isinstance(excel_analysis, dict):
            excel_analysis = runtime_context.get('excel_analysis')
        if not isinstance(excel_analysis, dict):
            fallback_ctx = runtime_context.get('last_excel_analysis_context')
            if isinstance(fallback_ctx, dict):
                excel_analysis = fallback_ctx.get('result') if isinstance(fallback_ctx.get('result'), dict) else fallback_ctx
        excel_analysis = excel_analysis if isinstance(excel_analysis, dict) else {}
        sheets = excel_analysis.get('sheets')
        if not isinstance(sheets, list):
            preview_data = excel_analysis.get('preview_data') if isinstance(excel_analysis.get('preview_data'), dict) else {}
            if not isinstance(preview_data, dict):
                preview_data = {}
            sheets = preview_data.get('all_sheets') if isinstance(preview_data.get('all_sheets'), list) else []
        sheet_index = params.get('sheet_index')
        sheet_name = str(params.get('sheet_name') or '').strip()
        if sheet_index is None:
            text_message = str(params.get('order_text') or runtime_context.get('message') or '')
            m = re.search('第\\s*(\\d+)\\s*(个)?\\s*(sheet|表)', text_message, flags=re.I)
            if m:
                try:
                    sheet_index = int(m.group(1))
                except _facade().RECOVERABLE_ERRORS:
                    sheet_index = None
        selected_sheet = None
        if isinstance(sheet_index, int) and sheet_index > 0:
            for s in sheets or []:
                if int(s.get('sheet_index') or 0) == sheet_index:
                    selected_sheet = s
                    break
        if selected_sheet is None and sheet_name:
            for s in sheets or []:
                if str(s.get('sheet_name') or '').strip() == sheet_name:
                    selected_sheet = s
                    break
        if selected_sheet is None and sheets:
            selected_sheet = sheets[0]
        if not selected_sheet:
            return {'success': False, 'message': '未找到可用的 sheet 分析结果，请先执行分析Excel。'}
        picked_sheet_name = str(selected_sheet.get('sheet_name') or '').strip() or 'Sheet1'
        template_name = str(params.get('name') or params.get('template_name') or '').strip()
        if not template_name:
            template_name = f'{picked_sheet_name}-模板'
        fields = selected_sheet.get('fields') if isinstance(selected_sheet.get('fields'), list) else []
        preview_data = {'sheet_name': picked_sheet_name, 'selected_sheet_name': picked_sheet_name, 'sample_rows': selected_sheet.get('sample_rows') if isinstance(selected_sheet.get('sample_rows'), list) else [], 'grid_preview': selected_sheet.get('grid_preview') if isinstance(selected_sheet.get('grid_preview'), dict) else {}, 'grid_style_cache': selected_sheet.get('style_cache') if isinstance(selected_sheet.get('style_cache'), dict) else {}}
        template_type = str(params.get('template_type') or 'Excel').strip()
        business_scope = str(params.get('business_scope') or _infer_business_scope(template_type) or '').strip()
        source = str(params.get('source') or 'ai-natural-language').strip() or 'ai-natural-language'
        file_path = str(params.get('file_path') or excel_analysis.get('file_path') or '').strip() or None
        if business_scope:
            (valid, missing_terms) = _validate_required_terms({}, fields, business_scope)
            if not valid:
                return {'success': False, 'message': '必填字段未匹配，不能保存模板', 'business_scope': business_scope, 'missing_terms': missing_terms}
        analyzed_data = {'category': 'excel', 'source': source, 'business_scope': business_scope, 'fields': fields, 'preview_data': preview_data}
        editable_config = fields
        business_rules = {'business_scope': business_scope, 'source': source, 'selected_sheet_name': picked_sheet_name}
        _ensure_template_tables_ready()
        template_key = f"TPL_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"
        from app.infrastructure.templates.tenant_scope import templates_tenant_id_for_insert
        from app.infrastructure.tenant_scope import TenantScopeError
        try:
            tenant_id = templates_tenant_id_for_insert()
        except TenantScopeError:
            return {'success': False, 'message': '缺少租户上下文，无法创建模板'}
        with get_db() as db:
            result = db.execute(text('\n                    INSERT INTO templates (\n                        template_key, template_name, template_type,\n                        original_file_path, analyzed_data, editable_config,\n                        zone_config, merged_cells_config, style_config,\n                        business_rules, is_active, tenant_id\n                    ) VALUES (\n                        :template_key, :template_name, :template_type,\n                        :original_file_path, :analyzed_data, :editable_config,\n                        :zone_config, :merged_cells_config, :style_config,\n                        :business_rules, :is_active, :tenant_id\n                    )\n                '), {'template_key': template_key, 'template_name': template_name, 'template_type': template_type, 'original_file_path': file_path, 'analyzed_data': json.dumps(analyzed_data, ensure_ascii=False), 'editable_config': json.dumps(editable_config, ensure_ascii=False), 'zone_config': json.dumps({}, ensure_ascii=False), 'merged_cells_config': json.dumps({}, ensure_ascii=False), 'style_config': json.dumps({}, ensure_ascii=False), 'business_rules': json.dumps(business_rules, ensure_ascii=False), 'is_active': 1, 'tenant_id': tenant_id})
            template_id = result.lastrowid
            db.commit()
        return {'success': True, 'message': '已按指定 sheet 加入模板库', 'template': {'id': f'db:{template_id}', 'db_id': template_id, 'name': template_name, 'template_type': template_type, 'business_scope': business_scope, 'source': source, 'fields': fields, 'preview_data': preview_data}}
    return {'success': False, 'message': f'未注册的 template_preview 动作: {action}'}

def _registered_router_print(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action == 'workflow_label_dispatch':
        from app.application.print_app_service import get_print_application_service
        model_number = str(params.get('model_number') or '').strip()
        if not model_number:
            return {'success': False, 'message': 'model_number 不能为空'}
        quantity = max(1, min(100, int(params.get('quantity') or 1)))
        product_name = model_number
        specification: str | None = None
        unit = '个'
        try:
            from app.application import get_product_app_service
            products_result = get_product_app_service().search_products(keyword=model_number, filters={'per_page': 1})
            products = products_result.get('data') or [] if isinstance(products_result, dict) else products_result
            if isinstance(products, list) and products:
                product = products[0]
                if isinstance(product, dict):
                    product_name = str(product.get('name') or product.get('product_name') or model_number)
                    specification = str(product.get('specification') or product.get('spec') or '') or None
                    unit = str(product.get('unit') or '个')
        except _facade().RECOVERABLE_ERRORS as lookup_err:
            _facade().logger.warning('print.workflow_label_dispatch: 产品查找失败: %s', lookup_err)
        return dict(get_print_application_service().print_single_label(product_name=product_name, model_number=model_number or None, specification=specification, unit=unit, quantity=quantity) or {})
    if str(runtime_context.get('service_source') or '') == 'fastapi_print_route':
        from app.fastapi_routes import print_routes
        svc = print_routes._svc()
    else:
        from app.services import get_printer_service
        svc = get_printer_service()
    if action == 'view':
        return {'success': True, 'redirect': '/console?view=print'}
    if action in ('list', 'query'):
        return _facade().cast('dict[Any, Any]', svc.get_printers())
    if action == 'print_label':
        return _facade().cast('dict[Any, Any]', svc.print_label(str(params.get('file_path') or '').strip(), params.get('printer_name'), int(params.get('copies') or 1)))
    if action == 'print_document':
        return _facade().cast('dict[Any, Any]', svc.print_document(str(params.get('file_path') or '').strip(), params.get('printer_name'), bool(params.get('use_automation', False))))
    if action == 'test':
        return _facade().cast('dict[Any, Any]', svc.test_printer(str(params.get('printer_name') or '').strip()))
    if action == 'save_printer_selection':
        document_printer = params.get('document_printer')
        label_printer = params.get('label_printer')
        printers_result = dict(svc.get_printers() or {})
        printers = printers_result.get('printers', [])
        if not isinstance(printers, list):
            printers = []
        available_names = {(printer.get('name') or '').strip() for printer in printers if isinstance(printer, dict)}

        def is_valid(name: _facade().Any) -> bool:
            if name is None:
                return True
            value = str(name).strip()
            return value == '' or value in available_names
        if not is_valid(document_printer):
            return {'success': False, 'message': '发货单打印机不在当前可用打印机列表中'}
        if not is_valid(label_printer):
            return {'success': False, 'message': '标签打印机不在当前可用打印机列表中'}
        result = dict(svc.save_printer_selection(document_printer=str(document_printer).strip() if document_printer is not None else None, label_printer=str(label_printer).strip() if label_printer is not None else None) or {})
        result.update(dict(svc.classify_printers(printers) or {}))
        return result
    return {'success': False, 'message': f'未注册的 print 动作: {action}'}

def _registered_router_printer_list(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.services import get_system_service
    svc = get_system_service()
    if action == 'view':
        return {'success': True, 'redirect': '/console?view=printer-list'}
    if action in ('list', 'query'):
        return svc.get_printer_config()
    if action == 'set_default':
        return svc.set_default_printer(str(params.get('printer_name') or '').strip())
    return {'success': False, 'message': f'未注册的 printer_list 动作: {action}'}

def _registered_router_settings(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.services import get_system_service
    svc = get_system_service()
    if action == 'view':
        return {'success': True, 'redirect': '/console?view=settings'}
    if action in ('query', 'get_system_info'):
        return {'success': True, 'data': svc.get_system_info()}
    if action == 'get_startup_config':
        return {'success': True, 'data': svc.get_startup_config()}
    if action == 'enable_startup':
        return svc.enable_startup()
    if action == 'disable_startup':
        return svc.disable_startup()
    return {'success': False, 'message': f'未注册的 settings 动作: {action}'}

def _registered_router_employee(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.mod_sdk.employee_tool_registry import build_employee_tools_status
    if action in ('list', 'query'):
        status = build_employee_tools_status()
        return {'success': True, 'message': f"已发现 {status.get('registered_tool_count', 0)} 个可调用员工", 'data': status}
    if action != 'execute':
        return {'success': False, 'message': f'未注册的 employee 动作: {action}'}
    employee_id = str(params.get('employee_id') or params.get('pack_id') or params.get('tool_name') or params.get('id') or '').strip()
    status = build_employee_tools_status()
    installed = status.get('employee_pack_tools') or []
    if not employee_id and user_message:
        for item in installed:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get('pack_id') or item.get('tool_name') or '').strip()
            if candidate and candidate in user_message:
                employee_id = candidate
                break
    if not employee_id:
        return {'success': False, 'message': '缺少 employee_id，请先用 employee.list 查看可用员工，或明确指定员工包 ID。', 'data': {'available_employee_ids': [str(x.get('pack_id') or '') for x in installed if isinstance(x, dict) and x.get('pack_id')][:80]}}
    task = str(params.get('task') or params.get('user_request') or params.get('message') or user_message or '').strip()
    if not task:
        return {'success': False, 'message': '缺少 task：请说明要让员工执行什么任务。'}
    input_data = params.get('input') if isinstance(params.get('input'), dict) else {}
    payload = dict(input_data or {})
    for (key, value) in params.items():
        if key in {'employee_id', 'pack_id', 'tool_name', 'id', 'task', 'user_request', 'input'}:
            continue
        payload.setdefault(key, value)
    payload.setdefault('source', 'workflow_tool.employee')
    payload.setdefault('user_message', user_message)
    workspace_root = str(params.get('workspace_root') or runtime_context.get('workspace_root') or '').strip() or None
    raw_user_id = params.get('user_id') or runtime_context.get('user_id') or 0
    try:
        numeric_user_id = int(raw_user_id)
    except (TypeError, ValueError):
        numeric_user_id = 0
    from app.application.employee_runtime.executor import execute_employee_task_local
    result = execute_employee_task_local(employee_id, task, payload, user_id=numeric_user_id, workspace_root=workspace_root, session_id=str(runtime_context.get('session_id') or params.get('session_id') or '') or None)
    ok = bool(result.get('success')) and (not bool(result.get('blocked_by_risk_gate')))
    return {'success': ok, 'message': '员工执行完成' if ok else str(result.get('error') or '员工执行失败'), 'employee_id': employee_id, 'data': result}

def _normalize_business_db_entity(raw: _facade().Any, user_message: str='') -> str:
    text = str(raw or '').strip()
    if text:
        lowered = text.lower()
        if lowered in _facade()._BUSINESS_DB_ENTITY_ALIASES:
            return _facade()._BUSINESS_DB_ENTITY_ALIASES[lowered]
        if text in _facade()._BUSINESS_DB_ENTITY_ALIASES:
            return _facade()._BUSINESS_DB_ENTITY_ALIASES[text]
    msg = str(user_message or '')
    for (token, entity) in _facade()._BUSINESS_DB_ENTITY_ALIASES.items():
        if token and token in msg:
            return entity
    return ''

def get_recent_business_db_target(user_id: object) -> dict[str, _facade().Any] | None:
    target = _facade()._RECENT_BUSINESS_DB_TARGETS.get(str(user_id or '').strip())
    return dict(target) if target is not None else None

def _business_db_payload_contains_key(value: _facade().Any, forbidden: set[str]) -> bool:
    """Reject forbidden controls even when a model nests them in changes/fields/selector."""
    if isinstance(value, dict):
        for (key, nested) in value.items():
            if str(key).strip().lower() in forbidden:
                return True
            if _business_db_payload_contains_key(nested, forbidden):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any((_business_db_payload_contains_key(item, forbidden) for item in value))
    return False

def _result_record_id(value: _facade().Any) -> int | None:
    if not isinstance(value, dict):
        return None
    raw_id = value.get('id') or value.get('product_id') or value.get('record_id')
    if raw_id not in (None, ''):
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    for key in ('data', 'raw', 'shipment', 'result'):
        nested_id = _result_record_id(value.get(key))
        if nested_id:
            return nested_id
    return None

def _business_db_selector(payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    nested = payload.get('selector')
    selector = dict(nested) if isinstance(nested, dict) else {}
    for key in ('id', 'customer_id', 'record_id', 'order_number', 'customer_name', 'unit_name', 'name', 'product_name', 'name_or_model', 'model_number', 'material_name', 'material_code'):
        if key not in selector and payload.get(key) not in (None, ''):
            selector[key] = payload.get(key)
    return selector

def _business_db_target_candidates(entity: str, selector: dict[str, _facade().Any]) -> tuple[list[dict[str, _facade().Any]], str]:
    """Resolve an exact target inside the active tenant scope.

    All involved models inherit TenantScopedMixin, and apply_tenant_filter is repeated here as
    defense in depth.  No fuzzy write target is ever accepted.
    """
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import apply_tenant_filter
    raw_id = selector.get('id') or selector.get('customer_id') or selector.get('record_id') or selector.get('order_number')
    numeric_id = 0
    if raw_id not in (None, ''):
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError):
            return ([], 'id')
        if numeric_id <= 0:
            return ([], 'id')
    with get_db() as db:
        if entity == 'customers':
            from app.db.models.purchase_unit import PurchaseUnit
            query = apply_tenant_filter(db.query(PurchaseUnit), PurchaseUnit)
            selector_field = 'id'
            if numeric_id:
                query = query.filter(PurchaseUnit.id == numeric_id)
            else:
                value = str(selector.get('customer_name') or selector.get('unit_name') or selector.get('name') or '').strip()
                if not value:
                    return ([], '')
                selector_field = next((key for key in ('customer_name', 'unit_name', 'name') if selector.get(key) not in (None, '')), 'customer_name')
                query = query.filter(PurchaseUnit.unit_name == value)
            rows = query.order_by(PurchaseUnit.id.asc()).limit(21).all()
            return ([{'id': row.id, 'customer_name': row.unit_name, 'name': row.unit_name} for row in rows], selector_field)
        if entity == 'products':
            from app.db.models.product import Product
            query = apply_tenant_filter(db.query(Product), Product)
            selector_field = 'id'
            if numeric_id:
                query = query.filter(Product.id == numeric_id)
            else:
                model_number = str(selector.get('model_number') or '').strip().upper()
                name = str(selector.get('product_name') or selector.get('name') or selector.get('name_or_model') or '').strip()
                if model_number:
                    selector_field = 'model_number'
                    query = query.filter(Product.model_number == model_number)
                elif name:
                    selector_field = next((key for key in ('product_name', 'name', 'name_or_model') if selector.get(key) not in (None, '')), 'name')
                    query = query.filter(Product.name == name)
                else:
                    return ([], '')
            rows = query.order_by(Product.id.asc()).limit(21).all()
            return ([{'id': row.id, 'name': row.name, 'product_name': row.name, 'model_number': row.model_number or ''} for row in rows], selector_field)
        if entity == 'materials':
            from app.db.models.material import Material
            query = apply_tenant_filter(db.query(Material), Material)
            selector_field = 'id'
            if numeric_id:
                query = query.filter(Material.id == numeric_id)
            else:
                code = str(selector.get('material_code') or '').strip()
                name = str(selector.get('material_name') or selector.get('name') or '').strip()
                if code:
                    selector_field = 'material_code'
                    query = query.filter(Material.material_code == code)
                elif name:
                    selector_field = 'material_name' if selector.get('material_name') else 'name'
                    query = query.filter(Material.name == name)
                else:
                    return ([], '')
            rows = query.order_by(Material.id.asc()).limit(21).all()
            return ([{'id': row.id, 'name': row.name, 'material_name': row.name, 'material_code': row.material_code} for row in rows], selector_field)
        if entity == 'shipment_records':
            from app.db.models.shipment import ShipmentRecord
            if not numeric_id:
                return ([], '')
            rows = apply_tenant_filter(db.query(ShipmentRecord), ShipmentRecord).filter(ShipmentRecord.id == numeric_id).order_by(ShipmentRecord.id.asc()).limit(2).all()
            return ([{'id': row.id, 'name': f'{row.purchase_unit} / {row.product_name}', 'purchase_unit': row.purchase_unit, 'product_name': row.product_name} for row in rows], 'id')
    return ([], '')

def prepare_business_db_write_target(entity: str, operation: str, payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """Resolve update/delete targets without mutating business data.

    The result is shared by the clarification gate and the final dispatcher, so approval previews
    and execution use the same exact, tenant-scoped target.
    """
    normalized = dict(payload or {})
    if operation not in {'update', 'delete'}:
        return {'success': True, 'payload': normalized}
    if bool(normalized.get('force')):
        return {'success': False, 'reason': 'force_not_allowed', 'message': '智能对话不允许 force 删除；请先处理关联数据。'}
    selector = _facade()._business_db_selector(normalized)
    (candidates, selector_field) = _facade()._business_db_target_candidates(entity, selector)
    if not selector_field:
        return {'success': False, 'reason': 'missing_target', 'message': '更新或删除必须提供当前租户内的唯一 ID 或受支持的精确自然键。', 'candidates': []}
    if not candidates:
        return {'success': False, 'reason': 'target_not_found', 'message': '当前租户内未找到目标记录，未执行写入。', 'candidates': []}
    if len(candidates) > 1:
        return {'success': False, 'reason': 'ambiguous_target', 'message': '精确条件匹配到多条记录，请选择唯一 ID。', 'candidates': candidates}
    target = candidates[0]
    normalized['id'] = int(target['id'])
    normalized['_selector_field'] = selector_field
    normalized['_resolved_target'] = target
    return {'success': True, 'payload': normalized, 'target': target}

def _remember_business_db_target(runtime_context: dict[str, _facade().Any], entity: str, operation: str, payload: dict[str, _facade().Any], result: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    if not result.get('success') or operation == 'delete':
        return result
    target_id = _facade()._result_record_id(result) or _facade()._result_record_id(payload)
    if not target_id and operation in {'create', 'ensure_exists', 'upsert'}:
        (candidates, _) = _facade()._business_db_target_candidates(entity, _facade()._business_db_selector(payload))
        if len(candidates) == 1:
            target_id = int(candidates[0]['id'])
    user_id = str(runtime_context.get('user_id') or '').strip()
    if user_id and target_id:
        _facade()._RECENT_BUSINESS_DB_TARGETS[user_id] = {'entity': entity, 'id': int(target_id)}
    return result
