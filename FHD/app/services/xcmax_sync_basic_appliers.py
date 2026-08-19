# ruff: noqa
"""Personnel, organization, attendance, approval, print, and template sync appliers."""
from __future__ import annotations
import json
import logging
import sys
from typing import Any
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger(__name__)

def _facade() -> Any:
    return sys.modules['app.services.xcmax_sync_service']

@_facade().register_entity_applier('personnel')
def _apply_personnel(item: dict[str, Any]) -> None:
    """人员变更：写入 taiyangniao-pro attendance_employees / products。"""
    payload = item.get('payload') or {}
    name = str(payload.get('name') or payload.get('employee_name') or '').strip()
    if not name:
        return
    try:
        import sqlite3
        from datetime import datetime
        from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path
        db_path = resolve_mod_private_sqlite_path('taiyangniao_pro.db')
        conn = sqlite3.connect(str(db_path))
        now = datetime.now().isoformat(timespec='seconds')
        dept = str(payload.get('department') or '').strip()
        conn.execute('\n            INSERT OR IGNORE INTO attendance_employees\n                (source_file, employee_name, department, main_department,\n                 attendance_group, employee_no, position, user_id)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n            ', ('xcmax_sync', name, dept, dept, payload.get('attendance_group') or 'XCmax', payload.get('employee_no') or '', payload.get('position') or '', payload.get('user_id') or ''))
        conn.execute('\n            INSERT INTO products (source_file, model_number, name, specification, price, unit, created_at, updated_at)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n            ', ('xcmax_sync', payload.get('employee_id') or name, name, payload.get('position') or '', 0.0, dept, now, now))
        conn.commit()
        conn.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('apply_personnel failed for %s: %s', name, exc)

@_facade().register_entity_applier('department')
def _apply_department(item: dict[str, Any]) -> None:
    """部门变更：写入 attendance_departments / customers。"""
    payload = item.get('payload') or {}
    dept = str(payload.get('department') or payload.get('customer_name') or '').strip()
    if not dept:
        return
    try:
        import sqlite3
        from datetime import datetime
        from app.mod_sdk.private_sqlite import resolve_mod_private_sqlite_path
        db_path = resolve_mod_private_sqlite_path('taiyangniao_pro.db')
        conn = sqlite3.connect(str(db_path))
        now = datetime.now().isoformat(timespec='seconds')
        conn.execute('\n            INSERT OR IGNORE INTO attendance_departments\n                (source_file, department, main_department, attendance_group)\n            VALUES (?, ?, ?, ?)\n            ', ('xcmax_sync', dept, dept, payload.get('attendance_group') or 'XCmax'))
        conn.execute('\n            INSERT INTO customers (source_file, customer_name, contact_person, contact_phone,\n                                   address, purchase_unit, created_at, updated_at)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?)\n            ', ('xcmax_sync', dept, '', '', '', '', now, now))
        conn.commit()
        conn.close()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('apply_department failed for %s: %s', dept, exc)

@_facade().register_entity_applier('attendance')
def _apply_attendance(item: dict[str, Any]) -> None:
    """考勤记录变更：写入主库 shipment_records 表（考勤行业语义）。"""
    payload = item.get('payload') or {}
    operation = item.get('operation', 'sync')
    try:
        from datetime import datetime as _dt
        from app.db import get_db
        from app.db.models.shipment import ShipmentRecord
        with get_db() as db:
            record_id = payload.get('id')
            if operation == 'delete' and record_id:
                obj = db.query(ShipmentRecord).filter(ShipmentRecord.id == record_id).first()
                if obj:
                    db.delete(obj)
                    db.commit()
                return
            purchase_unit = str(payload.get('purchase_unit') or payload.get('employee_name') or '').strip()
            product_name = str(payload.get('product_name') or payload.get('attendance_group') or '').strip()
            if not purchase_unit or not product_name:
                return
            if record_id:
                obj = db.query(ShipmentRecord).filter(ShipmentRecord.id == record_id).first()
            else:
                obj = None
            if obj:
                for col in ('purchase_unit', 'product_name', 'model_number', 'status', 'raw_text'):
                    if col in payload:
                        setattr(obj, col, payload[col])
                obj.updated_at = _dt.now()
            else:
                obj = ShipmentRecord(purchase_unit=purchase_unit, product_name=product_name, model_number=str(payload.get('model_number') or ''), quantity_kg=float(payload.get('quantity_kg') or 0), quantity_tins=int(payload.get('quantity_tins') or 0), status=str(payload.get('status') or 'pending'), created_at=_dt.now(), updated_at=_dt.now())
                db.add(obj)
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('apply_attendance failed: %s', exc)

