"""Canonical progress snapshots for durable Agent tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.run_models import AgentRun

if TYPE_CHECKING:
    from app.infrastructure.auth.agent_principal import AgentPrincipal

_SETTLED_STEP_STATES = {"completed", "failed", "skipped"}
_STATUS_LABELS = {
    "queued": "排队中",
    "planning": "正在生成执行计划",
    "running": "执行中",
    "retrying": "正在重试",
    "waiting_user": "等待审批或用户确认",
    "paused": "已暂停，可继续",
    "blocked": "等待依赖解除",
    "completed": "任务完成",
    "failed": "执行失败",
    "cancelled": "已取消",
}
_ELT_STAGE_LABELS = {
    "pending": "未开始",
    "queued": "等待预演",
    "parsing": "正在解析文件",
    "previewing": "正在生成预演",
    "loading": "正在保存源数据",
    "transforming": "正在校验数据",
    "preview_ready": "预演完成，等待入库",
    "executing": "正在执行导入",
    "persisting": "正在写入业务数据",
    "completed": "文件已完成",
    "interrupted": "预演待继续",
    "partial": "部分数据已写入",
    "failed": "处理失败",
    "unknown": "写入结果待核对",
    "unverified": "没有可核对的回执",
}


def _elt_checkpoint_parts(row: Any, now: datetime, *, optional: bool = False) -> dict[str, Any]:
    from app.application.elt.service_support import load_json

    if row is None:
        return {"run_id": "", "status": "pending", "stage": "pending", "executed_rows": 0}
    status = row.status
    rows = int(row.executed_rows or 0)
    expiry = row.operation_lease_until
    expired = expiry is not None and expiry.replace(tzinfo=expiry.tzinfo or UTC) <= now
    if status in {"completed", "partial"}:
        receipt = load_json(row.receipt_json, {})
        if (
            not isinstance(receipt, dict)
            or receipt.get("run_id") != row.id
            or receipt.get("target_type") != row.target_type
            or receipt.get("executed_rows") != rows
            or not (row.confirmed_at and row.executed_at)
            or row.rollback_status
            or row.rolled_back_at
        ):
            status = "unknown"
    elif (
        status == "outcome_unknown"
        or row.confirmed_at
        and (expired or status not in {"executing", "persisting"})
    ):
        status = "unknown"
    elif expired and status == "previewing":
        status = "interrupted"
    elif optional and status == "preview_ready" and row.total_rows == 0:
        status = "completed"
    return {
        "run_id": row.id,
        "status": status,
        "stage": row.stage if status == row.status else status,
        "executed_rows": rows if status in {"completed", "partial"} else 0,
    }


def _read_elt_checkpoint_files(
    slots: dict[str, str], owner: int, tenant: int, *, origin: dict[str, str] | None = None
) -> tuple[list[dict], list]:
    from sqlalchemy.orm import load_only

    from app.application.elt.service_support import load_json
    from app.db import SessionLocal
    from app.db.models.elt import EltRun, EltUpload

    files, changed = [], []
    now = datetime.now(UTC)
    # Read native rows instead of get_run, which can renew/recover expired leases.
    with SessionLocal() as db:
        scoped = (
            db.query(EltRun)
            .options(
                load_only(
                    EltRun.id,
                    EltRun.upload_id,
                    EltRun.target_type,
                    EltRun.file_sha256,
                    EltRun.summary_json,
                    EltRun.status,
                    EltRun.stage,
                    EltRun.executed_rows,
                    EltRun.total_rows,
                    EltRun.receipt_json,
                    EltRun.operation_lease_until,
                    EltRun.confirmed_at,
                    EltRun.executed_at,
                    EltRun.rolled_back_at,
                    EltRun.rollback_status,
                    EltRun.updated_at,
                )
            )
            .filter(EltRun.owner_user_id == owner, EltRun.tenant_id == tenant)
        )
        uploads = db.query(EltUpload.id, EltUpload.file_name).filter(
            EltUpload.owner_user_id == owner, EltUpload.tenant_id == tenant
        )
        sources = []
        if origin is not None:
            names = dict(uploads.filter(EltUpload.file_name.in_(slots)).all())
            by_name: dict[str, list[Any]] = {}
            for row in scoped.filter(
                EltRun.upload_id.in_(names),
                EltRun.summary_json.contains(origin["run_id"], autoescape=True),
            ).all():
                details = load_json(row.summary_json, {})
                if isinstance(details, dict) and details.get("chat_import_origin") == origin:
                    by_name.setdefault(names[row.upload_id], []).append(row)
            for name in slots:
                matches = by_name.get(name, [])
                sources.append((name, matches[0] if len(matches) == 1 else None))
        else:
            names = dict(uploads.filter(EltUpload.id.in_(slots)).all())
            parents = {row.id: row for row in scoped.filter(EltRun.id.in_(slots.values())).all()}
            for index, (upload_id, run_id) in enumerate(slots.items(), start=1):
                row = parents.get(run_id)
                if row is not None and row.upload_id != upload_id:
                    row = None
                sources.append((names.get(upload_id) or f"附件 {index}", row))
        links = {}
        for _name, row in sources:
            if row is None:
                continue
            details = load_json(row.summary_json, {})
            link = (
                details.get("linked_customer_products_preview")
                if isinstance(details, dict)
                else None
            )
            if isinstance(link, dict) and isinstance(link.get("run_id"), str):
                links[row.id] = link["run_id"]
        children = (
            {row.id: row for row in scoped.filter(EltRun.id.in_(links.values())).all()}
            if links
            else {}
        )
        for name, row in sources:
            main = _elt_checkpoint_parts(row, now)
            entry = {"name": name, **main}
            if row is None and origin is not None:
                entry.update(status="unknown", stage="unverified")
            if row is not None:
                changed.append(row.updated_at)
            if row is not None and row.id in links:
                child = children.get(links[row.id])
                details = load_json(child.summary_json, {}) if child is not None else {}
                if (
                    child is not None
                    and child.target_type == "customer_products"
                    and child.upload_id == row.upload_id
                    and child.file_sha256 == row.file_sha256
                    and isinstance(details, dict)
                    and details.get("linked_from_shipment_preview") == row.id
                ):
                    linked = _elt_checkpoint_parts(child, now, optional=True)
                    entry["primary"] = main
                    entry["companion"] = linked
                    entry["executed_rows"] += linked["executed_rows"]
                    changed.append(child.updated_at)
                    if (
                        linked["status"] == "unknown"
                        or main["status"] == "completed"
                        or (
                            main["status"] == "preview_ready"
                            and linked["status"] not in {"preview_ready", "completed"}
                        )
                    ):
                        entry.update(status=linked["status"], stage=linked["stage"])
                else:
                    entry.update(status="unknown", stage="unknown")
            if entry["status"] == "failed" and entry["executed_rows"] > 0:
                entry.update(status="partial", stage="partial")
            files.append(entry)
    return files, changed


def _legacy_prefix_for_tail(
    run: AgentRun, viewer: AgentPrincipal, policy: dict, tail: list[dict]
) -> list[dict]:
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.task_context import task_context_of

    parent_id = policy.get("continued_from_run_id")
    if (
        policy.get("source") != "elt_batch_continuation"
        or policy.get("legacy_elt_tail_recheck") is not True
        or not isinstance(parent_id, str)
        or not parent_id
        or parent_id == run.run_id
        or run.plan_id != f"continue-{parent_id}"
    ):
        return []
    task = task_context_of(run)
    if task.get("parent_run_id") != parent_id:
        return []
    original = get_agent_run_repository().get(parent_id)
    if original is None or original.run_id != parent_id or original.status != "blocked":
        return []
    prior = task_context_of(original)
    if (
        any(
            not task.get(key) or task[key] != prior.get(key)
            for key in ("task_id", "root_run_id", "conversation_id")
        )
        or _attempt_number(task.get("attempt")) != _attempt_number(prior.get("attempt")) + 1
    ):
        return []
    original_progress = _elt_file_progress(original, viewer)
    original_files = original_progress.get("files") or []
    prefix = original_files[: -len(tail)]
    prior_tail = original_files[-len(tail) :]
    if (
        original_progress.get("stage") != "结果待核对"
        or not prefix
        or not all(file["status"] == "completed" for file in prefix)
        or not all(file["stage"] == "unverified" for file in prior_tail)
        or [file["name"] for file in prior_tail] != [file["name"] for file in tail]
    ):
        return []
    return prefix


def _elt_file_progress(run: AgentRun, viewer: AgentPrincipal) -> dict[str, Any]:
    from app.domain.shared_services.tools_workflow_elt import durable_elt_checkpoint_ids
    from app.http.request_context import reset_current_http_request, set_current_http_request
    from app.infrastructure.tenant_scope import owned_tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    plan = run.metadata.get("plan")
    policy = plan.get("metadata") if isinstance(plan, dict) else None
    if len(run.steps) != 1:
        return {}
    step = run.steps[0]
    upload_ids = step.params.get("file_paths")
    if (
        (step.tool_id, step.action) != ("elt_import", "execute")
        or not isinstance(upload_ids, list)
        or not 1 <= len(upload_ids) <= 50
    ):
        return {}
    durable = isinstance(policy, dict) and policy.get("durable_elt_batch") is True
    legacy = (
        not durable
        and run.status == "blocked"
        and step.output.get("outcome") == "unknown"
        and step.output.get("error_code") == "tool_worker_exited"
        and step.output.get("reconciliation_required") is True
    )
    if not (durable or legacy):
        return {}
    runtime = run.metadata.get("runtime_context")
    if not isinstance(runtime, dict):
        return {}
    binding = runtime.get("_mod_authorization")
    persisted_mod = str(binding.get("mod_id") or "") if isinstance(binding, dict) else ""
    viewer_mod = str((viewer.mod_authorization or {}).get("mod_id") or "")
    if (viewer.user_id, viewer.tenant_id, viewer_mod) != (
        run.user_id,
        str(runtime.get("tenant_id") or ""),
        persisted_mod,
    ):
        return {}
    origin = None
    if legacy:
        origin = {
            "run_id": run.run_id,
            "step_id": step.step_id,
            "turn_id": str(runtime.get("turn_id") or ""),
            "conversation_id": str(runtime.get("conversation_id") or ""),
            "mod_id": persisted_mod,
        }
        if not all(origin.values()) or not all(
            isinstance(name, str) and name and "/" not in name and "\\" not in name
            for name in upload_ids
        ):
            return {}
    mod = set_request_active_mod_id(persisted_mod)
    request = set_current_http_request(None)
    try:
        owner, tenant = int(viewer.user_id), int(viewer.tenant_id)
        if min(owner, tenant) <= 0:
            return {}
        slots = (
            dict.fromkeys(upload_ids, "")
            if legacy
            else durable_elt_checkpoint_ids(run.run_id, step.step_id, upload_ids)
        )
        with owned_tenant_scope(tenant):
            files, changed = _read_elt_checkpoint_files(slots, owner, tenant, origin=origin)
    except RECOVERABLE_ERRORS:
        return {}
    finally:
        reset_current_http_request(request)
        reset_request_active_mod_id(mod)

    prefix = []
    if durable and isinstance(policy, dict) and files:
        try:
            prefix = _legacy_prefix_for_tail(run, viewer, policy, files)
        except RECOVERABLE_ERRORS:
            pass  # The new attempt's exact receipts remain visible on their own.
        files = prefix + files

    completed = sum(file["status"] == "completed" for file in files)
    settled = sum(file["status"] in {"completed", "failed", "partial"} for file in files)
    active = next(
        (
            idx
            for idx, file in enumerate(files)
            if file["status"] in {"previewing", "executing", "persisting"}
        ),
        next(
            (idx for idx, file in enumerate(files) if file["status"] != "completed"), len(files) - 1
        ),
    )
    current = files[active]
    written = sum(file["executed_rows"] for file in files)
    latest = max(
        (at.replace(tzinfo=at.tzinfo or UTC).astimezone(UTC).isoformat() for at in changed if at),
        default="",
    )
    return {
        "basis": "files",
        "percent": min(
            100 if run.status == "completed" else 99,
            _clamp_percent(round(completed * 100 / len(files))),
        ),
        "completed_units": completed,
        "settled_units": settled,
        "total_units": len(files),
        "current_unit": active + 1,
        "indeterminate": False,
        "detail": (
            f"{completed}/{len(files)} 份已完成 · 已确认写入 {written} 行"
            if legacy
            else f"{current['name']} · {completed}/{len(files)} 份已完成 · 已确认写入 {written} 行"
            if prefix
            else f"{current['name']} · {completed}/{len(files)} 份已完成"
        ),
        "executed_rows": written,
        "files": files,
        "updated_at": max(latest, str(run.updated_at or "")),
        **(
            {
                "stage": _ELT_STAGE_LABELS.get(
                    current["stage"], _ELT_STAGE_LABELS.get(current["status"], "执行中")
                )
            }
            if run.status == "running"
            else {"stage": "结果待核对"}
            if legacy
            else {}
        ),
    }


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def _attempt_number(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def task_progress_snapshot(
    run: AgentRun, *, viewer: AgentPrincipal | None = None
) -> dict[str, Any]:
    """Build one honest, durable progress representation from an AgentRun.

    An authorized reader can project ELT file receipts. Other snapshots are
    derived from the run's persisted step states.
    """

    status = str(run.status or "queued")
    steps = list(run.steps or [])
    total = len(steps)
    completed = sum(step.status == "completed" for step in steps)
    settled = sum(step.status in _SETTLED_STEP_STATES for step in steps)
    current = next(
        (step for step in steps if step.status not in _SETTLED_STEP_STATES),
        steps[-1] if steps else None,
    )
    current_index = steps.index(current) + 1 if current is not None else 0

    if total:
        percent = _clamp_percent(round((settled / total) * 100))
        if status != "completed":
            percent = min(99, percent)
    else:
        percent = 100 if status == "completed" else 0

    control_request = run.metadata.get("control_request")
    control_action = (
        str(control_request.get("action") or "")
        if isinstance(control_request, dict)
        and str(control_request.get("status") or "") == "requested"
        else ""
    )
    if control_action == "pause":
        stage = "正在请求暂停"
    elif control_action == "cancel":
        stage = "正在请求取消"
    else:
        stage = _STATUS_LABELS.get(status, "状态待同步")

    step_label = ""
    if current is not None:
        step_label = str(current.description or f"{current.tool_id}.{current.action}").strip()

    task_context = run.metadata.get("task_context")
    attempt = _attempt_number(task_context.get("attempt")) if isinstance(task_context, dict) else 1
    snapshot = {
        "percent": percent,
        "completed_units": completed,
        "settled_units": settled,
        "total_units": total,
        "current_unit": current_index,
        "stage": stage,
        "detail": step_label,
        "status": status,
        "attempt": attempt,
        "indeterminate": total == 0 and status != "completed",
        "basis": "steps" if total else "status",
        "updated_at": run.updated_at,
    }
    if viewer is not None:
        snapshot.update(_elt_file_progress(run, viewer))
        if control_action in {"pause", "cancel"}:
            snapshot["stage"] = stage
    return snapshot


def progress_snapshot_of_task_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Read the persisted canonical progress snapshot without exposing aliases."""

    raw = (metadata or {}).get("progress")
    return dict(raw) if isinstance(raw, dict) else {}


def fallback_task_progress_snapshot(
    *, status: str, attempt: int, updated_at: str
) -> dict[str, Any]:
    """Return a complete status-only snapshot for legacy task rows."""

    normalized_status = str(status or "queued")
    return {
        "percent": 100 if normalized_status == "completed" else 0,
        "completed_units": 0,
        "settled_units": 0,
        "total_units": 0,
        "current_unit": 0,
        "stage": _STATUS_LABELS.get(normalized_status, "状态待同步"),
        "detail": "",
        "status": normalized_status,
        "attempt": _attempt_number(attempt),
        "indeterminate": normalized_status != "completed",
        "basis": "status",
        "updated_at": str(updated_at or ""),
    }


__all__ = [
    "fallback_task_progress_snapshot",
    "progress_snapshot_of_task_metadata",
    "task_progress_snapshot",
]
