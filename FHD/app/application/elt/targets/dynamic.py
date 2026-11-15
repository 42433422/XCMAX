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

from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.application.elt.targets.targets_base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.utils.operational_errors import BOUNDARY_ERRORS

# 单事务插入上万行会长时间独占 SQLite 写锁，让并发 worker 的租约校验等到超时。
# 按批提交把写锁占用压到毫秒级，回滚仍按 run_id 删除，不受分批影响。
_CHUNK_SIZE = 500
_LOCK_ERRORS = ("database is locked", "database table is locked", "database schema is locked")
# 执行层把每行的来源坐标（sheet / 区块）挂在这个键上，适配器据此按 sheet、分片建多张表；
# 写入前会移除该键，不会落进业务数据。
PARTITION_MARKER = "__elt_partition__"


def _is_lock_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _LOCK_ERRORS)


def _fingerprint(headers: list[str], marker: dict[str, Any] | None = None) -> str:
    """表的身份＝表头 + 来源区块。

    同一 sheet 里并排的多个区块常常共用同一套列名；只按表头做指纹会把
    它们合成一张表，再把内容相同的行当成重复丢掉。
    """
    material = "|".join(headers)
    if marker:
        material += f"#sheet={marker.get('sheet') or ''}#table={marker.get('table_id') or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _row_hash(payload: dict[str, Any], keys: list[str]) -> str:
    scope = {key: payload.get(key) for key in keys} if keys else payload
    body = json.dumps(json_safe(scope), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _group_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """按来源 sheet / 区块分组：一个 sheet（或横向区块）就是一张通用表。"""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in rows:
        if not isinstance(payload, dict):
            continue
        marker = payload.get(PARTITION_MARKER)
        marker = marker if isinstance(marker, dict) else {}
        # 映射会为所有 sheet 的字段补齐空值；落库前去掉空值，
        # 否则每张分表都会被别的 sheet 的空列撑成一张宽表。
        cleaned = {
            str(key): value
            for key, value in payload.items()
            if key != PARTITION_MARKER and value not in (None, "")
        }
        if not cleaned:
            continue
        key = (str(marker.get("sheet") or ""), str(marker.get("table_id") or ""))
        group = groups.get(key)
        if group is None:
            group = {"marker": marker, "rows": [], "identities": []}
            groups[key] = group
        group["rows"].append(cleaned)
        group["identities"].append(
            (
                str(marker.get("sheet") or ""),
                str(marker.get("table_id") or ""),
                str(marker.get("row") or ""),
            )
        )
    return [groups[key] for key in sorted(groups)]


def _usable_dedupe_keys(
    dedupe_keys: list[str], headers: list[str], rows: list[dict[str, Any]]
) -> list[str]:
    """只保留在本分片里有区分度的去重键。

    模型常把「备注」「已付款」这类列当成主键；照它去重会把几千行正常数据
    折叠成几十行。区分度不足一半的键一律不参与去重，退回按来源坐标去重。
    """
    present = set(headers)
    usable: list[str] = []
    total = len(rows)
    for key in dedupe_keys:
        if key not in present:
            continue
        distinct = len(
            {json.dumps(json_safe(row.get(key)), ensure_ascii=False, default=str) for row in rows}
        )
        if total and distinct / total >= 0.5:
            usable.append(key)
    return usable


def _partition_columns(schema_columns: list[Any], headers: list[str]) -> list[dict[str, Any]]:
    """每张分表只保留本表实际出现的列，未推断到语义的列按原始表头登记。"""
    known: dict[str, dict[str, Any]] = {}
    for column in schema_columns:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or column.get("source") or "").strip()
        if name:
            known[name] = column
    columns: list[dict[str, Any]] = []
    for header in headers:
        column = known.get(header)
        if column is not None:
            columns.append(
                {
                    **column,
                    "source": str(column.get("source") or header),
                    "name": header,
                }
            )
        else:
            columns.append(
                {"source": header, "name": header, "type": "string", "role": "dimension"}
            )
    return columns


def _partition_headers(rows: list[dict[str, Any]], ordered: list[str]) -> list[str]:
    """本分片实际出现的列；顺序沿用全局映射，额外列按出现顺序补在后面。"""
    present: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            text = str(key)
            if text not in seen:
                seen.add(text)
                present.append(text)
    headers = [header for header in ordered if header in seen]
    headers.extend(header for header in present if header not in headers)
    return headers


def _partition_name(marker: dict[str, Any], default_name: str, index: int) -> str:
    """分片表名用文件自己的 sheet/区块名，不按表头另起名字。"""
    title = str(marker.get("table_title") or "").strip()
    sheet = str(marker.get("sheet") or "").strip()
    # 整张 sheet 回退成宽表时，区块标题只是其中一小块的标题，不能拿来命名整张表。
    if sheet and not str(marker.get("table_id") or "").strip():
        return sheet[:160]
    return (title or sheet or f"{default_name}-{index + 1}")[:160]


def _unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        return name
    suffix = 2
    while f"{name}-{suffix}" in used:
        suffix += 1
    return f"{name}-{suffix}"


