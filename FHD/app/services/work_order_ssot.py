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

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

try:
    import urllib.error
    import urllib.request
except ImportError:  # pragma: no cover - 环境兜底
    urllib = None  # type: ignore[assignment]


class _RemoteUnavailable(Exception):
    """共享宿主（市场端 work-order API）不可达或返回异常。"""


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

# 状态机常量/折叠/分类等纯逻辑在 work_order_state（app/ 单文件 ≤500 行门禁）；
# 此处显式重导出，保持既有调用面（wo.WO_STATES / classify_track / _fold ...）不变。
from app.services.work_order_state import (  # noqa: E402  pylint: disable=wrong-import-position
    _ALLOWED_TRANSITIONS,
    _OPS_REASONS,  # noqa: F401  (重导出：外部/一致性测试经本模块访问)
    _WO_ID_RE,
    WO_STATES,
    WO_TRACKS,
    _created_context,
    _created_reason,
    _fold,
    _utc_now,
    classify_track,
    derive_wo_id,
)


# ---- 共享持久层（远端优先） ----
# 配置 WORK_ORDER_MARKET_BASE（+ WORK_ORDER_MARKET_TOKEN，缺省 MARKET_ADMIN_TOKEN）
# 后，本模块对工单的读写与判定委托市场端 /api/work-orders（共享 DB），
# 本地 JSONL 仅作不可达时的降级视图；不配置则保持纯本地行为（测试/单仓开发）。
def _remote_enabled() -> bool:
    base = str(
        os.environ.get("WORK_ORDER_MARKET_BASE") or os.environ.get("WORK_ORDER_MARKET_URL") or ""
    ).strip()
    token = str(
        os.environ.get("WORK_ORDER_MARKET_TOKEN") or os.environ.get("MARKET_ADMIN_TOKEN") or ""
    ).strip()
    return bool(base and token) and urllib is not None


def _remote_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if urllib is None:  # pragma: no cover - 环境兜底
        raise _RemoteUnavailable()
    base = str(
        os.environ.get("WORK_ORDER_MARKET_BASE") or os.environ.get("WORK_ORDER_MARKET_URL") or ""
    ).rstrip("/")
    token = str(
        os.environ.get("WORK_ORDER_MARKET_TOKEN") or os.environ.get("MARKET_ADMIN_TOKEN") or ""
    )
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
        logger.warning("work_order remote %s %s unavailable: %s", method, path, exc)
        raise _RemoteUnavailable() from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        logger.warning("work_order remote %s %s bad payload", method, path)
        raise _RemoteUnavailable() from exc
    return parsed if isinstance(parsed, dict) else {}


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


def get_work_order(wo_id: str) -> dict[str, Any] | None:
    """按工单 ID 读取物化视图（含完整时间线）。"""
    if not _WO_ID_RE.match(wo_id):
        return None
    if _remote_enabled():
        try:
            remote = _remote_request("GET", f"/api/work-orders/{wo_id}")
            if remote:
                return remote
        except _RemoteUnavailable:
            logger.debug("remote work_order lookup skipped", exc_info=True)
    return _fold(_load_events()).get(wo_id)


def list_work_orders(status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """列出工单视图（按更新时间倒序）；``status`` 过滤当前状态。

    远端共享库为主时，本列表为本地降级视图（不做远端全量枚举）。
    """
    views = list(_fold(_load_events()).values())
    if status:
        views = [v for v in views if v["status"] == status]
    views.sort(key=lambda v: str(v.get("updated_at") or ""), reverse=True)
    return views[: max(1, int(limit))]


def find_by_issue(issue_number: int) -> dict[str, Any] | None:
    """按 GitHub issue 号反查工单（验收回写用）。"""
    number = int(issue_number)
    if _remote_enabled():
        try:
            remote = _remote_request("GET", f"/api/work-orders/by-issue/{number}")
            if remote:
                return remote
        except _RemoteUnavailable:
            logger.debug("remote by-issue lookup skipped", exc_info=True)
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
    if _remote_enabled():
        try:
            res = _remote_request(
                "POST",
                "/api/work-orders/candidate",
                {
                    "source": src,
                    "dedup_key": key,
                    "reason": str(reason or ""),
                    "context": context or {},
                },
            )
            if res.get("wo_id"):
                return {
                    "wo_id": str(res["wo_id"]),
                    "created": bool(res.get("created")),
                    "status": str(res.get("status") or "candidate"),
                    "remote": True,
                }
        except _RemoteUnavailable:
            logger.debug("remote candidate upsert skipped", exc_info=True)
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
    if _remote_enabled():
        try:
            res = _remote_request(
                "POST",
                "/api/work-orders/transition",
                {
                    "wo_id": wo_id,
                    "to_state": target,
                    "ref": ref or {},
                    "note": str(note or "")[:500],
                    "source": str(source or "mainline"),
                },
            )
            if res.get("wo_id") and "ok" in res:
                return {
                    "ok": bool(res.get("ok")),
                    "wo_id": str(res["wo_id"]),
                    "from": str(res.get("from") or ""),
                    "to": str(res.get("to") or ""),
                    "status": str(res.get("status") or ""),
                    "reason": str(res.get("reason") or ""),
                    "remote": True,
                }
        except _RemoteUnavailable:
            logger.debug("remote transition skipped", exc_info=True)
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

    共享模式（WORK_ORDER_MARKET_BASE）：验收判定委托市场端（服务端权威，
    verifying/released 窗口内才生效，不做复盘补写）；本地模式保留本地实现。
    """
    if _remote_enabled():
        try:
            res = _remote_request(
                "POST",
                "/api/work-orders/acceptance",
                {
                    "issue_number": int(issue_number),
                    "release_version": str(release_version or ""),
                    "verdict": str(verdict or ""),
                    "evidence": evidence or {},
                },
            )
            if "wo_id" in res:
                return {
                    "ok": bool(res.get("ok")),
                    "wo_id": str(res["wo_id"]),
                    "to": str(res.get("to") or ""),
                    "from": str(res.get("from") or ""),
                    "reason": str(res.get("reason") or ""),
                    "status": str(res.get("status") or ""),
                    "remote": True,
                }
        except _RemoteUnavailable:
            logger.debug("remote acceptance skipped", exc_info=True)
    view = find_by_issue(issue_number)
    if view is None:
        return {"ok": False, "reason": "issue_not_linked", "issue_number": int(issue_number)}
    wo_id = str(view["wo_id"])
    # pending：回执未齐，绝不可自动补写开发/合并/发布完成状态——
    # 只有真实可验收的 accepted/rejected 才推进状态机。
    if verdict not in ("accepted", "rejected"):
        return {
            "ok": False,
            "reason": "verdict_pending",
            "wo_id": wo_id,
            "status": str(view.get("status") or ""),
        }
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
    return record_transition(
        wo_id, "reopened", ref=ref, note="客户机安装/运行失败，重开原工单", source="acceptance"
    )


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
