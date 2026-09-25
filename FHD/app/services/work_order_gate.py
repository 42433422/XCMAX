"""工单附属事件：闸门收据（是否真的过了）与 issue 绑定（观测载体的补挂）。

主线状态机（``work_order_ssot``，candidate→…→closed）回答「工单走到哪一步」；
本模块只做**不改状态机**的追加式记录，与状态迁移共用同一条事件流和同一个
``wo_id``——不新增第二个工单、不新增第二份台账，两者按时间同序可核对。

``attach_issue`` 补的是 ``link_issue`` 覆盖不到的场景：``link_issue`` 只在
candidate→routed 那一次写绑定，工单若已 routed（闭环编排器建单时已定轨），
再调它会返回 already_in_state 而拿不到绑定。

``status`` 由调用方定义，闭环当前使用：
  FIX_VALIDATED_IN_DEV / OWNER_INSTANCE_VERIFIED / NEEDS_MORE_EVIDENCE
  / approved / rejected / held / MANUAL_DEPENDENCY

``evidence`` 只放路径、SHA256、判定、时间等事实，禁止放入凭据、token、
session cookie 或用户原文。落盘走 ``work_order_ssot`` 的同一把文件锁。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services import work_order_ssot as ssot

logger = logging.getLogger(__name__)

__all__ = ["attach_issue", "gate_receipts", "record_gate"]


def _append_checked(wo_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """持锁追加一条附属事件；工单不存在时拒绝写入。"""
    with ssot._exclusive_file_lock():
        if ssot._fold(ssot._load_events()).get(wo_id) is None:
            return {"ok": False, "reason": "unknown_work_order", "wo_id": wo_id}
        try:
            ssot._append_event(event)
        except OSError:
            logger.warning("work_order %s append failed", event.get("event"), exc_info=True)
            return {"ok": False, "reason": "write_failed", "wo_id": wo_id}
    return {"ok": True, "wo_id": wo_id}


def attach_issue(wo_id: str, *, issue_number: int, issue_url: str = "") -> dict[str, Any]:
    """把 issue 绑定到已存在的工单（不改状态机）；``_fold`` 会折叠出 issue 字段。"""
    number = int(issue_number or 0)
    if not ssot._WO_ID_RE.match(str(wo_id or "")) or number <= 0:
        return {"ok": False, "reason": "bad_arguments", "wo_id": wo_id}
    result = _append_checked(
        wo_id,
        {
            "wo_id": wo_id,
            "event": "issue_linked",
            "ref": {"issue_number": number, "issue_url": str(issue_url or "")},
            "at": ssot._utc_now(),
            "ts_unix": time.time(),
        },
    )
    if result.get("ok"):
        logger.info("work_order %s linked to issue #%d", wo_id, number)
        return {**result, "issue_number": number}
    return result


def record_gate(
    wo_id: str,
    gate: str,
    status: str,
    *,
    evidence: dict[str, Any] | None = None,
    note: str = "",
    source: str = "self_heal_loop",
) -> dict[str, Any]:
    """追加一条闸门收据（不推进状态机）；工单不存在时拒绝写入。"""
    if not ssot._WO_ID_RE.match(str(wo_id or "")):
        return {"ok": False, "reason": "bad_wo_id", "wo_id": wo_id}
    name = str(gate or "").strip()
    if not name:
        return {"ok": False, "reason": "empty_gate", "wo_id": wo_id}
    result = _append_checked(
        wo_id,
        {
            "wo_id": wo_id,
            "event": "gate",
            "gate": name,
            "gate_status": str(status or ""),
            "evidence": dict(evidence or {}),
            "note": str(note or "")[:500],
            "source": str(source or "self_heal_loop"),
            "at": ssot._utc_now(),
            "ts_unix": time.time(),
        },
    )
    if result.get("ok"):
        logger.info("work_order gate %s: %s=%s", wo_id, name, status)
        return {**result, "gate": name, "status": str(status or "")}
    return result


def gate_receipts(wo_id: str) -> dict[str, dict[str, Any]]:
    """按闸门名取最近一次收据（后写覆盖先写），供 fail-closed 判定。"""
    view = ssot._fold(ssot._load_events()).get(wo_id)
    if view is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for rec in view.get("history") or []:
        if rec.get("event") == "gate" and rec.get("gate"):
            out[str(rec["gate"])] = rec
    return out
