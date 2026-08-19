"""Shipment ETL and extraction-log routes for Excel data."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes.excel_extract import (
    TEMP_EXCEL_DIR,
    _form_include_ledger,
    _form_truthy,
    logger,
    router,
)
from app.infrastructure.auth.dependencies import require_identified_user
from app.utils.operational_errors import RECOVERABLE_ERRORS


@router.post('/shipment-etl/preview')
async def shipment_etl_preview(file: UploadFile | None=File(default=None), file_path: str=Form(''), workspace_root: str=Form(''), include_ledger: str=Form('auto'), save_as_template: str=Form('0'), template_name: str=Form(''), template_scope: str=Form('')):
    """预览：按内容指纹识别送货单/出货流水并抽取抬头+明细（不写业务库）。

    ``save_as_template=1`` 时额外把源办公文件解析入库模版库。
    """
    try:
        from app.application.office_template_ingest_app_service import (
            attach_template_ingest_to_etl_result,
        )
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        path = str(file_path or '').strip()
        tmp_path = ''
        if file is not None and (file.filename or '').strip():
            raw = await file.read()
            name = Path(str(file.filename or 'shipment.xlsx')).name
            tmp_path = os.path.join(TEMP_EXCEL_DIR, f"etl_{datetime.now().strftime('%Y%m%d%H%M%S')}_{name}")
            with open(tmp_path, 'wb') as fh:
                fh.write(raw)
            path = tmp_path
        if not path:
            return JSONResponse({'success': False, 'message': '请上传文件或提供 file_path'}, status_code=400)
        result = get_shipment_excel_etl_app_service().preview(path, include_ledger=_form_include_ledger(include_ledger), workspace_root=str(workspace_root or '').strip() or None)
        if tmp_path:
            result['uploaded_temp_path'] = tmp_path
        result = attach_template_ingest_to_etl_result(result, file_path=path, save_as_template=_form_truthy(save_as_template, False), template_name=str(template_name or '').strip(), template_scope=str(template_scope or '').strip(), source='shipment_excel_etl_preview')
        return JSONResponse(result, status_code=200 if result.get('success') else 400)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl preview failed: %s', e)
        return JSONResponse({'success': False, 'message': '单据预览失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/execute')
async def shipment_etl_execute(request: Request, file: UploadFile | None=File(default=None), file_path: str=Form(''), workspace_root: str=Form(''), notes_json: str=Form(''), import_products: str=Form('1'), import_shipments: str=Form('1'), idempotent: str=Form('1'), include_ledger: str=Form('0'), confirm_ledger: str=Form('0'), dry_run: str=Form('0'), direct: str=Form('0'), force_shipment_target: str=Form('0'), save_as_template: str=Form('0'), template_name: str=Form(''), template_scope: str=Form(''), _user: Any=Depends(require_identified_user)):
    """执行闭环：单据 → 客户/产品/发货单（默认幂等；流水需 confirm_ledger）。

    direct=1：无预览直写（需环境开关 FHD_EXCEL_ETL_ALLOW_DIRECT=1）。
    save_as_template=1：额外把源办公文件解析入库模版库。
    """
    try:
        import json

        from app.application.office_template_ingest_app_service import (
            attach_template_ingest_to_etl_result,
        )
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        try:
            from app.application.facades.session_facade import get_auth_service
            from app.infrastructure.auth.dependencies import resolve_session_user
            from app.utils.deployment import deployment_is_production, deployment_is_staging
            require_rbac = os.environ.get('FHD_SHIPMENT_ETL_REQUIRE_RBAC', '').strip().lower()
            if require_rbac == '':
                require_rbac_flag = deployment_is_production() or deployment_is_staging()
            else:
                require_rbac_flag = require_rbac in {'1', 'true', 'yes', 'on'}
            sess_user = resolve_session_user(request)
            if require_rbac_flag:
                if sess_user is None:
                    return JSONResponse({'success': False, 'message': '请先登录', 'error_code': 'unauthorized'}, status_code=401)
                if not get_auth_service().has_permission(sess_user, 'shipment.create'):
                    return JSONResponse({'success': False, 'message': '缺少 shipment.create 权限', 'error_code': 'forbidden'}, status_code=403)
            elif sess_user is not None and hasattr(get_auth_service(), 'has_permission'):
                if not get_auth_service().has_permission(sess_user, 'shipment.create'):
                    if os.environ.get('FHD_SHIPMENT_ETL_REQUIRE_RBAC', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
                        return JSONResponse({'success': False, 'message': '缺少 shipment.create 权限', 'error_code': 'forbidden'}, status_code=403)
        except RECOVERABLE_ERRORS:
            pass
        path = str(file_path or '').strip()
        if file is not None and (file.filename or '').strip():
            raw = await file.read()
            name = Path(str(file.filename or 'shipment.xlsx')).name
            path = os.path.join(TEMP_EXCEL_DIR, f"etl_exec_{datetime.now().strftime('%Y%m%d%H%M%S')}_{name}")
            with open(path, 'wb') as fh:
                fh.write(raw)
        notes = None
        raw_notes = str(notes_json or '').strip()
        if raw_notes:
            try:
                loaded = json.loads(raw_notes)
                if isinstance(loaded, list):
                    notes = loaded
                elif isinstance(loaded, dict) and isinstance(loaded.get('notes'), list):
                    notes = loaded.get('notes')
            except json.JSONDecodeError:
                return JSONResponse({'success': False, 'message': 'notes_json 不是合法 JSON', 'error_code': 'bad_notes'}, status_code=400)
        if not path and notes is None:
            return JSONResponse({'success': False, 'message': '请上传文件、提供 file_path，或提交 notes_json'}, status_code=400)
        result = get_shipment_excel_etl_app_service().execute(path or '', import_products=_form_truthy(import_products, True), import_shipments=_form_truthy(import_shipments, True), idempotent=_form_truthy(idempotent, True), include_ledger=_form_include_ledger(include_ledger, default='0'), confirm_ledger=_form_truthy(confirm_ledger, False), dry_run=_form_truthy(dry_run, False), direct=_form_truthy(direct, False), force_shipment_target=_form_truthy(force_shipment_target, False), notes=notes, workspace_root=str(workspace_root or '').strip() or None)
        result = attach_template_ingest_to_etl_result(result, file_path=path, save_as_template=_form_truthy(save_as_template, False), template_name=str(template_name or '').strip(), template_scope=str(template_scope or '').strip(), source='shipment_excel_etl_execute')
        status = 200 if result.get('success') or result.get('dry_run') else 400
        if result.get('error_code') == 'unsafe_path':
            status = 400
        if result.get('error_code') == 'ledger_confirm_required':
            status = 409
        if result.get('error_code') == 'direct_execute_denied':
            status = 403
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl execute failed: %s', e)
        return JSONResponse({'success': False, 'message': '单据入库失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/ocr-preview')
async def shipment_etl_ocr_preview(file: UploadFile | None=File(default=None), file_path: str=Form(''), workspace_root: str=Form(''), include_ledger: str=Form('auto'), _user: Any=Depends(require_identified_user)):
    """扫描件/图片/PDF OCR → 表格 → 单据预览。"""
    try:
        from app.application.shipment_excel_etl_app_service import preview_shipment_excel_etl
        from app.application.shipment_excel_etl_ocr import parse_ocr_document
        path = str(file_path or '').strip()
        if file is not None and (file.filename or '').strip():
            raw = await file.read()
            name = Path(str(file.filename or 'scan.png')).name
            path = os.path.join(TEMP_EXCEL_DIR, f"etl_ocr_{datetime.now().strftime('%Y%m%d%H%M%S')}_{name}")
            with open(path, 'wb') as fh:
                fh.write(raw)
        if not path:
            return JSONResponse({'success': False, 'message': '请上传扫描件或提供 file_path'}, status_code=400)
        suffix = Path(path).suffix.lower()
        if suffix in {'.xlsx', '.xlsm', '.xls'}:
            result = preview_shipment_excel_etl(path, include_ledger=_form_include_ledger(include_ledger, default='auto'), workspace_root=str(workspace_root or '').strip() or None)
        else:
            parsed = parse_ocr_document(path, include_ledger=_form_include_ledger(include_ledger, default='auto'), workspace_root=str(workspace_root or '').strip() or None)
            if not parsed.get('success'):
                return JSONResponse(parsed, status_code=400)
            ocr_xlsx = (parsed.get('ocr') or {}).get('file_path') or ''
            if ocr_xlsx:
                preview = preview_shipment_excel_etl(ocr_xlsx, include_ledger=_form_include_ledger(include_ledger, default='auto'), workspace_root=str(workspace_root or '').strip() or None)
                result = {**preview, 'ocr': parsed.get('ocr'), 'source_path': parsed.get('source_path')}
            else:
                result = parsed
        status = 200 if result.get('success') else 400
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl ocr-preview failed: %s', e)
        return JSONResponse({'success': False, 'message': 'OCR 预览失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/batch-preview')
async def shipment_etl_batch_preview(directory: str=Form(''), workspace_root: str=Form(''), include_ledger: str=Form('auto'), _user: Any=Depends(require_identified_user)):
    """批量预览目录内 xlsx 送货单/出货流水。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        root = str(directory or '').strip()
        if not root:
            return JSONResponse({'success': False, 'message': '缺少 directory'}, status_code=400)
        result = get_shipment_excel_etl_app_service().batch_preview(root, include_ledger=_form_include_ledger(include_ledger), workspace_root=str(workspace_root or '').strip() or None)
        return JSONResponse(result, status_code=200 if result.get('success') else 400)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl batch preview failed: %s', e)
        return JSONResponse({'success': False, 'message': '批量预览失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/batch-execute')
async def shipment_etl_batch_execute(directory: str=Form(''), workspace_root: str=Form(''), include_ledger: str=Form('0'), confirm_ledger: str=Form('0'), idempotent: str=Form('1'), import_products: str=Form('1'), import_shipments: str=Form('1'), dry_run: str=Form('0'), _user: Any=Depends(require_identified_user)):
    """批量执行目录内 xlsx 闭环入库（默认关闭，需 FHD_SHIPMENT_ETL_ALLOW_BATCH=1）。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        root = str(directory or '').strip()
        if not root:
            return JSONResponse({'success': False, 'message': '缺少 directory'}, status_code=400)
        result = get_shipment_excel_etl_app_service().batch_execute(root, include_ledger=_form_include_ledger(include_ledger, default='0'), confirm_ledger=_form_truthy(confirm_ledger, False), idempotent=_form_truthy(idempotent, True), import_products=_form_truthy(import_products, True), import_shipments=_form_truthy(import_shipments, True), dry_run=_form_truthy(dry_run, False), workspace_root=str(workspace_root or '').strip() or None)
        status = 200 if result.get('success') or result.get('dry_run') else 400
        if result.get('error_code') == 'batch_disabled':
            status = 403
        return JSONResponse(result, status_code=status)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl batch execute failed: %s', e)
        return JSONResponse({'success': False, 'message': '批量入库失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/generate-template')
async def shipment_etl_generate_template(kind: str=Form('delivery'), output_path: str=Form(''), unit_name: str=Form('闭环测试客户'), _user: Any=Depends(require_identified_user)):
    """生成测试用送货单或出货流水模板（输出限沙箱）。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        from app.application.shipment_excel_etl_security import (
            ShipmentEtlPathError,
            resolve_etl_output_path,
        )
        svc = get_shipment_excel_etl_app_service()
        out = str(output_path or '').strip()
        if not out:
            out = os.path.join(TEMP_EXCEL_DIR, f"etl_tpl_{kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx")
        try:
            out = str(resolve_etl_output_path(out))
        except ShipmentEtlPathError:
            return JSONResponse({'success': False, 'message': '非法输出路径', 'error_code': 'unsafe_path'}, status_code=400)
        kind_norm = str(kind or 'delivery').strip().lower()
        if kind_norm in {'ledger', 'shipment_ledger', '出货流水'}:
            result = svc.write_ledger_template([], out, unit_name=str(unit_name or '流水测试客户'))
        else:
            result = svc.write_delivery_template([{'unit_name': str(unit_name or '闭环测试客户'), 'contact_person': '测试联系人', 'order_date': '2026年07月24日', 'order_number': 'LOOP-0001', 'sheet': '送货单', 'items': [{'model_number': 'RX-LOOP', 'product_name': 'PU哑光清漆', 'quantity_tins': 2, 'tin_spec': 25, 'quantity_kg': 50, 'unit_price': 18, 'amount': 900}]}], out)
        return JSONResponse(result, status_code=200 if result.get('success') else 400)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl generate template failed: %s', e)
        return JSONResponse({'success': False, 'message': '单据处理失败，请稍后重试'}, status_code=500)

@router.post('/shipment-etl/regenerate')
async def shipment_etl_regenerate(file_path: str=Form(''), output_path: str=Form(''), workspace_root: str=Form(''), include_ledger: str=Form('auto'), _user: Any=Depends(require_identified_user)):
    """解析已有单据并按标准送货单版式反推再出单。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        from app.application.shipment_excel_etl_security import (
            ShipmentEtlPathError,
            resolve_etl_output_path,
            resolve_etl_path,
        )
        src = str(file_path or '').strip()
        if not src:
            return JSONResponse({'success': False, 'message': '缺少 file_path'}, status_code=400)
        wr = str(workspace_root or '').strip() or None
        try:
            src_resolved = str(resolve_etl_path(src, workspace_root=wr, must_exist=True))
        except ShipmentEtlPathError:
            return JSONResponse({'success': False, 'message': '非法文件路径', 'error_code': 'unsafe_path'}, status_code=400)
        out = str(output_path or '').strip()
        if not out:
            out = os.path.join(TEMP_EXCEL_DIR, f"etl_regen_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx")
        try:
            out = str(resolve_etl_output_path(out, workspace_root=wr))
        except ShipmentEtlPathError:
            return JSONResponse({'success': False, 'message': '非法输出路径', 'error_code': 'unsafe_path'}, status_code=400)
        result = get_shipment_excel_etl_app_service().regenerate(src_resolved, out, include_ledger=_form_include_ledger(include_ledger))
        return JSONResponse(result, status_code=200 if result.get('success') else 400)
    except RECOVERABLE_ERRORS as e:
        logger.exception('shipment etl regenerate failed: %s', e)
        return JSONResponse({'success': False, 'message': '单据处理失败，请稍后重试'}, status_code=500)

@router.get('/logs')
def get_extract_logs(data_type: str | None=Query(default=None), status: str | None=Query(default=None), limit: int=Query(default=50), offset: int=Query(default=0)):
    try:
        from app.bootstrap import get_extract_log_service
        log_service = get_extract_log_service()
        logs = log_service.get_logs(data_type=data_type, status=status, limit=limit, offset=offset)
        return JSONResponse({'success': True, 'logs': logs, 'total': len(logs)})
    except RECOVERABLE_ERRORS as e:
        logger.error('获取提取日志失败：%s', e)
        return JSONResponse({'success': False, 'message': f'获取失败：{str(e)}'}, status_code=500)

@router.get('/logs/{log_id}')
def get_extract_log(log_id: int):
    try:
        from app.bootstrap import get_extract_log_service
        log_service = get_extract_log_service()
        log = log_service.get_log(log_id)
        if not log:
            return JSONResponse({'success': False, 'message': '日志不存在'}, status_code=404)
        return JSONResponse({'success': True, 'log': log})
    except RECOVERABLE_ERRORS as e:
        logger.error('获取提取日志详情失败：%s', e)
        return JSONResponse({'success': False, 'message': f'获取失败：{str(e)}'}, status_code=500)

@router.get('/preview/{log_id}')
def get_preview(log_id: int):
    try:
        from app.bootstrap import get_extract_log_service
        log_service = get_extract_log_service()
        log = log_service.get_log(log_id)
        if not log:
            return JSONResponse({'success': False, 'message': '日志不存在'}, status_code=404)
        return JSONResponse({'success': True, 'log': log, 'message': '预览数据需要从提取源获取'})
    except RECOVERABLE_ERRORS as e:
        logger.error('获取预览失败：%s', e)
        return JSONResponse({'success': False, 'message': f'获取失败：{str(e)}'}, status_code=500)
