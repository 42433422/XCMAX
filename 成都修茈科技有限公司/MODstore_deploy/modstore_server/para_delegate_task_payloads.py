"""Prepare and validate a complete Para task group before its first submission."""

from __future__ import annotations

import importlib
import json
import re
from hashlib import sha256
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


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


def _build_request(*, task: str, input_data: dict[str, Any], employee_id: str) -> dict[str, Any]:
    input_data = {**input_data, **_facade()._customer_ticket_cloud_route(input_data)}
    from modstore_server.customer_ticket_triage import para_triage_hook

    input_data = para_triage_hook(input_data, employee_id=employee_id)
    budget = {}
    if input_data.get("_trusted_incident_team_execution") is True:
        from modstore_server.incident_model_router import route_for_incident

        role = str(input_data.get("role") or "")
        route = route_for_incident(
            event_type=str(input_data.get("event_type") or ""),
            payload=input_data.get("incident") or {},
            role=role,
        )
        budget = {"role": role, **route.get("budget", {})} if route.get("budget") else {}
    title = str(input_data.get("title") or task or "")[:240]
    if input_data.get("github_workspace") and input_data.get("_trusted_incident_team_execution"):
        request_key = str(input_data["github_workspace"]["request_id"])
        attempt = str(input_data.get("attempt_id") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", attempt):
            raise ValueError("GitHub employee attempt identity is invalid")
        title = f"[xcmax:{sha256(request_key.encode()).hexdigest()[:32]}:{attempt}] {employee_id}"
    workspace_root = (
        "" if input_data.get("github_workspace") else _facade()._project_root(input_data)
    )
    mode = _facade()._mode_for_employee(employee_id, input_data)
    report_only = _facade()._coerce_bool(
        input_data.get("report_only"), mode in {"review", "verify"}
    )
    branch = (
        str(
            input_data.get("branch")
            or input_data.get("base_branch")
            or _facade().os.environ.get("MODSTORE_PARA_BRANCH")
            or "main"
        ).strip()
        or "main"
    )
    return {
        "request_id": str(
            input_data.get("request_id")
            or input_data.get("attempt_id")
            or _facade().uuid.uuid4().hex
        ),
        "execution_identity": {
            key: input_data.get(key)
            for key in (
                "event_id",
                "tenant_id",
                "user_id",
                "attempt_id",
                "revision",
                "role",
            )
        },
        "created_at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "source": "modstore_employee_loop",
        "execution_budget": budget,
        "codex_model_candidates": budget.get("codex_model_candidates")
        or input_data.get("codex_model_candidates"),
        "employee_id": employee_id,
        "mode": mode,
        "report_only": report_only,
        "title": title,
        "max_attempts": 1 if input_data.get("github_workspace") else input_data.get("max_attempts"),
        "task": task,
        "prompt": str(input_data.get("prompt") or task or ""),
        "workspace_root": workspace_root,
        "repo_url": str(
            input_data.get("repo_url") or _facade().os.environ.get("MODSTORE_PARA_REPO_URL") or ""
        ),
        "branch": branch,
        "device_id": str(
            input_data.get("device_id") or _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID") or ""
        ),
        "tool_name": str(input_data.get("tool_name") or input_data.get("dev_tool") or ""),
        "depends_on": (
            input_data.get("depends_on") if isinstance(input_data.get("depends_on"), list) else []
        ),
        "para_task_id": str(input_data.get("para_task_id") or input_data.get("task_id") or ""),
        "dispatch_line": str(input_data.get("dispatch_line") or ""),
        "priority": str(input_data.get("priority") or ""),
        "action_item_id": input_data.get("action_item_id"),
        "record_id": input_data.get("record_id"),
        "wait_for_para": input_data.get("wait_for_para"),
        "wait_timeout_sec": input_data.get("wait_timeout_sec"),
        "evidence": (
            input_data.get("evidence") if isinstance(input_data.get("evidence"), dict) else {}
        ),
        "raw_input": input_data,
    }


def _independent_check_plan(req):
    """Validate read-only units against the saved server plan, never customer input."""
    raw = req.get("raw_input") or {}
    units = raw.get("independent_checks")
    if not units:
        return [], ""
    role = raw.get("role")
    if (
        not raw.get("_trusted_incident_team_execution")
        or not raw.get("_incident_continuation")
        or role not in {"scout", "verify"}
        or req.get("report_only") is not True
        or not isinstance(units, list)
        or not 1 <= len(units) <= 8
    ):
        raise ValueError("Independent checks require a durable read-only incident role")
    from modstore_server.models import IncidentEvent, get_session_factory
    from modstore_server.node_coordinator import assert_incident_claim

    event_id = int(raw.get("event_id") or 0)
    with get_session_factory()() as db:
        assert_incident_claim(event_id, session=db)
        event = db.get(IncidentEvent, event_id)
        if event is None:
            raise ValueError("Independent check incident does not exist")
        claim = json.loads(event.payload_json or "{}").get("_team_claim") or {}
        plan = claim.get("plan") or {}
        row = next((r for r in claim.get("team") or [] if r.get("role") == role), {})
        if (
            plan.get("execution_schema") != 2
            or (plan.get("independent_checks") or {}).get(role) != units
            or not row.get("attempt_id")
            or row.get("attempt_id") != raw.get("attempt_id")
        ):
            raise ValueError("Independent check plan or attempt does not match the incident")
        fix = next((r for r in claim.get("team") or [] if r.get("role") == "fix"), {})
        fixed = {
            str(output.get("commit_sha") or output.get("merge_commit_sha") or "")
            for output in (fix.get("handler_outputs") or {}).get("outputs") or []
            if output.get("commit_sha") or output.get("merge_commit_sha")
        }
    ids, revisions = set(), set()
    for unit in units:
        if (
            not isinstance(unit, dict)
            or unit.get("read_only") is not True
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(unit.get("unit_id") or ""))
            or unit["unit_id"] in ids
            or not str(unit.get("prompt") or "").strip()
            or len(str(unit.get("prompt") or "")) > 4000
            or unit.get("depends_on")
        ):
            raise ValueError(
                "Checks need distinct IDs, bounded prompts and independent read-only scope"
            )
        ids.add(unit["unit_id"])
        if unit.get("source_revision"):
            revisions.add(str(unit["source_revision"]))
    if not revisions and role == "verify":
        revisions = fixed
    if len(revisions) != 1 or not re.fullmatch(r"[0-9a-fA-F]{40}", next(iter(revisions), "")):
        raise ValueError("Independent checks require one immutable source revision")
    revision = next(iter(revisions))
    if role == "verify" and (not fix.get("ok") or fixed != {revision}):
        raise ValueError("Verification checks must target the completed fix revision")
    return units, revision


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
                grant,
                "dolt_incident_contract",
                "blocked_dolt_incident_contract",
                str(exc),
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
