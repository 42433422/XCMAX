"""工单状态机核心（纯逻辑，无 I/O）：共享宿主侧的 Work Order SSOT 判定。

与 FHD ``app.services.work_order_ssot`` 保持同一状态集合 / 迁移表 / 轨道分类 /
wo_id 派生算法（同源镜像，一测防漂移：FHD tests/test_services/test_work_order_core_parity.py
断言两侧行为一致）。事件只在这里做折叠与校验，直接由 work_order_api 落库。

验收语义（服务端权威，无复盘补写）：
  - pending 只是观察，绝不推进任何阶段
  - accepted / rejected 仅在 ``verifying``（或 ``released`` 单步校正进 verifying）窗口内
    生效；candidate/routed/in_dev/merged 未达验收窗口 → not_in_acceptance_window
  - accepted 要求双平台健康回执证据（win+mac installed>0 且 failed=0）
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

WO_STATES: tuple[str, ...] = (
    "candidate",
    "routed",
    "in_dev",
    "merged",
    "released",
    "verifying",
    "closed",
    "reopened",
    "dropped",
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"routed", "dropped"}),
    "routed": frozenset({"in_dev", "dropped"}),
    "in_dev": frozenset({"merged", "dropped"}),
    "merged": frozenset({"released"}),
    "released": frozenset({"verifying", "closed"}),
    "verifying": frozenset({"closed", "reopened"}),
    "closed": frozenset({"reopened"}),
    "reopened": frozenset({"in_dev", "dropped"}),
    "dropped": frozenset(),
}

WO_TRACKS: tuple[str, ...] = (
    "ops_support",
    "product_line",
    "industry_mod",
    "customer_custom",
)

_OPS_REASONS: frozenset[str] = frozenset(
    {
        "llm_timeout",
        "llm_unavailable",
        "service_unavailable",
        "deploy_failed",
        "install_failed",
        "update_failed",
        "health_check_failed",
    }
)

_WO_ID_RE = re.compile(r"^WO-[0-9a-f]{12}$")


def derive_wo_id(source: str, dedup_key: str) -> str:
    """与 FHD 同算法：source|dedup_key 的 sha1 前 12 位。"""
    digest = hashlib.sha1(f"{source}|{dedup_key}".encode()).hexdigest()
    return f"WO-{digest[:12]}"


def is_valid_wo_id(value: str) -> bool:
    return bool(_WO_ID_RE.match(str(value or "")))


def classify_track(
    *,
    source: str = "",
    reason: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """四类去向（与 FHD classify_track 同规则，跨仓镜像）。"""
    ctx = context if isinstance(context, dict) else {}
    reason_tag = str(reason or "").strip()
    raw_skill = ctx.get("skill_proposal")
    skill_proposal: dict[str, Any] = raw_skill if isinstance(raw_skill, dict) else {}
    # 1) 强定制信号
    if ctx.get("customer_scoped") or skill_proposal.get("customer_scoped"):
        return "customer_custom"
    # 2) 运维与支持（带客户标识的普通故障仍是运维问题）
    if reason_tag in _OPS_REASONS:
        return "ops_support"
    # 3) 显式单客户作用域
    if ctx.get("customer_id") or ctx.get("account_id"):
        return "customer_custom"
    # 4) 行业共性
    raw_intent = ctx.get("intent_result")
    intent_result: dict[str, Any] = raw_intent if isinstance(raw_intent, dict) else {}
    if ctx.get("industry") or intent_result.get("industry") or skill_proposal.get("industry"):
        return "industry_mod"
    return "product_line"


def fold(events: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """事件行列 → 每工单最新物化视图（与 FHD _fold 同折叠语义）。"""
    orders: dict[str, dict[str, Any]] = {}
    for rec in events:
        wo_id = str(rec.wo_id)
        view = orders.setdefault(
            wo_id,
            {
                "wo_id": wo_id,
                "status": "",
                "track": "",
                "source": "",
                "dedup_key": "",
                "issue_number": 0,
                "issue_url": "",
                "release_version": "",
                "created_at": "",
                "updated_at": "",
                "history": [],
            },
        )
        event = str(rec.event)
        at = str(getattr(rec, "at", "") or "")
        view["history"].append(
            {
                "event": event,
                "from": str(getattr(rec, "from_state", "") or ""),
                "to": str(getattr(rec, "to_state", "") or ""),
                "ref": _json_object(getattr(rec, "ref", "{}")),
                "note": str(getattr(rec, "note", "") or ""),
                "source": str(getattr(rec, "source", "") or ""),
                "at": at,
            }
        )
        view["updated_at"] = at
        if event == "created":
            view["status"] = "candidate"
            view["source"] = str(getattr(rec, "source", "") or "")
            view["dedup_key"] = str(getattr(rec, "dedup_key", "") or "")
            view["created_at"] = at
        elif event == "transition":
            view["status"] = str(getattr(rec, "to_state", "") or view["status"])
        ref = _json_object(getattr(rec, "ref", "{}"))
        if ref.get("issue_number"):
            view["issue_number"] = int(ref["issue_number"])
        if ref.get("issue_url"):
            view["issue_url"] = str(ref["issue_url"])
        if ref.get("release_version"):
            view["release_version"] = str(ref["release_version"])
        if ref.get("track"):
            view["track"] = str(ref["track"])
    return orders


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def validate_transition(current: str | None, target: str) -> str:
    """返回空字符串表示合法；否则返回拒绝原因。"""
    current = str(current or "")
    if target not in WO_STATES:
        return "unknown_state"
    if target == current:
        return "already_in_state"
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return "invalid_transition"
    return ""


def acceptance_plan(
    *,
    current: str,
    issue_number: int,
    release_version: str,
    verdict: str,
    evidence: dict[str, Any] | None,
    seen_version: str = "",
) -> dict[str, Any]:
    """验收判定计划：返回 {ok, target?, reason, note?, ref?} 供 API 落库。"""
    if verdict == "pending":
        return {"ok": False, "reason": "verdict_pending", "target": "", "status": current}
    if verdict not in ("accepted", "rejected"):
        return {"ok": False, "reason": "unknown_verdict", "target": ""}
    version = str(release_version or "").strip()
    if not version:
        return {"ok": False, "reason": "missing_release_identity", "target": ""}
    # 乱序保护：已记录其它发布身份且处于验收终态 → 旧版本回执拒绝
    if seen_version and seen_version != version and current in ("closed", "reopened"):
        return {
            "ok": False,
            "reason": "stale_receipt",
            "target": "",
            "status": current,
            "receipt_release_version": version,
            "recorded_release_version": seen_version,
        }

    ref: dict[str, Any] = {"issue_number": int(issue_number), "release_version": version}
    if evidence:
        ref["evidence"] = evidence

    if current == "released":
        return {
            "ok": True,
            "target": "verifying",
            "reason": "window_correction",
            "note": "验收期起点校正（服务端）",
            "ref": ref,
        }
    if current in ("closed", "reopened"):
        return {"ok": True, "reason": "already_terminal", "target": "", "ref": ref}
    if current != "verifying":
        return {
            "ok": False,
            "reason": "not_in_acceptance_window",
            "target": "",
            "status": current,
        }

    if verdict == "accepted":
        platforms = (evidence or {}).get("per_platform")
        healthy: list[str] = []
        if isinstance(platforms, dict):
            for p in ("win", "mac"):
                stats = platforms.get(p)
                if isinstance(stats, dict) and int(stats.get("installed") or 0) > 0:
                    if int(stats.get("failed") or 0) == 0:
                        healthy.append(p)
        if len(healthy) < 2:
            return {"ok": False, "reason": "missing_acceptance_evidence", "healthy": healthy}
        return {
            "ok": True,
            "target": "closed",
            "reason": "双平台回执健康，客户验收通过",
            "ref": ref,
        }
    return {
        "ok": True,
        "target": "reopened",
        "reason": "客户机安装/运行失败，重开原工单",
        "ref": ref,
    }


__all__ = [
    "ALLOWED_TRANSITIONS",
    "WO_STATES",
    "WO_TRACKS",
    "acceptance_plan",
    "classify_track",
    "derive_wo_id",
    "fold",
    "is_valid_wo_id",
    "validate_transition",
]
