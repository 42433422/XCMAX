# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
import json
import re

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.para_delegate_handler")


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
            str(output.get("merge_commit_sha") or "")
            for output in (fix.get("handler_outputs") or {}).get("outputs") or []
            if output.get("merge_commit_sha")
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


def _normalize_tool_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if raw in _facade()._VALID_DEV_TOOLS:
        return raw
    return _facade()._TOOL_INPUT_ALIASES.get(raw, raw)


def _tool_fallback_allowed(req: _facade().Dict[str, _facade().Any]) -> bool:
    """Whether CLI runtime failure may retry another tool.

    ``allow_tool_fallback=0`` pins the requested tool.  Otherwise the env master
    switch wins — an explicit ``tool_name`` no longer silently disables recovery
    (that previously left ``spawn codex ENOENT`` storms with no fallback).
    """
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    raw_fallback = raw.get("allow_tool_fallback")
    if raw_fallback is None and "allow_tool_fallback" not in req:
        return _facade()._env_bool("MODSTORE_PARA_TOOL_FALLBACK_ENABLED", "1")
    value = raw_fallback if raw_fallback is not None else req.get("allow_tool_fallback")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _excluded_tools(req: _facade().Dict[str, _facade().Any]) -> set[str]:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    excluded: set[str] = set()
    for key in ("_para_exclude_tools", "para_exclude_tools"):
        blob = raw.get(key)
        if isinstance(blob, (list, tuple, set)):
            excluded.update(str(item or "").strip() for item in blob if str(item or "").strip())
    top = req.get("_para_exclude_tools")
    if isinstance(top, (list, tuple, set)):
        excluded.update(str(item or "").strip() for item in top if str(item or "").strip())
    return {item for item in excluded if item in _facade()._VALID_DEV_TOOLS}


def _tool_candidates(req: _facade().Dict[str, _facade().Any]) -> list[str]:
    """Return the preferred executor followed by allowed same-device fallbacks.

    With fallback enabled, an explicit tool stays first but other tools from
    ``MODSTORE_PARA_TOOL_FALLBACK_ORDER`` remain eligible.  Without an explicit
    tool, the fallback order itself is the preference list (no silent codex
    prepend).  Pin with ``allow_tool_fallback=0`` for strict single-tool mode.
    """
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    explicit = _facade()._normalize_tool_name(
        str(req.get("tool_name") or raw.get("tool_name") or raw.get("dev_tool") or "")
    )
    preferred = explicit if explicit in _facade()._VALID_DEV_TOOLS else _facade()._dev_tool()
    order = _facade()._fallback_order_tools()
    if not _facade()._tool_fallback_allowed(req):
        candidates = [preferred]
    elif explicit:
        candidates = [explicit] + [tool for tool in order if tool != explicit]
    else:
        candidates = list(order) if order else [preferred]
        if preferred not in candidates:
            candidates.insert(0, preferred)
    excluded = _facade()._excluded_tools(req)
    return [tool for tool in candidates if tool not in excluded]


def _is_cli_runtime_failure(
    *,
    error: str = "",
    status: str = "",
    snapshot: _facade().Any = None,
    api_error: str = "",
) -> bool:
    """True when the chosen CLI is missing/broken and another tool may succeed."""
    parts = [str(error or ""), str(status or ""), str(api_error or "")]
    if isinstance(snapshot, dict):
        parts.append(str(snapshot.get("task_status") or ""))
        for sub in snapshot.get("subtasks") or []:
            if isinstance(sub, dict):
                parts.append(str(sub.get("last_error") or ""))
                parts.append(str(sub.get("status") or ""))
        for item in snapshot.get("logs_tail") or []:
            if isinstance(item, dict):
                parts.append(str(item.get("content") or ""))
    text = " ".join(parts).lower()
    needles = (
        "enoent",
        "not_installed",
        "not installed",
        "command not found",
        "no such file",
        "spawn codex",
        "spawn cursor",
        "spawn claude",
        "spawn trae",
        "codex cli",
        "cursor cli",
        "claude cli",
        "trae cli",
        "cli 失败",
        "cli failed",
        "executable not found",
        "is not recognized",
    )
    return any(token in text for token in needles)


def _device_discovery_enabled() -> bool:
    return _facade()._env_bool("MODSTORE_PARA_DEVICE_DISCOVERY", "1")


def _safe_json(resp: _facade().httpx.Response) -> _facade().Any:
    try:
        return resp.json() if resp.content else {}
    except RECOVERABLE_ERRORS:
        return {"raw": resp.text[:4000]}


def _device_tool_entry(
    item: _facade().Dict[str, _facade().Any], tool_name: str
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    tools = item.get("tools")
    if not isinstance(tools, list):
        return None
    aliases = _facade()._TOOL_NAME_ALIASES.get(tool_name, (tool_name,))
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("toolName") or tool.get("name") or "").strip()
        if name in aliases:
            return tool
    return None