@_facade().register_entity_applier('approval')
def _apply_approval(item: dict[str, Any]) -> None:
    """审批请求变更：更新 approval_requests 表的状态字段。"""
    payload = item.get('payload') or {}
    operation = item.get('operation', 'sync')
    try:
        from datetime import datetime as _dt
        from app.db import get_db
        from app.db.models.approval import ApprovalRequest
        with get_db() as db:
            record_id = payload.get('id')
            if not record_id:
                return
            obj = db.query(ApprovalRequest).filter(ApprovalRequest.id == record_id).first()
            if not obj:
                return
            if operation == 'delete':
                db.delete(obj)
            else:
                for col in ('status', 'title', 'description', 'priority', 'applicant_name'):
                    if col in payload:
                        setattr(obj, col, payload[col])
                obj.updated_at = _dt.now()
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('apply_approval failed: %s', exc)

@_facade().register_entity_applier('approval_flow')
def _apply_approval_flow(item: dict[str, Any]) -> None:
    """审批流程定义变更：同步 approval_flows 表的 is_active 和配置字段。"""
    payload = item.get('payload') or {}
    try:
        from datetime import datetime as _dt
        from app.db import get_db
        from app.db.models.approval import ApprovalFlow
        with get_db() as db:
            flow_key = str(payload.get('flow_key') or '').strip()
            if not flow_key:
                return
            obj = db.query(ApprovalFlow).filter(ApprovalFlow.flow_key == flow_key).first()
            if obj:
                for col in ('flow_name', 'description', 'is_active', 'timeout_hours'):
                    if col in payload:
                        setattr(obj, col, payload[col])
                obj.updated_at = _dt.now()
                db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.warning('apply_approval_flow failed: %s', exc)

@_facade().register_entity_applier('print_job')
def _apply_print_job(item: dict[str, Any]) -> None:
    """打印任务变更：写入打印作业日志表（若存在），否则记录结构化日志。"""
    payload = item.get('payload') or {}
    operation = item.get('operation', 'sync')
    try:
        from app.db import get_db
        with get_db() as db:
            from sqlalchemy import text
            db.execute(text('\n                INSERT INTO print_jobs (entity_id, template, status, payload_json, created_at)\n                VALUES (:eid, :tpl, :status, :payload, NOW())\n                ON CONFLICT (entity_id) DO UPDATE SET\n                    status = EXCLUDED.status,\n                    payload_json = EXCLUDED.payload_json\n            '), {'eid': item.get('entity_id') or '', 'tpl': str(payload.get('template') or ''), 'status': str(payload.get('status') or operation), 'payload': _facade().json.dumps(payload, ensure_ascii=False, default=str)})
            db.commit()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.info('print_job sync [%s] entity=%s status=%s', operation, item.get('entity_id'), payload.get('status'))

@_facade().register_entity_applier('template')
def _apply_template(item: dict[str, Any]) -> None:
    """文档/打印模板变更：更新 document_templates 表或本地模板文件路径记录。"""
    payload = item.get('payload') or {}
    operation = item.get('operation', 'sync')
    try:
        from sqlalchemy import text
        from app.db import get_db
        template_id = str(payload.get('template_id') or item.get('entity_id') or '').strip()
        if not template_id:
            return
        with get_db() as db:
            if operation == 'delete':
                db.execute(text('DELETE FROM document_templates WHERE slug = :s'), {'s': template_id})
            else:
                db.execute(text('\n                    INSERT INTO document_templates (slug, name, category, is_active, created_at)\n                    VALUES (:slug, :name, :cat, true, NOW())\n                    ON CONFLICT (slug) DO UPDATE SET\n                        name = EXCLUDED.name,\n                        category = EXCLUDED.category\n                '), {'slug': template_id, 'name': str(payload.get('name') or template_id), 'cat': str(payload.get('category') or 'word')})
            db.commit()
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.debug('apply_template non-fatal: %s', exc)
