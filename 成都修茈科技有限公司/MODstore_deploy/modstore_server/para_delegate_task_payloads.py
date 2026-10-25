"""Prepare and validate a complete Para task group before its first submission."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modstore_server.dot_ticket_dispatch import DoltIncidentContractError

PreparedPayload = tuple[dict[str, Any], dict[str, Any] | None, str, dict[str, object]]
PayloadTransform = Callable[[dict[str, Any], dict[str, object], str], dict[str, object]]


@dataclass
class PreparedTaskGroup:
    """Retain preparation progress so failures can report the original intended scope."""

    planned_devices: list[str] = field(default_factory=list)
    payloads: list[PreparedPayload] = field(default_factory=list)
    first_payload: dict[str, object] = field(default_factory=dict)
    blocked: dict[str, Any] | None = None


def validated_check_units(
    req: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    from modstore_server.para_delegate_handler import _independent_check_plan

    try:
        units, revision = _independent_check_plan(req) if not req.get("para_task_id") else ([], "")
        return units, revision, None
    except (ValueError, TypeError) as exc:
        return [], "", _blocked(None, "", "blocked_independent_checks", str(exc))


def task_payload_options(req: dict[str, Any], units: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve request options at the existing pre-I/O boundary."""
    h = importlib.import_module("modstore_server.para_delegate_handler")
    max_attempts = h._resolve_max_attempts(req)
    mode = str(req.get("mode") or "").strip().lower()
    auto_merge = bool(req.get("auto_merge")) and not units
    if (
        not auto_merge
        and mode in {"verify", "review", "report"}
        and not bool(req.get("report_only"))
    ):
        auto_merge = h._coerce_bool(req.get("auto_merge_on_complete"), False)
    workspace_path = str(
        req.get("workspace_path") or h.os.environ.get("MODSTORE_PARA_WORKSPACE_PATH") or ""
    ).strip()
    return {
        "max_attempts": max_attempts,
        "auto_merge": auto_merge,
        "workspace_path": workspace_path,
    }


def _blocked(grant: Any, reason: str, status: str, error: str, **extra: Any) -> dict[str, Any]:
    if grant is not None:
        from modstore_server.cred_vault import revoke_task_grants

        revoke_task_grants(grant.task_id, reason=reason)
    return {
        "handler": "para_delegate",
        "ok": False,
        "accepted": False,
        "queued": False,
        "retryable": False,
        "status": status,
        "error": error,
        **extra,
    }


def prepare_task_group(
    req: dict[str, Any],
    devices: list[dict[str, Any]],
    *,
    base_prompt: str,
    units: list[dict[str, Any]],
    check_revision: str,
    options: dict[str, Any],
    grant: Any,
    group: PreparedTaskGroup,
    transform: PayloadTransform,
) -> None:
    """Build every child and fail the whole group before any caller can POST."""
    h = importlib.import_module("modstore_server.para_delegate_handler")
    raw = req.get("raw_input") or {}
    if raw.get("_incident_continuation") and not units:
        devices = devices[:1]  # A repair has one writer.
    if units and any(
        h._normalize_tool_name(str(device.get("_selected_tool") or "")) == "dolt"
        for device in devices
    ):
        # The dot ticket wrapper replaces prompts and cannot preserve unit scope.
        group.blocked = _blocked(
            grant,
            "para_check_scope_unsupported",
            "blocked_independent_checks",
            "dolt ticket routing cannot preserve independent read-only check scope",
        )
        return
    assignments = (
        [(devices[index % len(devices)], unit) for index, unit in enumerate(units)]
        if units
        else [(device, None) for device in devices]
    )
    group.planned_devices = [str(device.get("id") or "") for device, _ in assignments]
    total = len(assignments)
    branch = check_revision or str(req.get("branch") or "main").strip() or "main"
    repo_url = str(req.get("repo_url") or "").strip()
    task_id = str(req.get("para_task_id") or "").strip()
    for index, (device, unit) in enumerate(assignments):
        device_id = str(device.get("id") or "").strip()
        if not device_id:
            continue
        payload: dict[str, object] = {
            "device_id": device_id,
            "title": str(req.get("title") or "MODstore loop task").strip(),
            "prompt": h._multi_device_prompt(base_prompt, device, index, total),
            "branch": branch,
            "subtask_title": h._para_subtask_title(req, index, total),
            "report_only": bool(req.get("report_only")),
            "max_attempts": options["max_attempts"],
        }
        if unit:
            payload.update(
                subtask_title=f"check:{unit['unit_id']} {unit.get('title') or ''}"[:240],
                prompt=h.insert_before_loop_context(
                    base_prompt,
                    "独立只读检查 "
                    + unit["unit_id"]
                    + "，源码版本 "
                    + check_revision
                    + "。只执行本项检查并返回证据；禁止修复、提交、合并或操作客户数据。\n"
                    + str(unit["prompt"]),
                ),
                report_only=True,
                max_attempts=1,
            )
        selected_tool = str(device.get("_selected_tool") or "").strip()
        if selected_tool:
            payload["tool_name"] = selected_tool
        if repo_url:
            payload["repo_url"] = repo_url
        if options["auto_merge"]:
            payload["auto_merge"] = True
        if options["workspace_path"]:
            payload["workspace_path"] = options["workspace_path"]
        if isinstance(req.get("depends_on"), list) and req.get("depends_on"):
            payload["depends_on"] = req.get("depends_on")
        if task_id:
            payload["task_id"] = task_id
        try:
            payload = transform(req, payload, h._normalize_tool_name(selected_tool))
        except DoltIncidentContractError as exc:
            group.blocked = _blocked(
                grant, "dolt_incident_contract", "blocked_dolt_incident_contract", str(exc)
            )
            return
        if not group.first_payload:
            group.first_payload = payload
        group.payloads.append((device, unit, selected_tool, payload))
    budget = req.get("execution_budget") or {}
    limit = int(budget.get("context_chars") or 0)
    largest = max((len(str(item[3]["prompt"])) for item in group.payloads), default=0)
    if limit and largest > limit:
        group.blocked = _blocked(
            grant,
            "para_context_budget",
            "blocked_context_budget",
            f"Final execution context has {largest} characters; budget allows {limit}",
            requested_execution_budget=budget,
        )
