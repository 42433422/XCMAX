"""AI-inferred generic table target.

任何无法归入固定业务目标的表格文件，只要模型能推断出表结构，就落到这里：
表结构按表头指纹复用，行数据以 JSON 保存，按行指纹去重。写入是可撤销的
批量事务，不创建新的业务表，也不修改客户/产品等主数据。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.application.elt.targets.targets_base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)


def _fingerprint(headers: list[str]) -> str:
    return hashlib.sha256("|".join(headers).encode("utf-8")).hexdigest()


def _row_hash(payload: dict[str, Any], keys: list[str]) -> str:
    scope = {key: payload.get(key) for key in keys} if keys else payload
    body = json.dumps(json_safe(scope), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class DynamicTableAdapter(TargetAdapter):
    type = "dynamic_table"
    label = "AI 通用表"
    reversible = True
    fields: tuple[TargetField, ...] = ()
    default_match_keys: tuple[str, ...] = ()
    allow_dynamic_fields = True

    def preview(self, db, data, *, allowed_update_fields, context):
        del db, allowed_update_fields, context
        payload = data if isinstance(data, dict) else {}
        if not any(value not in (None, "") for value in payload.values()):
            return PreviewDecision("skip", reason="empty_dynamic_row")
        return PreviewDecision("new", after=json_safe(payload), reason="dynamic_row")

    @staticmethod
    def _table_spec(context: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        from app.application.elt.service_support import load_json, new_session
        from app.db.models.elt import EltRun

        db = new_session()
        try:
            run = (
                db.query(EltRun)
                .filter(
                    EltRun.id == str(context["run_id"]),
                    EltRun.owner_user_id == int(context["owner_user_id"]),
                )
                .first()
            )
            draft = load_json(run.draft_json, {}) if run is not None else {}
        finally:
            db.close()
        schema = draft.get("dynamic_schema") if isinstance(draft, dict) else None
        schema = schema if isinstance(schema, dict) else {}
        headers = [
            str(item.get("target") or "")
            for item in draft.get("field_mappings") or []
            if isinstance(item, dict) and str(item.get("target") or "").strip()
        ]
        return headers, schema

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        from app.application.elt.service_support import dump_json, new_id, new_session
        from app.db.models.elt import EltDynamicRow, EltDynamicTable
        from app.infrastructure.tenant_scope import tenant_id_for_write

        headers, schema = self._table_spec(context)
        dedupe_keys = [
            str(key) for key in schema.get("dedupe_keys") or [] if str(key) in set(headers)
        ]
        fingerprint = _fingerprint(headers)
        tenant_id = tenant_id_for_write()
        owner_user_id = int(context["owner_user_id"])
        run_id = str(context["run_id"])
        file_name = str(context.get("file_name") or "")
        default_name = Path(file_name).stem[:160] if file_name else "AI 通用表"
        table_name = str(schema.get("table_name") or "").strip()[:160] or default_name
        callback = context.get("progress_callback")
        total = int(context.get("row_count") or 0)

        db = new_session()
        try:
            table = (
                db.query(EltDynamicTable)
                .filter(
                    EltDynamicTable.tenant_id == tenant_id,
                    EltDynamicTable.owner_user_id == owner_user_id,
                    EltDynamicTable.fingerprint == fingerprint,
                )
                .first()
            )
            if table is None:
                table = EltDynamicTable(
                    id=new_id(),
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    name=table_name,
                    fingerprint=fingerprint,
                    headers_json=dump_json(headers),
                    columns_json=dump_json(schema.get("columns") or []),
                    source_file=file_name[:255] or None,
                    row_count=0,
                )
                db.add(table)
                db.flush()
            elif schema.get("columns") and table.columns_json in {"", "[]"}:
                table.columns_json = dump_json(schema.get("columns") or [])

            existing = {
                str(item[0])
                for item in db.query(EltDynamicRow.row_hash)
                .filter(EltDynamicRow.table_id == table.id)
                .all()
            }
            inserted = 0
            duplicates = 0
            for payload in rows:
                if not isinstance(payload, dict):
                    continue
                digest = _row_hash(payload, dedupe_keys)
                if digest in existing:
                    duplicates += 1
                    continue
                existing.add(digest)
                db.add(
                    EltDynamicRow(
                        table_id=table.id,
                        tenant_id=tenant_id,
                        owner_user_id=owner_user_id,
                        run_id=run_id,
                        row_hash=digest,
                        payload_json=dump_json(payload),
                    )
                )
                inserted += 1
                if callable(callback) and inserted % 200 == 0:
                    callback(inserted, max(1, total))
            table.row_count = int(table.row_count or 0) + inserted
            db.commit()
            receipt = {
                "table_id": table.id,
                "table_name": table.name,
                "columns": schema.get("columns") or [],
                "inserted": inserted,
                "duplicates": duplicates,
                "reversible": True,
            }
            if callable(callback):
                callback(inserted, max(1, total))
            return {"receipt": receipt, "executed": inserted}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rollback_batch(self, context: dict[str, Any], receipt: dict[str, Any]) -> int:
        from app.application.elt.service_support import new_session
        from app.db.models.elt import EltDynamicRow, EltDynamicTable
        from app.infrastructure.tenant_scope import tenant_id_for_write

        run_id = str(context["run_id"])
        owner_user_id = int(context["owner_user_id"])
        table_id = str(receipt.get("table_id") or "")
        db = new_session()
        try:
            query = db.query(EltDynamicRow).filter(
                EltDynamicRow.tenant_id == tenant_id_for_write(),
                EltDynamicRow.owner_user_id == owner_user_id,
                EltDynamicRow.run_id == run_id,
            )
            matched = query.all()
            deleted = len(matched)
            if table_id:
                table = db.query(EltDynamicTable).filter(EltDynamicTable.id == table_id).first()
                if table is not None:
                    table.row_count = max(0, int(table.row_count or 0) - deleted)
            for row in matched:
                db.delete(row)
            db.commit()
            return deleted
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


__all__ = ["DynamicTableAdapter"]
