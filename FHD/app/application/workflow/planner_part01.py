# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.workflow.planner')

def _clean_db_slot_value(value: str) -> str:
    text = str(value or '').strip(' \t\r\n，,。；;：:')
    for token in ('到数据库', '写入数据库', '加入数据库', '添加到数据库', '保存到数据库', '入库', '数据库'):
        text = text.replace(token, '')
    if text in {'原材料', '物料'}:
        return text
    text = _facade().re.sub('^(新增|添加|创建|写入|保存|修改|更新|删除|移除|客户|单位|购买单位|产品|商品|原材料|物料|发货单)\\s*', '', text)
    text = _facade().re.sub('\\s*(客户|单位|购买单位|产品|商品|原材料|物料|发货单)$', '', text)
    return text.strip(' \t\r\n，,。；;：:')

def _extract_named_slot(message: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        match = _facade().re.search(pattern, message, flags=_facade().re.I)
        if match:
            value = _facade()._clean_db_slot_value(match.group(1))
            if value:
                return value
    quoted = _facade().re.search('[「“\\"\']([^」”\\"\']+)[」”\\"\']', message)
    if quoted:
        return _facade()._clean_db_slot_value(quoted.group(1))
    return ''

def _infer_business_db_entity(message: str) -> str:
    if any((k in message for k in ('出货', '发货', '发货单'))):
        return 'shipment_records'
    if any((k in message for k in ('原材料', '物料'))):
        return 'materials'
    if any((k in message for k in ('产品', '商品'))):
        return 'products'
    if any((k in message for k in ('客户', '单位', '购买单位'))):
        return 'customers'
    return 'products'

def _infer_business_db_operation(message: str) -> str:
    lower = str(message or '').lower()
    if any((k in message for k in ('删除', '移除'))) or any((k in lower for k in ('delete', 'remove'))):
        return 'delete'
    if any((k in message for k in ('修改', '更新', '改为', '改成'))) or 'update' in lower:
        return 'update'
    return 'create'

def _extract_business_db_id(message: str) -> int | None:
    match = _facade().re.search('(?:记录|客户|产品|原材料|物料|发货单|订单)?\\s*(?:id|ID|编号)\\s*[:：#]?\\s*(\\d+)', message)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None

def _extract_marked_value(message: str, labels: tuple[str, ...]) -> str:
    label_pattern = '|'.join((_facade().re.escape(label) for label in labels))
    match = _facade().re.search(f"""(?:{label_pattern})\\s*[:：是为]?\\s*[「“\\"']?([^，,。；;\\n]+?)[」”\\"']?(?=\\s+(?:联系人|电话|地址|型号|规格|单价|价格|数量|库存|单位|状态|客户|产品|原材料|物料|发货单|ID|id)\\s*[:：是为]?|[，,。；;]|$)""", message, flags=_facade().re.I)
    return _facade()._clean_db_slot_value(match.group(1)) if match else ''

def _extract_number(message: str, labels: tuple[str, ...]) -> float | None:
    label_pattern = '|'.join((_facade().re.escape(label) for label in labels))
    match = _facade().re.search(f'(?:{label_pattern})\\s*[:：是为]?\\s*(-?\\d+(?:\\.\\d+)?)', message, _facade().re.I)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None

def _selector_for_business_db_message(entity: str, message: str) -> dict[str, _facade().Any]:
    numeric_id = _facade()._extract_business_db_id(message)
    if numeric_id:
        return {'id': numeric_id}
    if entity == 'customers':
        name = _facade()._extract_marked_value(message, ('客户', '购买单位'))
        return {'customer_name': name} if name else {}
    if entity == 'products':
        model = _facade()._extract_marked_value(message, ('型号', 'model'))
        if model:
            return {'model_number': model.upper()}
        name = _facade()._extract_marked_value(message, ('产品', '商品'))
        return {'product_name': name} if name else {}
    if entity == 'materials':
        code = _facade()._extract_marked_value(message, ('物料编码', '原材料编码', 'material_code'))
        if code:
            return {'material_code': code}
        name = _facade()._extract_marked_value(message, ('原材料', '物料'))
        return {'material_name': name} if name else {}
    return {}

def _changes_for_business_db_message(entity: str, message: str) -> dict[str, _facade().Any]:
    changes: dict[str, _facade().Any] = {}
    if entity == 'customers':
        person = _facade()._extract_marked_value(message, ('联系人',))
        phone = _facade()._extract_marked_value(message, ('联系电话', '电话'))
        address = _facade()._extract_marked_value(message, ('联系地址', '地址'))
        if person:
            changes['contact_person'] = person
        if phone:
            changes['contact_phone'] = phone
        if address:
            changes['contact_address'] = address
    elif entity == 'products':
        spec = _facade()._extract_marked_value(message, ('规格',))
        price = _facade()._extract_number(message, ('单价', '价格'))
        quantity = _facade()._extract_number(message, ('数量', '库存'))
        unit = _facade()._extract_marked_value(message, ('计量单位',))
        if spec:
            changes['specification'] = spec
        if price is not None:
            changes['price'] = price
        if quantity is not None:
            changes['quantity'] = int(quantity)
        if unit:
            changes['unit'] = unit
    elif entity == 'materials':
        price = _facade()._extract_number(message, ('单价', '价格'))
        quantity = _facade()._extract_number(message, ('数量', '库存'))
        spec = _facade()._extract_marked_value(message, ('规格',))
        if price is not None:
            changes['unit_price'] = price
        if quantity is not None:
            changes['quantity'] = quantity
        if spec:
            changes['specification'] = spec
    elif entity == 'shipment_records':
        tins = _facade()._extract_number(message, ('桶数', '数量'))
        status = _facade()._extract_marked_value(message, ('状态',))
        price = _facade()._extract_number(message, ('单价', '价格'))
        if tins is not None:
            changes['quantity_tins'] = int(tins)
        if status:
            changes['status'] = status
        if price is not None:
            changes['unit_price'] = price
    return changes

def _extract_business_db_write_node(message: str) -> _facade().WorkflowNode | None:
    entity = _facade()._infer_business_db_entity(message)
    operation = _facade()._infer_business_db_operation(message)
    if operation in {'update', 'delete'}:
        selector = _facade()._selector_for_business_db_message(entity, message)
        if not selector:
            return None
        payload: dict[str, _facade().Any] = {'selector': selector}
        if operation == 'update':
            changes = _facade()._changes_for_business_db_message(entity, message)
            if not changes:
                return None
            payload['changes'] = changes
        return _facade().WorkflowNode(node_id=f"{operation}_business_{entity.rstrip('s')}", tool_id='business_db', action='write', params={'entity': entity, 'operation': operation, 'payload': _facade()._attach_explicit_tenant_id(payload, message)}, risk='high' if operation == 'delete' else 'medium', description=f'{operation} {entity}', idempotent=False)
    if entity == 'customers':
        unit_name = _facade()._extract_named_slot(message, ('(?:客户|单位|购买单位)\\s*[:：是为]?\\s*([^\\s，,。；;]+)', '(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:客户|单位)'))
        if not unit_name:
            return None
        payload = {'unit_name': unit_name, 'customer_name': unit_name}
        payload.update(_facade()._changes_for_business_db_message(entity, message))
        return _facade().WorkflowNode(node_id='write_business_customer', tool_id='business_db', action='write', params={'entity': 'customers', 'operation': 'upsert', 'payload': _facade()._attach_explicit_tenant_id(payload, message)}, risk='medium', description=f'写入客户 {unit_name}', idempotent=True)
    if entity == 'products':
        product_name = _facade()._extract_named_slot(message, ('(?:产品|商品)\\s*[:：是为]?\\s*([^\\s，,。；;]+)', '(?:新增|添加|创建|写入|保存)\\s*([^\\s，,。；;]+)\\s*(?:产品|商品)'))
        if not product_name:
            return None
        model_match = _facade().re.search('(?:型号|model)\\s*[:：]?\\s*([A-Za-z0-9._-]+)', message, _facade().re.I)
        product_payload: dict[str, _facade().Any] = {'name_or_model': product_name, 'product_name': product_name}
        unit = _facade()._extract_marked_value(message, ('计量单位',))
        price = _facade()._extract_number(message, ('单价', '价格'))
        specification = _facade()._extract_marked_value(message, ('规格',))
        if unit:
            product_payload['unit'] = unit
        if price is not None:
            product_payload['price'] = price
        if specification:
            product_payload['specification'] = specification
        if model_match:
            product_payload['model_number'] = model_match.group(1).strip().upper()
        return _facade().WorkflowNode(node_id='write_business_product', tool_id='business_db', action='write', params={'entity': 'products', 'operation': 'create', 'payload': _facade()._attach_explicit_tenant_id(product_payload, message)}, risk='medium', description=f'写入产品 {product_name}', idempotent=False)
    if entity == 'materials':
        name = _facade()._extract_marked_value(message, ('原材料', '物料'))
        if not name:
            return None
        payload = {'name': name}
        code = _facade()._extract_marked_value(message, ('物料编码', '原材料编码', 'material_code'))
        unit = _facade()._extract_marked_value(message, ('计量单位',))
        quantity = _facade()._extract_number(message, ('数量', '库存'))
        price = _facade()._extract_number(message, ('单价', '价格'))
        if code:
            payload['material_code'] = code
        if unit:
            payload['unit'] = unit
        if quantity is not None:
            payload['quantity'] = quantity
        if price is not None:
            payload['unit_price'] = price
        return _facade().WorkflowNode(node_id='write_business_material', tool_id='business_db', action='write', params={'entity': 'materials', 'operation': 'create', 'payload': _facade()._attach_explicit_tenant_id(payload, message)}, risk='medium', description=f'写入原材料 {name}', idempotent=False)
    if entity == 'shipment_records':
        unit_name = _facade()._extract_marked_value(message, ('客户', '购买单位'))
        product_name = _facade()._extract_marked_value(message, ('产品', '商品'))
        tins = _facade()._extract_number(message, ('桶数', '数量'))
        if not unit_name or not product_name or tins is None:
            return None
        item: dict[str, _facade().Any] = {'product_name': product_name, 'name': product_name, 'quantity_tins': int(tins)}
        model = _facade()._extract_marked_value(message, ('型号', 'model'))
        spec = _facade()._extract_number(message, ('桶规格', '规格'))
        price = _facade()._extract_number(message, ('单价', '价格'))
        if model:
            item['model_number'] = model.upper()
        if spec is not None:
            item['tin_spec'] = spec
        if price is not None:
            item['unit_price'] = price
        return _facade().WorkflowNode(node_id='write_business_shipment_record', tool_id='business_db', action='write', params={'entity': 'shipment_records', 'operation': 'create', 'payload': _facade()._attach_explicit_tenant_id({'unit_name': unit_name, 'products': [item]}, message)}, risk='medium', description=f'为 {unit_name} 创建 {product_name} 出货记录', idempotent=False)
    return None

def _extract_business_db_read_keyword(message: str, entity: str) -> str:
    quoted = _facade().re.search('[「“\\"\']([^」”\\"\']+)[」”\\"\']', message)
    if quoted:
        return _facade()._clean_db_slot_value(quoted.group(1))
    if entity == 'products':
        slot = _facade()._extract_named_slot(message, ('(?:产品|商品|型号|model)\\s*[:：的]?\\s*([A-Za-z0-9._-]+|[^\\s，,。；;]+)', '(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:产品|商品)?\\s*([A-Za-z0-9._-]+)'))
        if slot:
            return slot
        model = _facade().re.search('\\b[A-Za-z0-9][A-Za-z0-9._-]{1,}\\b', message)
        if model:
            return model.group(0).strip()
    if entity == 'customers':
        slot = _facade()._extract_named_slot(message, ('(?:客户|单位|购买单位)\\s*[:：的]?\\s*([^\\s，,。；;]+)', '(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:客户|单位)?\\s*([^\\s，,。；;]+)'))
        if slot:
            return slot
    if entity == 'materials':
        slot = _facade()._extract_named_slot(message, ('(?:原材料|物料|材料)\\s*[:：的]?\\s*([^\\s，,。；;]+)', '(?:查|查询|读取|读)\\s*(?:数据库|db|database)?\\s*(?:原材料|物料|材料)?\\s*([^\\s，,。；;]+)'))
        if slot:
            return slot
    cleaned = str(message or '').strip()
    for token in ('查询数据库', '读取数据库', '查数据库', '读数据库', '数据库', 'database', '查库', '读库', '查询', '读取', '查', '读', '产品', '商品', '客户', '单位', '购买单位', '原材料', '物料', '材料'):
        cleaned = cleaned.replace(token, ' ')
    cleaned = _facade().re.sub('\\s+', ' ', cleaned).strip(' \t\r\n，,。；;：:')
    return cleaned or str(message or '').strip()

def get_tool_registry() -> dict[str, _facade().Any]:
    """
    返回工作流工具注册表，供 ai_chat_app_service 使用。
    覆盖报价、主数据、出货、模板与微信辅助等能力，与意图层 tool_key 对齐。
    """
    from app.services.tools_execution.registry import get_workflow_tool_registry
    return get_workflow_tool_registry()

def execute_tool(tool_name: str, params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """
    执行指定工具（支持 execute_registered_workflow_tool 注入的 _action）。

    与 get_tool_registry 中的工具 id 一致。
    """
    _facade().logger.info('execute_tool called: tool_name=%s, params=%s', tool_name, params)
    merged = dict(params or {})
    merged.pop('_runtime_context', None)
    action = str(merged.pop('_action', '') or '').strip().lower()
    if not action:
        action_defaults: dict[str, str] = {'price_list': 'export', 'products': 'query', 'customers': 'query', 'shipment_generate': 'generate', 'shipment_records': 'query', 'shipments': 'query', 'materials': 'query', 'print_label': 'generate', 'excel_decompose': 'decompose', 'template_extract': 'extract', 'excel_schema': 'analyze', 'excel_analysis': 'analyze', 'import_excel': 'import', 'employee': 'list', 'business_db': 'read'}
        action = action_defaults.get(tool_name, 'query')
    handler = _facade()._WORKFLOW_TOOL_HANDLERS.get((tool_name, action))
    if handler is not None:
        return handler(merged)
    result = _facade().execute_registered_workflow_tool(tool_name, action, merged)
    if not result.get('success') and str(result.get('message', '')).startswith('未注册'):
        return {'success': False, 'message': f'未知工具动作: {tool_name}.{action}', 'error_code': 'unknown_tool_action'}
    return result

def _execute_price_list_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """执行价格表导出工具"""
    try:
        customer_name = params.get('customer_name') or params.get('unit')
        keyword = params.get('keyword')
        date = params.get('date')
        if not customer_name:
            return {'success': False, 'message': '缺少 customer_name 参数', 'error_code': 'missing_customer_name'}
        fhd_root = _facade().ensure_fhd_repo_on_syspath()
        from app.application.tools import handle_price_list_export
        result = handle_price_list_export({'customer_name': customer_name, 'keyword': keyword, 'export_date': date}, workspace_root=str(fhd_root) if fhd_root else None)
        return result
    except ImportError as e:
        _facade().logger.error('价格表导出服务导入失败: %s', e)
        return {'success': False, 'message': '价格表导出服务不可用', 'error_code': 'service_unavailable'}
    except (ValueError, TypeError) as e:
        _facade().logger.warning('价格表导出参数错误: %s', e)
        return {'success': False, 'message': '参数错误：请检查客户名称和价格参数', 'error_code': 'invalid_parameters'}
    except OSError as e:
        _facade().logger.error('价格表导出文件操作失败: %s', e)
        return {'success': False, 'message': '文件导出失败，请检查磁盘空间', 'error_code': 'file_io_error'}
    except RuntimeError as e:
        _facade().logger.error('价格表导出运行时错误: %s', e)
        return {'success': False, 'message': '导出处理失败，请稍后重试', 'error_code': 'export_failed'}

def _execute_products_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """执行产品查询工具"""
    try:
        from app.bootstrap import get_products_service
        keyword = str(params.get('keyword') or '').strip()
        unit_name = str(params.get('unit_name') or params.get('unit') or '').strip() or None
        model_number = str(params.get('model_number') or params.get('product_code') or '').strip() or None
        page = int(params.get('page', 1))
        per_page = int(params.get('per_page', 20))
        svc = get_products_service()
        if model_number and unit_name:
            result = svc.get_products(unit_name=unit_name, model_number=model_number, keyword=None, page=page, per_page=per_page)
        elif model_number:
            result = svc.get_products(unit_name=None, model_number=model_number, keyword=None, page=page, per_page=per_page)
        elif unit_name:
            result = svc.get_products(unit_name=unit_name, model_number=None, keyword=keyword or None, page=page, per_page=per_page)
        else:
            result = svc.get_products(unit_name=None, model_number=None, keyword=keyword or None, page=page, per_page=per_page)
        return result
    except ImportError as e:
        _facade().logger.error('产品服务导入失败: %s', e)
        return {'success': False, 'message': '产品服务不可用', 'error_code': 'service_unavailable'}
    except (ValueError, TypeError) as e:
        _facade().logger.warning('产品查询参数错误: %s', e)
        return {'success': False, 'message': '查询参数错误，请检查输入', 'error_code': 'invalid_parameters'}
    except RuntimeError as e:
        _facade().logger.error('产品查询运行时错误: %s', e)
        return {'success': False, 'message': '查询失败，请稍后重试', 'error_code': 'query_failed'}

def _execute_customers_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """执行客户查询工具"""
    try:
        from app.bootstrap import get_customer_app_service
        keyword = params.get('keyword') or params.get('customer_name') or ''
        page = int(params.get('page', 1))
        per_page = int(params.get('per_page', 20))
        svc = get_customer_app_service()
        return _facade().cast('dict[str, Any]', svc.get_all(keyword=str(keyword).strip() or None, page=page, per_page=per_page))
    except ImportError as e:
        _facade().logger.error('客户服务导入失败: %s', e)
        return {'success': False, 'message': '客户服务不可用', 'error_code': 'service_unavailable'}
    except (ValueError, TypeError) as e:
        _facade().logger.warning('客户查询参数错误: %s', e)
        return {'success': False, 'message': '查询参数错误，请检查输入', 'error_code': 'invalid_parameters'}
    except RuntimeError as e:
        _facade().logger.error('客户查询运行时错误: %s', e)
        return {'success': False, 'message': '查询失败，请稍后重试', 'error_code': 'query_failed'}

def _execute_customers_ensure_exists_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    """创建客户（单位）如不存在。"""
    try:
        from app.bootstrap import get_customer_app_service
        unit = str(params.get('unit_name') or params.get('customer_name') or '').strip()
        if not unit:
            return {'success': False, 'message': '缺少 unit_name', 'error_code': 'missing_unit_name'}
        svc = get_customer_app_service()
        matched = svc.match_purchase_unit(unit)
        if matched:
            return {'success': True, 'created': False, 'message': f'单位已存在：{unit}', 'data': {'id': getattr(matched, 'id', None), 'customer_name': getattr(matched, 'unit_name', None) or unit, 'unit_name': getattr(matched, 'unit_name', None) or unit}}
        created = svc.create({'customer_name': unit})
        out = dict(created) if isinstance(created, dict) else {'success': False}
        out['created'] = bool(out.get('success'))
        return out
    except ImportError as e:
        _facade().logger.error('客户创建服务导入失败: %s', e)
        return {'success': False, 'message': '客户创建服务不可用', 'error_code': 'service_unavailable', 'created': False}
    except (ValueError, TypeError) as e:
        _facade().logger.warning('客户创建参数错误: %s', e)
        return {'success': False, 'message': '创建参数错误，请检查单位名称', 'error_code': 'invalid_parameters', 'created': False}
    except RuntimeError as e:
        _facade().logger.error('客户创建运行时错误: %s', e)
        return {'success': False, 'message': '创建失败，请稍后重试', 'error_code': 'create_failed', 'created': False}

def _execute_shipment_generate_tool(params: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    try:
        from app.application.facades.tools_facade import _parse_order_text
        from app.bootstrap import get_shipment_app_service
        order_text = str(params.get('order_text') or '').strip()
        unit_name = str(params.get('unit_name') or '').strip()
        products = params.get('products')
        if order_text:
            parsed = _parse_order_text(order_text)
        elif unit_name and isinstance(products, list) and products:
            parsed = {'success': True, 'unit_name': unit_name, 'products': products}
        else:
            return {'success': False, 'message': '缺少 order_text，或 unit_name+products', 'error_code': 'missing_order_params'}
        if not parsed.get('success'):
            return {'success': False, 'message': parsed.get('message') or parsed.get('error') or '订单解析失败'}
        svc = get_shipment_app_service()
        return _facade().cast('dict[str, Any]', svc.generate_shipment_document(unit_name=str(parsed.get('unit_name') or ''), products=list(parsed.get('products') or []), template_name=params.get('template_name') or params.get('template'), template_id=params.get('template_id'), preferred_template=params.get('preferred_template') or params.get('template'), date=params.get('date'), order_number=params.get('order_number'), intent='shipment_generate', allow_products_from_db=True, raw_text=order_text or str(params.get('raw_text') or '')))
    except ImportError as e:
        _facade().logger.error('发货单服务导入失败: %s', e)
        return {'success': False, 'message': '发货单服务不可用', 'error_code': 'service_unavailable'}
    except (ValueError, TypeError) as e:
        _facade().logger.warning('发货单生成参数错误: %s', e)
        return {'success': False, 'message': '订单参数错误，请检查输入', 'error_code': 'invalid_parameters'}
    except OSError as e:
        _facade().logger.error('发货单文件生成失败: %s', e)
        return {'success': False, 'message': '文档生成失败，请检查磁盘空间', 'error_code': 'file_io_error'}
    except RuntimeError as e:
        _facade().logger.error('发货单生成运行时错误: %s', e)
        return {'success': False, 'message': '生成失败，请稍后重试', 'error_code': 'generation_failed'}
