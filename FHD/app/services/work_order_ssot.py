"""工单 SSOT：候选需求 → 唯一工单 ID → GitHub issue 的主线脊椎。

三类 SSOT 边界（不可混用）：
  - Customer SSOT（customers 表）：回答「这个客户是谁」
  - Work Order SSOT（本模块）：回答「发生了什么事情」
  - Delivery Center：回答「交付了什么」，不是需求入口；
    新增需求必须回到 Signal Gate（对话/反馈/微信 → 意图过滤 → 提案）重走主线

设计：
  - 所有信号先落 Conversation/Signal 层；只有经过去重聚合的有效需求
    （capability_proposal）才在本模块升级为唯一工单 ``wo_id``
  - 存储为 JSONL 追加式事件流（与 capability_proposal_recorder 同风格，
    文件锁保证多进程安全），物化视图由事件流折叠而成，崩溃不丢已写入数据
  - GitHub issue 是工单的对外观测载体：本模块维护 candidate → routed → in_dev
    候选期状态与 ``wo_id ↔ issue_number`` 映射；merge 后的验收期历史
    （回执判定、重开、验收通过）由 release-acceptance-closeout 回写到
    issue 时间线，并经 ``record_acceptance_verdict`` 落回本地事件流
  - 每次状态迁移发布 NeuroBus 事件（best-effort，失败不影响主线写入）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_STORE_DIR = Path(
    os.environ.get("WORK_ORDER_SSOT_DIR")
    or os.environ.get("CAPABILITY_PROPOSAL_DIR")
    or "test_reports"
)
_EVENTS_FILE = _STORE_DIR / "work_orders.jsonl"

_file_lock = threading.Lock()

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 使用线程锁兜底
    fcntl = None  # type: ignore[assignment]

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


def classify_track(
    *,
    source: str = "",
    reason: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """把工单分入四类去向之一（确定性规则，无 LLM，可机器核对）。

    优先级：单客户定制 > 运维支持 > 行业 Mod > 通用产品线（默认）。
    默认落 product_line 与「只有通用能力进入主产品」一致——
    无法证明属于其他轨道的需求，按通用能力走主产品治理门禁。
    """
    ctx = context if isinstance(context, dict) else {}
    # 1) 单客户定制信号：显式客户/账号作用域标记
    if (
        ctx.get("customer_id")
        or ctx.get("account_id")
        or ctx.get("customer_scoped")
        or (
            isinstance(ctx.get("skill_proposal"), dict)
            and ctx["skill_proposal"].get("customer_scoped")
        )
    ):
        return "customer_custom"
    # 2) 运维与支持：reason 是运行期故障信号
    if str(reason or "").strip() in _OPS_REASONS:
        return "ops_support"
    # 3) 行业共性：上下文带行业标识（intent_result.industry / skill_proposal.industry）
    raw_intent = ctx.get("intent_result")
    intent_result: dict[str, Any] = raw_intent if isinstance(raw_intent, dict) else {}
    raw_skill = ctx.get("skill_proposal")
    skill_proposal: dict[str, Any] = raw_skill if isinstance(raw_skill, dict) else {}
    if ctx.get("industry") or intent_result.get("industry") or skill_proposal.get("industry"):
        return "industry_mod"
    return "product_line"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def _exclusive_file_lock():
    """同进程线程锁 + POSIX 跨进程文件锁。"""
    with _file_lock:
        if fcntl is None:
            yield
            return
        _STORE_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = _STORE_DIR / ".work_orders.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def derive_wo_id(source: str, dedup_key: str) -> str:
    """由信号来源 + 去重键派生唯一工单 ID（幂等：同输入必同 ID）。"""
    digest = hashlib.sha1(f"{source}|{dedup_key}".encode()).hexdigest()
    return f"WO-{digest[:12]}"


def _append_event(event: dict[str, Any]) -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    with _EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _load_events() -> list[dict[str, Any]]:
    if not _EVENTS_FILE.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with _EVENTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and _WO_ID_RE.match(str(rec.get("wo_id") or "")):
                    out.append(rec)
    except OSError:
        logger.warning("read work_orders events failed", exc_info=True)
    return out


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


def _publish_bus_event(wo_id: str, to_state: str, ref: dict[str, Any]) -> None:
    """状态迁移 → NeuroBus（best-effort，主线写入不受总线故障影响）。"""
    try:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.events.base import NeuroEvent

        get_neuro_bus().publish(
            NeuroEvent(
                event_type="work_order.transition",
                payload={"wo_id": wo_id, "to_state": to_state, "ref": ref},
                source="work_order_ssot",
            )
        )
    except RECOVERABLE_ERRORS:
        logger.debug("work_order bus publish skipped", exc_info=True)


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


def get_work_order(wo_id: str) -> dict[str, Any] | None:
    """按工单 ID 读取物化视图（含完整时间线）。"""
    if not _WO_ID_RE.match(wo_id):
        return None
    return _fold(_load_events()).get(wo_id)


def list_work_orders(status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """列出工单视图（按更新时间倒序）；``status`` 过滤当前状态。"""
    views = list(_fold(_load_events()).values())
    if status:
        views = [v for v in views if v["status"] == status]
    views.sort(key=lambda v: str(v.get("updated_at") or ""), reverse=True)
    return views[: max(1, int(limit))]


def find_by_issue(issue_number: int) -> dict[str, Any] | None:
    """按 GitHub issue 号反查工单（验收回写用）。"""
    number = int(issue_number)
    for view in _fold(_load_events()).values():
        if int(view.get("issue_number") or 0) == number:
            return view
    return None


def upsert_candidate(
    *,
    source: str,
    dedup_key: str,
    reason: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """候选需求升级为唯一工单（幂等：同 source+dedup_key 不重复建单）。

    返回 {"wo_id", "created", "status"}。
    """
    src = str(source or "").strip() or "unknown"
    key = str(dedup_key or "").strip()
    if not key:
        return {"wo_id": "", "created": False, "status": "", "reason": "empty_dedup_key"}
    wo_id = derive_wo_id(src, key)
    with _exclusive_file_lock():
        existing = _fold(_load_events()).get(wo_id)
        if existing:
            return {"wo_id": wo_id, "created": False, "status": existing["status"]}
        event = {
            "wo_id": wo_id,
            "event": "created",
            "source": src,
            "dedup_key": key,
            "reason": str(reason or ""),
            "context": context or {},
            "at": _utc_now(),
            "ts_unix": time.time(),
        }
        try:
            _append_event(event)
        except OSError:
            logger.warning("work_order create failed", exc_info=True)
            return {"wo_id": wo_id, "created": False, "status": "", "reason": "write_failed"}
    _publish_bus_event(wo_id, "candidate", {})
    logger.info("work_order created: %s source=%s reason=%s", wo_id, src, reason)
    return {"wo_id": wo_id, "created": True, "status": "candidate"}


def record_transition(
    wo_id: str,
    to_state: str,
    *,
    ref: dict[str, Any] | None = None,
    note: str = "",
    source: str = "mainline",
) -> dict[str, Any]:
    """推进工单状态机。非法迁移拒绝并返回 ok=False（不抛异常，调用方不崩）。"""
    target = str(to_state or "").strip()
    if target not in WO_STATES:
        return {"ok": False, "reason": "unknown_state", "wo_id": wo_id}
    with _exclusive_file_lock():
        view = _fold(_load_events()).get(wo_id)
        if view is None:
            return {"ok": False, "reason": "unknown_work_order", "wo_id": wo_id}
        current = str(view.get("status") or "")
        if target == current:
            return {"ok": True, "reason": "already_in_state", "wo_id": wo_id, "status": current}
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            logger.warning("work_order invalid transition %s: %s -> %s", wo_id, current, target)
            return {
                "ok": False,
                "reason": "invalid_transition",
                "wo_id": wo_id,
                "status": current,
            }
        final_ref = dict(ref or {})
        # 统一 Router：进入 routed 必须携带合法轨道；调用方未给时按建单上下文自动分类
        if target == "routed":
            track = str(final_ref.get("track") or "").strip()
            if track and track not in WO_TRACKS:
                return {"ok": False, "reason": "unknown_track", "wo_id": wo_id, "track": track}
            if not track:
                track = classify_track(
                    source=str(view.get("source") or ""),
                    reason=_created_reason(view),
                    context=_created_context(view),
                )
            final_ref["track"] = track
        event = {
            "wo_id": wo_id,
            "event": "transition",
            "from": current,
            "to": target,
            "ref": final_ref,
            "note": str(note or "")[:500],
            "source": str(source or "mainline"),
            "at": _utc_now(),
            "ts_unix": time.time(),
        }
        try:
            _append_event(event)
        except OSError:
            logger.warning("work_order transition write failed", exc_info=True)
            return {"ok": False, "reason": "write_failed", "wo_id": wo_id}
    _publish_bus_event(wo_id, target, final_ref)
    logger.info("work_order %s: %s -> %s (source=%s)", wo_id, current, target, source)
    return {"ok": True, "wo_id": wo_id, "from": current, "to": target}


def link_issue(
    wo_id: str,
    *,
    issue_number: int,
    issue_url: str,
    track: str = "",
    source: str = "capability_proposal_to_issue",
) -> dict[str, Any]:
    """工单绑定 GitHub issue：candidate → routed。

    ``track`` 为统一 Router 的四类去向之一（WO_TRACKS）；缺省时由
    record_transition 按建单上下文自动分类补入。
    """
    ref: dict[str, Any] = {"issue_number": int(issue_number), "issue_url": str(issue_url or "")}
    if str(track or "").strip():
        ref["track"] = str(track).strip()
    return record_transition(
        wo_id,
        "routed",
        ref=ref,
        note="升级为 GitHub issue",
        source=source,
    )


def record_acceptance_verdict(
    *,
    issue_number: int,
    release_version: str,
    verdict: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """市场端回执验收判定落回主线：verifying → closed / reopened。

    由 release-acceptance-closeout 在回写 GitHub issue 后调用；
    issue 未绑定工单时返回 ok=False（不阻塞 issue 回写本身）。
    """
    view = find_by_issue(issue_number)
    if view is None:
        return {"ok": False, "reason": "issue_not_linked", "issue_number": int(issue_number)}
    wo_id = str(view["wo_id"])
    ref = {"issue_number": int(issue_number), "release_version": str(release_version or "")}
    if evidence:
        ref["evidence"] = evidence
    current = str(view.get("status") or "")
    # 验收期起点校正：历史事件可能缺席，沿主线逐步补齐到 verifying
    for step in ("in_dev", "merged", "released", "verifying"):
        if current == step:
            continue
        current = str(find_by_issue(issue_number).get("status") or "")  # type: ignore[union-attr]
        if current == step:
            continue
        if step not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            break
        record_transition(wo_id, step, ref=ref, note="验收期起点补齐", source="acceptance")
    if verdict == "accepted":
        return record_transition(
            wo_id, "closed", ref=ref, note="双平台回执健康，客户验收通过", source="acceptance"
        )
    if verdict == "rejected":
        return record_transition(
            wo_id, "reopened", ref=ref, note="客户机安装/运行失败，重开原工单", source="acceptance"
        )
    return {"ok": False, "reason": "verdict_pending", "wo_id": wo_id}


__all__ = [
    "WO_STATES",
    "WO_TRACKS",
    "classify_track",
    "derive_wo_id",
    "find_by_issue",
    "get_work_order",
    "link_issue",
    "list_work_orders",
    "record_acceptance_verdict",
    "record_transition",
    "upsert_candidate",
]
