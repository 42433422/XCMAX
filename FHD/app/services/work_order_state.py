"""Work Order SSOT 状态机纯逻辑（无 I/O）：常量、轨道分类、wo_id 派生、事件折叠。

从 ``work_order_ssot`` 拆出（app/ 单文件 ≤500 行门禁），保持模块级符号在
``work_order_ssot`` 命名空间可访问（显式 import 重导出），既有调用面不变。
与 modstore_server.work_order_core 保持同规则——一致性由
tests/test_services/test_work_order_core_parity.py 锁死。
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

# 主线状态机：candidate → routed → in_dev → merged → released → verifying → closed
# reopened 从 verifying/closed 回到 in_dev（失败重开原单，不另起新单）
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

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
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

_WO_ID_RE = re.compile(r"^WO-[0-9a-f]{12}$")

# 统一 Router 的四类去向（工单分流轨道）：
#   ops_support    运维与支持问题（超时/不可用/部署安装失败等运行期信号）
#   product_line   通用产品线能力（默认去向：只有通用能力进入主产品 main）
#   industry_mod   行业共性沉淀（进入版本化 Mod，不进主产品主线）
#   customer_custom 单客户定制（严禁自动进入主线；派发实现前须显式加
#                   custom-track-approved 标签，见 capability_proposal_promote）
WO_TRACKS: tuple[str, ...] = (
    "ops_support",
    "product_line",
    "industry_mod",
    "customer_custom",
)

# reason → 运维支持轨道（运行期故障信号不是产品需求）
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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def classify_track(
    *,
    source: str = "",
    reason: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """把工单分入四类去向之一（确定性规则，无 LLM，可机器核对）。

    优先级：强定制信号 > 运维与支持 > 显式客户作用域 > 行业 Mod > 通用产品线（默认）。

    关键区分：仅携带 ``customer_id`` 的普通故障（llm_timeout/install_failed 等
    运行期信号）仍归 ``ops_support``，不得因客户标识而自动归入 ``customer_custom``；
    只有显式 ``customer_scoped``（或技能提案 customer_scoped）与其后再判断的
    customer_id/account_id 才构成单客户定制。

    默认落 product_line 与「只有通用能力进入主产品」一致——
    无法证明属于其他轨道的需求，按通用能力走主产品治理门禁。
    """
    ctx = context if isinstance(context, dict) else {}
    reason_tag = str(reason or "").strip()
    raw_skill = ctx.get("skill_proposal")
    skill_proposal: dict[str, Any] = raw_skill if isinstance(raw_skill, dict) else {}
    # 1) 强定制信号：显式 customer_scoped（含技能提案场景）→ 单客户定制
    if ctx.get("customer_scoped") or skill_proposal.get("customer_scoped"):
        return "customer_custom"
    # 2) 运维与支持：运行期故障信号，优先级高于「仅携带 customer_id」。
    #    带客户标识的普通故障仍是运维问题，不得因此自动归入客户定制。
    if reason_tag in _OPS_REASONS:
        return "ops_support"
    # 3) 显式单客户作用域（无运维故障时才成立）
    if ctx.get("customer_id") or ctx.get("account_id"):
        return "customer_custom"
    # 4) 行业共性：上下文带行业标识（intent_result.industry / skill_proposal.industry）
    raw_intent = ctx.get("intent_result")
    intent_result: dict[str, Any] = raw_intent if isinstance(raw_intent, dict) else {}
    if ctx.get("industry") or intent_result.get("industry") or skill_proposal.get("industry"):
        return "industry_mod"
    return "product_line"


def derive_wo_id(source: str, dedup_key: str) -> str:
    """由信号来源 + 去重键派生唯一工单 ID（幂等：同输入必同 ID）。"""
    digest = hashlib.sha1(f"{source}|{dedup_key}".encode()).hexdigest()
    return f"WO-{digest[:12]}"


def _created_reason(view: dict[str, Any]) -> str:
    """从物化视图 history 里取建单 reason（自动分类轨道的输入之一）。"""
    for rec in view.get("history") or []:
        if rec.get("event") == "created":
            return str(rec.get("reason") or "")
    return ""


def _created_context(view: dict[str, Any]) -> dict[str, Any]:
    """从物化视图 history 里取建单 context。"""
    for rec in view.get("history") or []:
        if rec.get("event") == "created":
            ctx = rec.get("context")
            return ctx if isinstance(ctx, dict) else {}
    return {}


def _fold(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """事件流 → 每工单最新物化视图。"""
    orders: dict[str, dict[str, Any]] = {}
    for rec in events:
        wo_id = str(rec["wo_id"])
        view = orders.setdefault(
            wo_id,
            {
                "wo_id": wo_id,
                "status": "",
                "source": "",
                "dedup_key": "",
                "issue_number": 0,
                "issue_url": "",
                "release_version": "",
                "track": "",
                "created_at": "",
                "updated_at": "",
                "history": [],
            },
        )
        view["history"].append(rec)
        view["updated_at"] = str(rec.get("at") or "")
        if rec.get("event") == "created":
            view["status"] = "candidate"
            view["source"] = str(rec.get("source") or "")
            view["dedup_key"] = str(rec.get("dedup_key") or "")
            view["created_at"] = str(rec.get("at") or "")
        elif rec.get("event") == "transition":
            view["status"] = str(rec.get("to") or view["status"])
        raw_ref = rec.get("ref")
        ref: dict[str, Any] = raw_ref if isinstance(raw_ref, dict) else {}
        if ref.get("issue_number"):
            view["issue_number"] = int(ref["issue_number"])
        if ref.get("issue_url"):
            view["issue_url"] = str(ref["issue_url"])
        if ref.get("release_version"):
            view["release_version"] = str(ref["release_version"])
        if ref.get("track"):
            view["track"] = str(ref["track"])
    return orders


__all__ = [
    "_ALLOWED_TRANSITIONS",
    "_OPS_REASONS",
    "_WO_ID_RE",
    "WO_STATES",
    "WO_TRACKS",
    "classify_track",
    "derive_wo_id",
    "_utc_now",
    "_fold",
    "_created_reason",
    "_created_context",
]
