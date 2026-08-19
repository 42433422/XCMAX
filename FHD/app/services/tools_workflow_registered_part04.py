# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

from app.services.tools_workflow_registered_part03 import prepare_business_db_write_target

_DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET = prepare_business_db_write_target

def _facade():
    return importlib.import_module('app.services.tools_workflow_registered')

def _business_db_update_fields(payload: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
    nested = payload.get('changes')
    if not isinstance(nested, dict):
        nested = payload.get('fields')
    if isinstance(nested, dict):
        return {k: v for (k, v) in nested.items() if k not in _facade()._BUSINESS_DB_CONTROL_FIELDS}
    selector_field = str(payload.get('_selector_field') or '')
    return {key: value for (key, value) in payload.items() if key not in _facade()._BUSINESS_DB_CONTROL_FIELDS and key not in {'id', 'customer_id', 'record_id', 'order_number'} and (key != selector_field)}

def _registered_router_business_db(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    entity = _facade()._normalize_business_db_entity(params.get('entity'), user_message)
    if not entity:
        return {'success': False, 'message': '缺少或不支持的 entity；允许 customers/products/materials/shipment_records。', 'allowed_entities': ['customers', 'products', 'materials', 'shipment_records']}
    if any((k in params for k in ('sql', 'raw_sql', 'query_sql'))):
        return {'success': False, 'message': 'business_db 不接受任意 SQL，请使用 entity/operation/payload。'}
    if action in ('read', 'query', 'list'):
        read_params = dict(params)
        read_params.setdefault('keyword', params.get('keyword') or params.get('query') or '')
        if entity == 'customers':
            return _facade()._registered_router_customers('query', read_params, runtime_context, profile, user_message)
        if entity == 'products':
            return _facade()._registered_router_products('query', read_params, runtime_context, 'admin', user_message)
        if entity == 'materials':
            return _facade()._registered_router_materials('query', read_params, runtime_context, profile, user_message)
        if entity == 'shipment_records':
            return _facade()._registered_router_shipment_records('query', read_params, runtime_context, profile, user_message)
    if action != 'write':
        return {'success': False, 'message': f'未注册的 business_db 动作: {action}'}
    operation = str(params.get('operation') or params.get('op') or 'create').strip().lower()
    payload = params.get('payload')
    if not isinstance(payload, dict):
        return {'success': False, 'message': 'business_db.write 需要 dict payload。'}
    if _facade()._business_db_payload_contains_key(payload, {'sql', 'raw_sql', 'query_sql'}):
        return {'success': False, 'message': 'business_db 不接受任意 SQL，请使用 entity/operation/payload。'}
    if _facade()._business_db_payload_contains_key(payload, {'tenant_id'}):
        return {'success': False, 'message': 'tenant_id 只能来自当前登录会话，拒绝跨租户目标。'}
    try:
        from app.infrastructure.tenant_scope import tenant_id_for_write
        tenant_id_for_write()
    except _facade().RECOVERABLE_ERRORS as exc:
        return {'success': False, 'message': f'缺少有效租户上下文，拒绝写入：{exc}'}
    # Preserve both historical patch seams: some callers patch this extracted
    # function's globals, while others patch the public facade export.
    prepare_target = prepare_business_db_write_target
    if prepare_target is _DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET:
        prepare_target = _facade().prepare_business_db_write_target
    prepared = prepare_target(entity, operation, payload)
    if not prepared.get('success'):
        return dict(prepared)
    payload = dict(prepared.get('payload') or {})
    if entity == 'customers':
        if operation in ('create', 'ensure_exists', 'upsert'):
            return _facade()._registered_router_customers(operation, payload, runtime_context, profile, user_message)
        if operation == 'update':
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {'success': False, 'message': 'customers.update 缺少 changes/fields。'}
            return _facade()._registered_router_customers('update', {'id': payload['id'], **fields}, runtime_context, profile, user_message)
        if operation == 'delete':
            return _facade()._registered_router_customers('delete', {'id': payload['id'], 'force': False}, runtime_context, profile, user_message)
        return {'success': False, 'message': 'customers 支持 create/ensure_exists/upsert/update/delete。'}
    if entity == 'products':
        if operation == 'create':
            return _facade()._registered_router_products('create', payload, runtime_context, profile, user_message)
        if operation == 'update':
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {'success': False, 'message': 'products.update 缺少 changes/fields。'}
            return _facade()._registered_router_products('update', {'id': payload['id'], **fields}, runtime_context, profile, user_message)
        if operation == 'delete':
            return _facade()._registered_router_products('delete', {'id': payload['id']}, runtime_context, profile, user_message)
        return {'success': False, 'message': 'products 支持 create/update/delete；查询请用 read。'}
    if entity == 'materials':
        if operation == 'create':
            return _facade()._registered_router_materials('create', payload, runtime_context, profile, user_message)
        if operation == 'update':
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {'success': False, 'message': 'materials.update 缺少 changes/fields。'}
            return _facade()._registered_router_materials('update', {'id': payload['id'], **fields}, runtime_context, profile, user_message)
        if operation == 'delete':
            result = _facade()._registered_router_materials('delete', {'id': payload['id']}, runtime_context, profile, user_message)
            if result.get('success'):
                from app.db.models.material import Material
                from app.db.session import get_db
                from app.infrastructure.tenant_scope import tenant_id_for_write
                with get_db() as db:
                    deleted = db.query(Material).filter(Material.id == int(payload['id']), Material.tenant_id == tenant_id_for_write()).delete(synchronize_session=False)
                if deleted != 1:
                    return {'success': False, 'message': '原材料软删除后物理清理未命中唯一租户记录。'}
            return result
        return {'success': False, 'message': 'materials 支持 create/update/delete。'}
    if entity == 'shipment_records':
        if operation == 'create':
            return _facade()._registered_router_shipment_records('create', payload, runtime_context, profile, user_message)
        if operation == 'update':
            fields = _facade()._business_db_update_fields(payload)
            if not fields:
                return {'success': False, 'message': 'shipment_records.update 缺少 changes/fields。'}
            return _facade()._registered_router_shipment_records('update', {'id': payload['id'], **fields}, runtime_context, profile, user_message)
        if operation == 'delete':
            return _facade()._registered_router_shipment_records('delete', {'id': payload['id']}, runtime_context, profile, user_message)
        return {'success': False, 'message': 'shipment_records 支持 create/update/delete。'}
    return {'success': False, 'message': f'不支持的 entity: {entity}'}

def _registered_router_dataset_rag(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    dataset_id = str(params.get('dataset_id') or '').strip()
    if not dataset_id:
        return {'success': False, 'message': f'dataset_rag.{action} 缺少 dataset_id 参数'}
    from app.application.dataset_rag_app_service import DATASET_READ_PERMISSION, DATASET_WRITE_PERMISSION, DatasetAccessContext, get_dataset_rag_app_service
    service = get_dataset_rag_app_service()

    def as_bool(value: _facade().Any, *, default: bool=False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if not cleaned:
                return default
            if cleaned in {'1', 'true', 'yes', 'on'}:
                return True
            if cleaned in {'0', 'false', 'no', 'off'}:
                return False
        return bool(value)

    def as_int(value: _facade().Any, default: int) -> int:
        if value in (None, ''):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def as_dict(value: _facade().Any) -> dict[str, _facade().Any]:
        return dict(value) if isinstance(value, dict) else {}

    def parse_permissions(value: _facade().Any) -> set[str]:
        if isinstance(value, str):
            return {part.strip() for part in value.replace(';', ',').split(',') if part.strip()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return {str(part).strip() for part in value if str(part).strip()}
        return set()

    def access_context(_required_permission: str) -> DatasetAccessContext | None:
        raw_context = params.get('access_context') or runtime_context.get('dataset_access_context')
        context_payload = as_dict(raw_context)
        has_explicit_context = bool(context_payload)
        tenant_id = str(context_payload.get('tenant_id') or runtime_context.get('dataset_tenant_id') or runtime_context.get('tenant_id') or runtime_context.get('workspace_id') or '').strip()
        actor_id = str(context_payload.get('actor_id') or context_payload.get('user_id') or params.get('actor_id') or params.get('user_id') or runtime_context.get('user_id') or '').strip()
        permissions = parse_permissions(context_payload.get('permissions'))
        permissions.update(parse_permissions(params.get('permissions')))
        permissions.update(parse_permissions(runtime_context.get('dataset_permissions')))
        is_admin = as_bool(params.get('dataset_admin') if 'dataset_admin' in params else context_payload.get('is_admin', context_payload.get('admin')), default=False) or as_bool(runtime_context.get('dataset_admin'), default=False)
        if not has_explicit_context and (not permissions) and (not is_admin):
            return None
        return DatasetAccessContext(actor_id=actor_id, tenant_id=tenant_id, permissions=frozenset(permissions), is_admin=is_admin)

    def finalize(result: dict[str, _facade().Any], **defaults: _facade().Any) -> dict[str, _facade().Any]:
        result.setdefault('success', bool(result.get('success', False)))
        for (key, value) in defaults.items():
            result.setdefault(key, value)
        return result
    if action == 'ingest_document':
        result = service.ingest_document(dataset_id=dataset_id, source=str(params.get('source') or ''), text=str(params.get('text') or ''), file_path=str(params.get('file_path') or ''), document_id=str(params.get('document_id') or ''), chunk_strategy=str(params.get('chunk_strategy') or 'semantic'), chunk_size=as_int(params.get('chunk_size'), 500), chunk_overlap=as_int(params.get('chunk_overlap'), 50), metadata=as_dict(params.get('metadata')), tenant_id=str(params.get('tenant_id') or ''), version=params.get('version') or '', version_label=str(params.get('version_label') or ''), access_context=access_context(DATASET_WRITE_PERMISSION))
        return finalize(result, dataset_id=dataset_id)
    if action == 'query':
        query = str(params.get('query') or params.get('question') or user_message or '').strip()
        if not query:
            return {'success': False, 'message': 'dataset_rag.query 缺少 query 参数'}
        top_k = as_int(params.get('top_k'), 5)
        tenant_id = str(params.get('tenant_id') or '')
        version = params.get('version') or ''
        metadata_filter = as_dict(params.get('metadata_filter'))
        rerank = as_bool(params.get('rerank'), default=False)
        read_context = access_context(DATASET_READ_PERMISSION)
        include_answer = as_bool(params.get('include_answer'), default=True)
        if include_answer:
            result = service.answer(dataset_id=dataset_id, query=query, top_k=top_k, tenant_id=tenant_id, version=version, metadata_filter=metadata_filter, rerank=rerank, access_context=read_context)
        else:
            result = service.query(dataset_id=dataset_id, query=query, top_k=top_k, tenant_id=tenant_id, version=version, metadata_filter=metadata_filter, rerank=rerank, access_context=read_context)
        return finalize(result, dataset_id=dataset_id, query=query, chunks=[], citations=[], answer='')
    if action == 'diff_versions':
        source = str(params.get('source') or '').strip()
        from_version = params.get('from_version') or ''
        if not source:
            return {'success': False, 'message': 'dataset_rag.diff_versions 缺少 source 参数'}
        if not from_version:
            return {'success': False, 'message': 'dataset_rag.diff_versions 缺少 from_version 参数'}
        result = service.diff_versions(dataset_id=dataset_id, source=source, tenant_id=str(params.get('tenant_id') or ''), from_version=from_version, to_version=params.get('to_version') or 'latest', access_context=access_context(DATASET_READ_PERMISSION))
        return finalize(result, dataset_id=dataset_id, source=source)
    if action == 'rollback_version':
        source = str(params.get('source') or '').strip()
        target_version = params.get('target_version') or ''
        if not source:
            return {'success': False, 'message': 'dataset_rag.rollback_version 缺少 source 参数'}
        if not target_version:
            return {'success': False, 'message': 'dataset_rag.rollback_version 缺少 target_version 参数'}
        result = service.rollback_document_version(dataset_id=dataset_id, source=source, tenant_id=str(params.get('tenant_id') or ''), target_version=target_version, metadata=as_dict(params.get('metadata')), access_context=access_context(DATASET_WRITE_PERMISSION))
        return finalize(result, dataset_id=dataset_id, source=source)
    if action == 'rebuild_index':
        result = service.start_rebuild_index(dataset_id=dataset_id, tenant_id=str(params.get('tenant_id') or ''), metadata_filter=as_dict(params.get('metadata_filter')), background=as_bool(params.get('background'), default=True), max_attempts=as_int(params.get('max_attempts'), 1), access_context=access_context(DATASET_WRITE_PERMISSION))
        return finalize(result, dataset_id=dataset_id)
    if action == 'cancel_rebuild':
        job_id = str(params.get('job_id') or '').strip()
        if not job_id:
            return {'success': False, 'message': 'dataset_rag.cancel_rebuild 缺少 job_id 参数'}
        result = service.cancel_rebuild_job(dataset_id, job_id, access_context=access_context(DATASET_WRITE_PERMISSION))
        return finalize(result, dataset_id=dataset_id, job_id=job_id)
    if action == 'delete_document':
        document_id = str(params.get('document_id') or '').strip()
        if not document_id:
            return {'success': False, 'message': 'dataset_rag.delete_document 缺少 document_id 参数'}
        result = service.delete_document(dataset_id, document_id, access_context=access_context(DATASET_WRITE_PERMISSION))
        return finalize(result, dataset_id=dataset_id, document_id=document_id)
    return {'success': False, 'message': f'未注册的 dataset_rag 动作: {action}'}

def _registered_router_memory_v2(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    from app.services.user_memory_service import get_user_memory_service
    service = get_user_memory_service()
    user_id = str(params.get('user_id') or params.get('userId') or runtime_context.get('user_id') or 'default').strip()
    if not user_id:
        return {'success': False, 'message': f'memory_v2.{action} 缺少 user_id 参数'}

    def as_float(value: _facade().Any, default: float) -> tuple[float, str]:
        if value in (None, ''):
            return (default, '')
        try:
            return (float(value), '')
        except (TypeError, ValueError):
            return (default, 'confidence 必须是数字')
    if action == 'propose_candidate':
        memory_type = str(params.get('memory_type') or params.get('type') or 'preference').strip()
        key = str(params.get('key') or '').strip()
        if not key:
            return {'success': False, 'message': 'memory_v2.propose_candidate 缺少 key 参数'}
        if 'value' not in params:
            return {'success': False, 'message': 'memory_v2.propose_candidate 缺少 value 参数'}
        (confidence, error) = as_float(params.get('confidence'), 0.5)
        if error:
            return {'success': False, 'message': error}
        try:
            return service.propose_memory_candidate(user_id, memory_type, key, params.get('value'), source=str(params.get('source') or 'memory_v2_api'), confidence=confidence, evidence=params.get('evidence') if isinstance(params.get('evidence'), list) else None)
        except ValueError as exc:
            return {'success': False, 'message': str(exc)}
    memory_id = str(params.get('memory_id') or params.get('id') or '').strip()
    if not memory_id:
        return {'success': False, 'message': f'memory_v2.{action} 缺少 memory_id 参数'}
    if action == 'confirm':
        correction = params.get('correction') if isinstance(params.get('correction'), dict) else None
        return service.confirm_memory_candidate(user_id, memory_id, correction=correction)
    if action == 'reject':
        return service.reject_memory_candidate(user_id, memory_id, reason=str(params.get('reason') or ''))
    if action == 'correct':
        return service.correct_memory(user_id, memory_id, value=params.get('value') if 'value' in params else None, key=str(params.get('key')) if 'key' in params else None, reason=str(params.get('reason') or ''))
    if action == 'delete':
        return service.delete_memory(user_id, memory_id, reason=str(params.get('reason') or ''))
    return {'success': False, 'message': f'未注册的 memory_v2 动作: {action}'}

def _registered_router_excel_analysis(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    file_path = str(params.get('file_path') or '').strip()
    if not file_path:
        excel_ctx = runtime_context.get('excel_analysis') if isinstance(runtime_context.get('excel_analysis'), dict) else None
        if not excel_ctx:
            last_ctx = runtime_context.get('last_excel_analysis_context')
            if isinstance(last_ctx, dict):
                excel_ctx = last_ctx.get('result') if isinstance(last_ctx.get('result'), dict) else last_ctx
        if isinstance(excel_ctx, dict):
            file_path = str(excel_ctx.get('file_path') or '').strip()
    if not file_path:
        return {'success': False, 'message': 'excel_analysis 缺少 file_path 参数'}
    question = str(params.get('question') or '').strip()
    try:
        from app.infrastructure.skills.excel_analyzer.excel_template_analyzer import get_excel_analyzer_skill
        from app.infrastructure.skills.excel_toolkit.excel_toolkit import get_excel_toolkit_skill
    except ImportError:
        return {'success': False, 'message': 'Excel Skill 未正确安装'}
    toolkit_skill = get_excel_toolkit_skill()
    analyzer_skill = get_excel_analyzer_skill()
    if action == 'read':
        result = toolkit_skill.execute(file_path=file_path, action='view')
        return result
    if action == 'structure':
        result = analyzer_skill.execute(file_path=file_path)
        return result
    if action == 'statistics':
        view_result = toolkit_skill.execute(file_path=file_path, action='view')
        if not view_result.get('success'):
            return view_result
        content = view_result.get('content') or []
        total_rows = view_result.get('row_count') or 0
        all_values = []
        for row in content:
            for cell in row.get('cells') or []:
                v = cell.get('value')
                if v is not None:
                    try:
                        all_values.append(float(v))
                    except (TypeError, ValueError):
                        pass
        if all_values:
            stats = {'count': len(all_values), 'sum': round(sum(all_values), 4), 'avg': round(sum(all_values) / len(all_values), 4), 'min': min(all_values), 'max': max(all_values)}
        else:
            stats = {'count': 0}
        return {'success': True, 'file_path': file_path, 'total_rows': total_rows, 'statistics': stats}
    if action == 'query':
        view_result = toolkit_skill.execute(file_path=file_path, action='view')
        if not view_result.get('success'):
            return view_result
        content = view_result.get('content') or []
        if not question:
            return {'success': True, 'data': content[:20]}
        question_lower = question.lower()
        if any((kw in question_lower for kw in ['多少', '总和', '总计', 'total', 'sum'])):
            all_vals = []
            for row in content:
                for cell in row.get('cells') or []:
                    try:
                        all_vals.append(float(cell.get('value')))
                    except (TypeError, ValueError):
                        pass
            total = sum(all_vals) if all_vals else 0
            return {'success': True, 'answer': f'所有数值总和为 {round(total, 4)}', 'total': total}
        if any((kw in question_lower for kw in ['最大', '最高', 'max'])):
            all_vals = [float(c.get('value')) for row in content for c in row.get('cells') or [] if c.get('value') is not None]
            try:
                mx = max(all_vals)
                return {'success': True, 'answer': f'最大值为 {mx}', 'max': mx}
            except ValueError:
                return {'success': True, 'answer': '未找到数值'}
        return {'success': True, 'data': content[:20], 'message': f'已读取前 {min(20, len(content))} 行数据'}
    return {'success': False, 'message': f'未知 excel_analysis action: {action}'}

def _registered_router_generate_office_document(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action != 'execute':
        return {'success': False, 'message': f'未知 generate_office_document action: {action}'}
    payload = dict(params or {})
    payload.setdefault('user_request', user_message)
    try:
        import json
        from app.application.tools.workflow import execute_workflow_tool
        raw = execute_workflow_tool('generate_office_document', payload, workspace_root=runtime_context.get('workspace_root'))
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {'success': False, 'message': str(raw)}
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.error('generate_office_document 执行失败: %s', err, exc_info=True)
        return {'success': False, 'message': f'文档生成失败：{str(err)}'}

def _registered_router_excel_vector_index(action: str, params: dict, runtime_context: dict, profile: str, user_message: str) -> dict:
    if action == 'execute':
        file_path = str(params.get('file_path') or '').strip()
        if not file_path:
            return {'success': False, 'message': '缺少 file_path'}
        index_name = str(params.get('index_name') or '').strip() or None
        index_id = str(params.get('index_id') or '').strip() or None
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_ingest_app_service
            result = get_excel_vector_ingest_app_service().ingest_excel(file_path=file_path, index_name=index_name, index_id=index_id)
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error('excel_vector_index 执行失败: %s', err, exc_info=True)
            return {'success': False, 'message': str(err), 'error_code': 'excel_vector_exception'}
        payload = dict(result or {})
        if payload.get('success') and payload.get('index_id'):
            payload['excel_vector_index_id'] = payload.get('index_id')
            payload['excel_index_id'] = payload.get('index_id')
        return payload
    if action == 'query':
        index_id = str(params.get('index_id') or '').strip()
        query_text = str(params.get('query') or params.get('query_text') or '').strip()
        if not index_id:
            return {'success': False, 'message': '缺少 index_id'}
        if not query_text:
            return {'success': False, 'message': '缺少 query'}
        try:
            top_k = int(params.get('top_k', 5))
        except (TypeError, ValueError):
            top_k = 5
        try:
            from app.fastapi_routes.excel_vector import get_excel_vector_search_app_service
            return dict(get_excel_vector_search_app_service().query(index_id=index_id, query_text=query_text, top_k=top_k) or {})
        except _facade().RECOVERABLE_ERRORS as err:
            _facade().logger.error('excel_vector_index query 失败: %s', err, exc_info=True)
            return {'success': False, 'message': str(err), 'error_code': 'excel_vector_exception'}
    return {'success': False, 'message': f'未知 excel_vector_index action: {action}'}

def _ocr_artifact_payload(*, text: str, file_path: str='', structured_data: dict[str, _facade().Any] | None=None, analysis: dict[str, _facade().Any] | None=None, confidence: _facade().Any=0) -> dict[str, _facade().Any]:
    return {'artifact_type': 'ocr_text', 'name': 'ocr_result', 'source': 'ocr.recognize', 'uri': file_path, 'mime_type': 'image/*', 'summary': 'OCR 解析结果', 'fields': [{'name': key, 'value': value} for (key, value) in dict(structured_data or {}).items() if value not in (None, '', [], {})][:20], 'preview': {'text': text[:1000], 'confidence': confidence, 'structured_data': dict(structured_data or {}), 'analysis': dict(analysis or {})}, 'metadata': {'parser_used': 'ocr', 'text': text, 'success': True}}
