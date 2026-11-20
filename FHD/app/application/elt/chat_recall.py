"""Bind reversible ELT writes to the chat step that confirmed them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.application.elt.errors import EltConflict
from app.application.elt.service_support import dump_json, load_json
from app.db.models.elt import EltRun, EltRunRow
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.request_active_mod_ctx import get_request_active_mod_id

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_ORIGIN_KEY = "chat_import_origin"
_REQUIRED_IDENTITY = ("conversation_id", "turn_id", "run_id", "step_id")
_TARGETS = {"customers", "products", "customer_products"}
_NO_SOURCE = {"missing_upload", "upload_not_found", "upload_missing"}
_KNOWLEDGE_SKIPS = _NO_SOURCE | {
    "empty_document",
    "duplicate_content_hash",
    "duplicate_source_fingerprint",
    "source_exists_update_not_confirmed",
}
_TEMPLATE_SKIPS = _NO_SOURCE | {"no_region"}


@dataclass(frozen=True)
class ImportRollback:
    run_id: str
    origin: dict[str, str]
    rows: int


def _origin(context: dict) -> dict[str, str]:
    origin = {key: str(context.get(key) or "").strip() for key in _REQUIRED_IDENTITY}
    return (
        {**origin, "mod_id": str(get_request_active_mod_id() or "")} if all(origin.values()) else {}
    )


def record_import_origin(run: EltRun, context: dict | None) -> None:
    """Call inside the transaction that wins the execute-queue claim."""
    details = load_json(run.summary_json, {})
    origin = _origin(context or {})
    if not origin and _ORIGIN_KEY not in details:
        return
    if origin and not run.executed_at and not run.executed_rows:
        details[_ORIGIN_KEY] = origin
    else:
        # An execution with earlier committed rows has more than one origin.
        details.pop(_ORIGIN_KEY, None)
    run.summary_json = dump_json(details)


def _member_receipts(output: dict) -> list[dict]:
    if (
        output.get("success") is not True
        or output.get("outcome") in {"unknown", "partial"}
        or output.get("reconciliation_required")
    ):
        raise EltConflict("ELT_RECALL_INCOMPLETE", "入库结果未完整确认，请先在数据对接中心核对。")
    if output.get("batch") is not True:
        if "results" in output:
            raise EltConflict("ELT_RECALL_INCOMPLETE", "缺少完整的批量入库回执。")
        return [output]
    members = output.get("results")
    if (
        not isinstance(members, list)
        or not members
        or output.get("run_count") != len(members)
        or output.get("done_count") != len(members)
        or output.get("deferred_count") != 0
        or output.get("pending_count") != 0
        or any(
            not isinstance(item, dict)
            or item.get("success") is not True
            or item.get("outcome") in {"unknown", "partial"}
            or item.get("reconciliation_required")
            for item in members
        )
    ):
        raise EltConflict("ELT_RECALL_INCOMPLETE", "缺少完整的批量入库回执。")
    return list(reversed(members))


def _valid_skip(data: dict, key: str, reasons: set[str]) -> bool:
    receipt = data.get(key)
    return (
        isinstance(receipt, dict)
        and receipt.get("action") == "skip"
        and receipt.get("reason") in reasons
    )


def _checked_run(
    db: Session, item: ImportRollback, *, owner_user_id: int, tenant_id: int
) -> EltRun:
    if tenant_id <= 0 or owner_user_id <= 0 or tenant_id_for_write() != tenant_id:
        raise EltConflict("ELT_RECALL_SCOPE", "当前企业或账号与入库回执不一致。")
    run = (
        db.query(EltRun)
        .filter_by(id=item.run_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        .populate_existing()
        .one_or_none()
    )
    details = load_json(run.summary_json, {}) if run is not None else {}
    if run is None or not isinstance(details, dict) or details.get(_ORIGIN_KEY) != item.origin:
        raise EltConflict(
            "ELT_RECALL_SCOPE", "无法核实该笔入库由此轮对话提交，请在数据对接中心核对。"
        )
    if (
        run.target_type not in _TARGETS
        or details.get("linked_customer_products_preview")
        or details.get("linked_from_shipment_preview")
    ):
        raise EltConflict(
            "ELT_RECALL_UNSUPPORTED", "这次入库涉及其他目标或关联入库，请在原任务中核对。"
        )
    receipt = load_json(run.receipt_json, {})
    if (
        not isinstance(receipt, dict)
        or run.status != "completed"
        or not run.confirmed_at
        or not run.executed_at
        or not run.reversible
        or run.operation_token
        or run.rollback_status not in {None, "failed", "completed"}
        or run.executed_rows != item.rows
        or receipt.get("run_id") != run.id
        or receipt.get("executed_rows") != item.rows
        or receipt.get("partial") is not False
    ):
        raise EltConflict("ELT_RECALL_INCOMPLETE", "入库或撤回结果待核对，已保留原对话。")
    rows = (
        db.query(EltRunRow)
        .filter_by(run_id=run.id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        .filter(EltRunRow.execution_status.in_(("success", "rolled_back")))
        .count()
    )
    if rows != item.rows or (
        run.rollback_status == "completed" and not _confirmed_rollback(receipt, item)
    ):
        raise EltConflict("ELT_RECALL_INCOMPLETE", "入库行与回执不一致，请在原任务中核对。")
    return run


def _confirmed_rollback(receipt: dict, item: ImportRollback) -> bool:
    rollback = receipt.get("rollback")
    return (
        isinstance(rollback, dict)
        and rollback.get("status") == "completed"
        and rollback.get("rows") == item.rows
    )


def prepare_import_rollback(
    db: Session,
    *,
    candidates: list[tuple[dict, dict]],
    owner_user_id: int,
    tenant_id: int,
) -> list[ImportRollback]:
    """Preflight every affected import before compensating any of them."""
    plan: list[tuple[datetime, ImportRollback]] = []
    seen: set[str] = set()
    for harness, output in candidates:
        origin = _origin(harness)
        if not origin or str(harness.get("mod_id") or "") != origin["mod_id"]:
            raise EltConflict("ELT_RECALL_SCOPE", "入库回执缺少与当前业务空间匹配的对话归属。")
        total = 0
        for member in _member_receipts(output):
            data = member.get("data")
            if (
                not isinstance(data, dict)
                or data.get("status") != "completed"
                or data.get("reversible") is not True
                or data.get("customer_products")
                or not _valid_skip(data, "knowledge", _KNOWLEDGE_SKIPS)
                or not _valid_skip(data, "template", _TEMPLATE_SKIPS)
            ):
                raise EltConflict(
                    "ELT_RECALL_UNSUPPORTED",
                    "这次入库的知识库、模板库或关联写入无法一并撤回，请在原任务中核对。",
                )
            run_id, rows = data.get("run_id"), data.get("executed_rows")
            if (
                not isinstance(run_id, str)
                or not run_id
                or run_id in seen
                or type(rows) is not int
                or rows < 0
                or member.get("run_id", run_id) != run_id
            ):
                raise EltConflict("ELT_RECALL_INCOMPLETE", "入库回执编号或写入数量无法核实。")
            item = ImportRollback(run_id, origin, rows)
            run = _checked_run(db, item, owner_user_id=owner_user_id, tenant_id=tenant_id)
            seen.add(run_id)
            total += rows
            if rows and run.executed_at is not None:
                executed_at = run.executed_at
                plan.append((executed_at.replace(tzinfo=executed_at.tzinfo or UTC), item))
        if output.get("batch") is True:
            summary = output.get("data")
            if not isinstance(summary, dict) or summary.get("executed_rows") != total:
                raise EltConflict(
                    "ELT_RECALL_INCOMPLETE", "批量入库回执的合计写入量与各文件不一致。"
                )
    return [item for _, item in sorted(plan, key=lambda entry: entry[0], reverse=True)]


def rollback_imports(
    db: Session, plan: list[ImportRollback], *, owner_user_id: int, tenant_id: int
) -> int:
    from app.application.elt.service import get_elt_service

    service = get_elt_service()
    for item in plan:
        run = _checked_run(db, item, owner_user_id=owner_user_id, tenant_id=tenant_id)
        if run.rollback_status == "completed":
            continue
        result = service.rollback(db, run_id=item.run_id, owner_user_id=owner_user_id)
        if result.get("rollback_status") != "completed" or not _confirmed_rollback(
            result.get("receipt") or {}, item
        ):
            raise EltConflict("ELT_RECALL_INCOMPLETE", "入库撤回尚未收到完整回执，已保留原对话。")
    return len(plan)