def _device_has_capability(caps: _facade().Dict[str, _facade().Any], tool_name: str) -> bool:
    for key in _facade()._TOOL_CAP_ALIASES.get(tool_name, (f"{tool_name}_cli",)):
        if caps.get(key) is True:
            return True
    return False


def _device_eligible(item: _facade().Any, tool_name: str) -> bool:
    """设备能否承接派工：在线 + 目标工具已装且非占用（executorReady）。"""
    if not isinstance(item, dict):
        return False
    if str(item.get("status") or "") != "online":
        return False
    if item.get("executorReady") is False:
        return False
    tool = _facade()._device_tool_entry(item, tool_name)
    if tool and str(tool.get("status") or "") == "not_installed":
        return False
    if tool and str(tool.get("status") or "") == "running" and tool.get("currentTask"):
        return False
    if not tool:
        caps = item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        if _facade()._device_has_capability(caps, tool_name):
            return True
        dev_tool = str(item.get("devTool") or "").strip()
        aliases = _facade()._TOOL_NAME_ALIASES.get(tool_name, (tool_name,))
        return dev_tool in aliases
    return True


def _selected_tool_for_device(item: _facade().Any, req: _facade().Dict[str, _facade().Any]) -> str:
    for tool_name in _facade()._tool_candidates(req):
        if _facade()._device_eligible(item, tool_name):
            return tool_name
    return ""


def _with_selected_tool(
    item: _facade().Dict[str, _facade().Any], tool_name: str
) -> _facade().Dict[str, _facade().Any]:
    return {**item, "_selected_tool": tool_name}


def _select_local_device_with_fallback(
    devices: list, req: _facade().Dict[str, _facade().Any]
) -> list:
    local_id = (_facade().os.environ.get("MODSTORE_PARA_DEVICE_ID") or "").strip()
    ordered: list = []
    if local_id:
        ordered.extend(
            item
            for item in devices
            if isinstance(item, dict) and str(item.get("id") or "") == local_id
        )
    else:
        primary = [item for item in devices if isinstance(item, dict) and item.get("isPrimary")]
        ordered.extend(primary or [item for item in devices if isinstance(item, dict)])
    for item in ordered:
        selected_tool = _facade()._selected_tool_for_device(item, req)
        if selected_tool:
            return [_facade()._with_selected_tool(item, selected_tool)]
    return []


def _select_fleet_devices_with_fallback(
    devices: list, req: _facade().Dict[str, _facade().Any]
) -> list:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    target = raw.get("target_devices")
    targets = (
        {str(x).strip() for x in target if str(x).strip()} if isinstance(target, list) else {"all"}
    )
    candidates: list = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        if (
            "all" not in targets
            and str(item.get("id") or "") not in targets
            and (str(item.get("name") or "") not in targets)
        ):
            continue
        selected_tool = _facade()._selected_tool_for_device(item, req)
        if selected_tool:
            candidates.append(_facade()._with_selected_tool(item, selected_tool))
    workers = [item for item in candidates if not item.get("isPrimary")]
    return (workers or candidates)[: _facade()._max_fleet_devices(req)]


def _filter_executor_ready(devices: list, tool_name: str) -> list:
    return [item for item in devices if _facade()._device_eligible(item, tool_name)]


def _resolve_tier(req: _facade().Dict[str, _facade().Any]) -> int:
    """一级(1) / 二级(2)。默认一级，按需升二级。读 req.raw_input + 任务文本。"""
    forced = (_facade().os.environ.get("MODSTORE_PARA_FORCE_TIER") or "").strip().lower()
    if forced in {"1", "local", "single", "本机"}:
        return 1
    if forced in {"2", "fleet", "multi", "多设备"}:
        return 2
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    hint = str(raw.get("para_tier") or raw.get("tier") or "").strip().lower()
    if hint in {"2", "fleet", "multi", "multi_device", "多设备"}:
        return 2
    if hint in {"1", "local", "single", "本机"}:
        return 1
    if raw.get("escalate") in (True, 1, "1", "true", "yes", "on"):
        return 2
    try:
        if int(raw.get("max_devices") or 0) > 1:
            return 2
    except (TypeError, ValueError):
        pass
    target = raw.get("target_devices")
    if isinstance(target, list):
        specific = [s for s in (str(x).strip() for x in target) if s and s != "all"]
        if len(specific) > 1:
            return 2
    text = f"{req.get('task') or ''} {req.get('prompt') or ''}"
    if any(m in text for m in ("多设备", "所有设备", "全部设备", "调用所有设备", "跨设备")):
        return 2
    return 1


def _max_fleet_devices(req: _facade().Dict[str, _facade().Any]) -> int:
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    try:
        return max(1, min(8, int(raw.get("max_devices") or 3)))
    except (TypeError, ValueError):
        return 3