@retry(
    retry=retry_if_exception(_is_lock_error),
    wait=wait_exponential(multiplier=0.2, max=3),
    stop=stop_after_attempt(6),
    reraise=True,
)
def _insert_chunk(db, chunk: list[dict[str, Any]]) -> int:
    """幂等批量插入一批行，返回真正新增的行数。

    依赖唯一约束 ``(table_id, row_hash)`` 冲突即忽略：重复导入同文件不会产生
    重复行，也不需要在 Python 侧先拉全表指纹。遇到 SQLite 写锁按指数退避重试，
    重试只在当前批次上发生，不会让整个文件重来。
    """
    from app.db.models.elt import EltDynamicRow

    table = EltDynamicRow.__table__
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    try:
        result = db.execute(
            dialect_insert(table).on_conflict_do_nothing(index_elements=["table_id", "row_hash"]),
            chunk,
        )
        db.commit()
        return int(result.rowcount or 0)
    except OperationalError:
        db.rollback()
        raise


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
        tenant_id = tenant_id_for_write()
        owner_user_id = int(context["owner_user_id"])
        run_id = str(context["run_id"])
        file_name = str(context.get("file_name") or "")
        default_name = Path(file_name).stem[:160] if file_name else "AI 通用表"
        table_name = str(schema.get("table_name") or "").strip()[:160] or default_name
        callback = context.get("progress_callback")
        total = int(context.get("row_count") or 0)

        # 一个 sheet / 区块一张表：分组后逐表建表、逐表去重、逐表分批提交。
        partitions = _group_rows(rows)
        db = new_session()
        try:
            tables: list[dict[str, Any]] = []
            attempted_total = 0
            inserted_total = 0
            used_names: set[str] = set()
            for index, group in enumerate(partitions):
                part_rows = group["rows"]
                part_headers = _partition_headers(part_rows, headers)
                if not part_headers:
                    continue
                part_name = table_name
                if len(partitions) > 1:
                    part_name = _unique_name(
                        _partition_name(group["marker"], default_name, index), used_names
                    )
                used_names.add(part_name)
                part_dedupe = _usable_dedupe_keys(dedupe_keys, part_headers, part_rows)
                part_columns = _partition_columns(schema.get("columns") or [], part_headers)
                fingerprint = _fingerprint(part_headers, group["marker"])
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
                        name=part_name,
                        fingerprint=fingerprint,
                        headers_json=dump_json(part_headers),
                        columns_json=dump_json(part_columns),
                        source_file=file_name[:255] or None,
                        row_count=0,
                    )
                    db.add(table)
                elif table.columns_json in {"", "[]"}:
                    table.columns_json = dump_json(part_columns)
                db.commit()
                table_id = str(table.id)

                attempted = 0
                inserted = 0
                chunk: list[dict[str, Any]] = []
                for payload, identity in zip(part_rows, group["identities"], strict=False):
                    # 没有显式去重键时按来源坐标去重：同一份文件重复导入仍幂等，
                    # 但不会把不同位置、内容相同的业务行误判成重复丢掉。
                    hash_source = (
                        payload if part_dedupe else {**payload, "__source__": "|".join(identity)}
                    )
                    chunk.append(
                        {
                            "table_id": table_id,
                            "tenant_id": tenant_id,
                            "owner_user_id": owner_user_id,
                            "run_id": run_id,
                            "row_hash": _row_hash(hash_source, part_dedupe),
                            "payload_json": dump_json(payload),
                        }
                    )
                    attempted += 1
                    if len(chunk) >= _CHUNK_SIZE:
                        inserted += _insert_chunk(db, chunk)
                        chunk = []
                        if callable(callback):
                            callback(inserted_total + inserted, max(1, total))
                if chunk:
                    inserted += _insert_chunk(db, chunk)

                # 以目标库实际行数为准回写，避免「以为写进去了」。
                actual = int(
                    db.query(func.count())
                    .select_from(EltDynamicRow)
                    .filter(EltDynamicRow.table_id == table_id)
                    .scalar()
                    or 0
                )
                db.query(EltDynamicTable).filter(EltDynamicTable.id == table_id).update(
                    {"row_count": actual}, synchronize_session=False
                )
                db.commit()
                attempted_total += attempted
                inserted_total += inserted
                tables.append(
                    {
                        "table_id": table_id,
                        "table_name": part_name,
                        "headers": part_headers,
                        "columns": part_columns,
                        "inserted": inserted,
                        "duplicates": max(0, attempted - inserted),
                        "row_count": actual,
                    }
                )
            primary = (
                tables[0]
                if tables
                else {
                    "table_id": "",
                    "table_name": table_name,
                    "columns": schema.get("columns") or [],
                    "row_count": 0,
                }
            )
            receipt = {
                "table_id": primary.get("table_id", ""),
                "table_name": primary.get("table_name", table_name),
                "columns": primary.get("columns") or schema.get("columns") or [],
                "inserted": inserted_total,
                "duplicates": max(0, attempted_total - inserted_total),
                "row_count": primary.get("row_count", 0),
                "tables": tables,
                "reversible": True,
            }
            if callable(callback):
                callback(inserted_total, max(1, total))
            return {"receipt": receipt, "executed": inserted_total}
        except BOUNDARY_ERRORS:
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
        db = new_session()
        try:
            query = db.query(EltDynamicRow).filter(
                EltDynamicRow.tenant_id == tenant_id_for_write(),
                EltDynamicRow.owner_user_id == owner_user_id,
                EltDynamicRow.run_id == run_id,
            )
            matched = query.all()
            deleted = len(matched)
            # 多分片导入时按表分别扣减，单表回执（旧数据）仍按原字段处理。
            per_table: dict[str, int] = {}
            for row in matched:
                table_id = str(row.table_id or "")
                per_table[table_id] = per_table.get(table_id, 0) + 1
            for table_id, delta in per_table.items():
                table = db.query(EltDynamicTable).filter(EltDynamicTable.id == table_id).first()
                if table is not None:
                    table.row_count = max(0, int(table.row_count or 0) - delta)
            for row in matched:
                db.delete(row)
            db.commit()
            return deleted
        except BOUNDARY_ERRORS:
            db.rollback()
            raise
        finally:
            db.close()


__all__ = ["DynamicTableAdapter", "PARTITION_MARKER"]
