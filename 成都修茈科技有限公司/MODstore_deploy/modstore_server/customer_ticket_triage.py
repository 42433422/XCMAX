"""客服工单分诊（五项架构·终极员工介入）。

Para 收单后、分类/派发前后：
1. 产出可查看的分诊快照（intent / lane / 是否允许代码修复）；
2. 若 payload 或 evidence 带 ``triage_intervention``，立即应用（改分类、改 tool/device）；
3. **不阻塞等人**：无介入则自动分诊继续；有介入则用其决定；
4. 账号类 / 不确定意图默认进终极员工通道（grok_bot / dolt），**不静默丢弃**，
   且不得误派到代码修复工具（codex / cursor / claude_code / trae）。

运维快修执行器（ops_fast_fix）仍预留，本模块不实现。
"""

from __future__ import annotations

from typing import Any

from modstore_server.operational_errors import RECOVERABLE_ERRORS

# 与 customer_service_orchestrator.TRIAGE_LANES 对齐；此处再声明以免循环导入。
ULTIMATE_TOOLS = frozenset({"grok_bot", "dolt"})
CODE_FIX_TOOLS = frozenset({"codex", "claude_code", "cursor", "trae"})
_ACCOUNT_OR_UNCERTAIN = frozenset({"account_support", "general", "greeting"})


def resolve_dispatch_lane(intent: str) -> str:
    """intent → 派发车道。账号/不确定 → ultimate_review。"""
    intent = str(intent or "").strip().lower()
    if intent == "product_issue":
        return "product_defect"
    if intent in _ACCOUNT_OR_UNCERTAIN:
        return "ultimate_review"
    if intent in {"refund", "catalog_complaint", "catalog_review", "llm_extension"}:
        return "commerce"
    return "general"


def allow_code_fix(intent: str, *, intervention: dict[str, Any] | None = None) -> bool:
    """是否允许派代码修复工具。介入可显式开关；默认仅 product_issue 允许。"""
    if isinstance(intervention, dict) and "allow_code_fix" in intervention:
        return bool(intervention.get("allow_code_fix"))
    return str(intent or "").strip().lower() == "product_issue"


def build_triage_snapshot(
    payload: dict[str, Any] | None,
    *,
    intervention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """供终极员工查看的当前分诊结果（只读快照）。"""
    body = dict(payload or {})
    intent = (
        str(
            (intervention or {}).get("intent")
            or body.get("intent")
            or body.get("ticket_intent")
            or ""
        )
        .strip()
        .lower()
    )
    lane = resolve_dispatch_lane(intent)
    code_ok = allow_code_fix(intent, intervention=intervention)
    return {
        "intent": intent or "general",
        "triage_lane": lane,
        "allow_code_fix": code_ok,
        "needs_ultimate_review": lane == "ultimate_review"
        or not code_ok
        and intent != "product_issue",
        "ultimate_tools": sorted(ULTIMATE_TOOLS),
        "code_fix_tools_blocked": sorted(CODE_FIX_TOOLS) if not code_ok else [],
        "intervention_applied": bool(intervention),
        "note": str((intervention or {}).get("note") or "")[:300],
    }


def _read_intervention(payload: dict[str, Any]) -> dict[str, Any] | None:
    for holder in (payload, payload.get("evidence"), payload.get("resolution")):
        raw = holder.get("triage_intervention") if isinstance(holder, dict) else None
        if isinstance(raw, dict) and raw:
            return dict(raw)
    return None


def apply_triage_intervention(
    payload: dict[str, Any] | None,
    intervention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """应用终极员工介入（若有），否则自动分诊继续。永不丢弃工单字段。"""
    body = dict(payload or {})
    decided = (
        intervention
        if isinstance(intervention, dict) and intervention
        else _read_intervention(body)
    )
    if decided:
        if decided.get("intent"):
            body["intent"] = str(decided["intent"]).strip().lower()[:64]
        if decided.get("tool_name"):
            body["tool_name"] = str(decided["tool_name"]).strip().lower()[:64]
            body["dev_tool"] = body["tool_name"]
        if decided.get("device_id"):
            body["device_id"] = str(decided["device_id"]).strip()[:128]
        if "allow_code_fix" in decided:
            body["allow_code_fix"] = bool(decided.get("allow_code_fix"))
        body["triage_intervention"] = {
            k: decided[k]
            for k in ("intent", "tool_name", "device_id", "allow_code_fix", "note", "by")
            if k in decided
        }
    snap = build_triage_snapshot(body, intervention=decided)
    if "allow_code_fix" not in body:
        body["allow_code_fix"] = snap["allow_code_fix"]
    body["triage"] = snap
    body["triage_lane"] = snap["triage_lane"]
    return body


def guard_code_fix_tool(
    tool_name: str,
    *,
    allow: bool,
    fallback_ultimate: str = "grok_bot",
) -> tuple[str, str]:
    """账号/未授权代码修复时，把 codex 等改写到终极员工工具；不静默清空派发。"""
    tool = str(tool_name or "").strip().lower()
    if allow:
        return tool, ""
    if tool in CODE_FIX_TOOLS or not tool:
        fb = fallback_ultimate if fallback_ultimate in ULTIMATE_TOOLS else "grok_bot"
        return fb, f"triage_blocked_code_fix:{tool or 'empty'}->{fb}"
    return tool, ""


def apply_para_triage(
    input_data: dict[str, Any] | None,
    *,
    employee_id: str = "",
) -> dict[str, Any]:
    """Para ``_build_request`` 前钩子：贴快照、应用介入、挡住误进代码修复。"""
    _ = employee_id
    src = dict(input_data or {})
    nested = src.get("incident")
    incident: dict[str, Any] = nested if isinstance(nested, dict) else {}
    for key in ("intent", "triage_intervention", "allow_code_fix"):
        if key not in src and key in incident:
            src[key] = incident[key]
    if not str(src.get("intent") or "").strip() and not _read_intervention(src):
        return src  # 意图未知：不改派、不降级，保持原派发
    body = apply_triage_intervention(src)
    allow = bool(body.get("allow_code_fix"))
    raw_tool = str(body.get("tool_name") or body.get("dev_tool") or "")
    # 有序路由首跳若是终极员工，优先作 fallback
    route = body.get("_ticket_route")
    hops: list[Any] = route if isinstance(route, list) else []
    fallback = "grok_bot"
    for hop in hops:
        if isinstance(hop, dict) and str(hop.get("tool_name") or "") in ULTIMATE_TOOLS:
            fallback = str(hop["tool_name"])
            break
    new_tool, reason = guard_code_fix_tool(raw_tool, allow=allow, fallback_ultimate=fallback)
    if reason:
        body["tool_name"] = new_tool
        body["dev_tool"] = new_tool
        body.setdefault("triage", {})
        if isinstance(body["triage"], dict):
            body["triage"] = {**body["triage"], "guard": reason}
        # 非代码修复任务：报告优先，避免误改仓库
        if not allow:
            body.setdefault("para_mode", "review")
            body.setdefault("report_only", True)
    return body


def stamp_intake_triage(payload: dict[str, Any] | None) -> dict[str, Any]:
    """incident publish 边界：写入分诊快照，供终极员工查看与后续介入。"""
    try:
        return apply_triage_intervention(payload)
    except RECOVERABLE_ERRORS:
        body = dict(payload or {})
        body.setdefault("triage", build_triage_snapshot(body))
        return body