def _select_local_device(devices: list, tool_name: str) -> list:
    """一级：只挑「本机」一台。配置 MODSTORE_PARA_DEVICE_ID → is_primary → 首台合格。
    识别到的本机若不合格(离线/工具未装/占用)则返空，由上层升二级。"""
    local_id = (
        _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID")
        or _facade().os.environ.get("DEVFLEET_DEVICE_ID")
        or ""
    ).strip()
    if local_id:
        for item in devices:
            if isinstance(item, dict) and str(item.get("id") or "") == local_id:
                return [item] if _facade()._device_eligible(item, tool_name) else []
        return []
    for item in devices:
        if isinstance(item, dict) and item.get("isPrimary"):
            return [item] if _facade()._device_eligible(item, tool_name) else []
    for item in devices:
        if _facade()._device_eligible(item, tool_name):
            return [item]
    return []


def _select_fleet_devices(
    devices: list, req: _facade().Dict[str, _facade().Any], tool_name: str
) -> list:
    """二级：选多台在线设备(偏好非主 worker)，受 target_devices / max_devices 约束。"""
    raw = req.get("raw_input") if isinstance(req.get("raw_input"), dict) else {}
    target = raw.get("target_devices")
    targets = (
        {str(x).strip() for x in target if str(x).strip()} if isinstance(target, list) else {"all"}
    )
    candidates: list = []
    for item in devices:
        if not _facade()._device_eligible(item, tool_name):
            continue
        if (
            "all" not in targets
            and str(item.get("id") or "") not in targets
            and (str(item.get("name") or "") not in targets)
        ):
            continue
        candidates.append(item)
    workers = [item for item in candidates if not item.get("isPrimary")]
    selected = workers or candidates
    return selected[: _facade()._max_fleet_devices(req)]


def _fetch_devices(client: _facade().httpx.Client, base: str, token: str) -> list:
    try:
        resp = client.get(f"{base}/api/devices", headers={"Authorization": f"Bearer {token}"})
    except RECOVERABLE_ERRORS:
        return []
    if resp.status_code >= 400:
        return []
    body = _facade()._safe_json(resp)
    devices = body.get("devices") if isinstance(body, dict) else []
    return devices if isinstance(devices, list) else []


def _resolve_dispatch_devices(
    client: _facade().httpx.Client,
    base: str,
    token: str,
    req: _facade().Dict[str, _facade().Any],
) -> tuple:
    """返回 (tier, [device dicts], reason)。显式 device_id → 零回归走一级单设备。"""
    explicit = str(req.get("device_id") or "").strip()
    if explicit:
        devices = _facade()._fetch_devices(client, base, token)
        target = next(
            (
                item
                for item in devices
                if isinstance(item, dict) and str(item.get("id") or "") == explicit
            ),
            None,
        )
        if target is not None:
            selected_tool = _facade()._selected_tool_for_device(target, req)
            if selected_tool:
                return (1, [_facade()._with_selected_tool(target, selected_tool)], "")
        return (
            1,
            [{"id": explicit, "_selected_tool": _facade()._tool_candidates(req)[0]}],
            "",
        )
    if not _facade()._device_discovery_enabled():
        return (
            1,
            [],
            "未配置 MODSTORE_PARA_DEVICE_ID 且设备发现关闭(MODSTORE_PARA_DEVICE_DISCOVERY=0)",
        )
    devices = _facade()._fetch_devices(client, base, token)
    tier = _facade()._resolve_tier(req)
    if tier == 1:
        local = _facade()._select_local_device_with_fallback(devices, req)
        if local:
            return (1, local, "")
        preferred = (_facade()._tool_candidates(req) or [_facade()._dev_tool()])[0]
        local = _facade()._select_local_device(devices, preferred)
        if local:
            return (1, [_facade()._with_selected_tool(local[0], preferred)], "")
        tier = 2
    selected = _facade()._select_fleet_devices_with_fallback(devices, req)
    if not selected:
        preferred = (_facade()._tool_candidates(req) or [_facade()._dev_tool()])[0]
        selected = [
            _facade()._with_selected_tool(item, preferred)
            for item in _facade()._select_fleet_devices(devices, req, preferred)
        ]
    if not selected:
        tools = ",".join(_facade()._tool_candidates(req)) or _facade()._dev_tool()
        return (tier, [], f"未发现在线可用 {tools} 执行器(共 {len(devices)} 台设备)")
    return (tier, selected, "")


def _multi_device_prompt(
    base_prompt: str, device: _facade().Dict[str, _facade().Any], index: int, total: int
) -> str:
    if total <= 1:
        return base_prompt
    label = device.get("name") or device.get("id") or f"设备{index + 1}"
    suffix = f"\n\n你是第 {index + 1}/{total} 台工作设备（{label}）。请承担可独立完成的部分，避免与其它设备改同一批文件；提交到调度器分配的分支并回写日志。"
    return _facade().insert_before_loop_context(base_prompt, suffix)


def _para_subtask_title(req: _facade().Dict[str, _facade().Any], index: int, total: int) -> str:
    title = str(req.get("title") or "MODstore loop task")
    if total <= 1:
        return f"{req.get('mode') or 'code'}: {title}"[:240]
    label = (
        _facade()._SUBTASK_LABELS[index]
        if index < len(_facade()._SUBTASK_LABELS)
        else f"工作单元{index + 1}"
    )
    return f"{label}：{title[:60]}"
