# mypy: disable-error-code="assignment"
"""digest / line-execute → 战略层行动项桥接。

把 ``daily_action_items`` 幂等镜像到 ``strategic_action_items``，并确保每条 digest
有一条可挂载的 ``strategic_decisions``（日常成功日用 ``track_digest_action_items``）。

设计：
- 看板 SSOT 仍是 ``daily_action_items``；本模块只做战略层审计镜像。
- ``action_id = act-dai-{daily_id}`` 稳定可重入。
- 失败只 log，不阻断 digest / line-execute。
- 受 ``MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED`` 开关控制（默认开启）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

TRACK_ACTION = "track_digest_action_items"
TRACK_SCOPE = "digest_action_items"

_STATUS_MAP = {
    "open": "pending",
    "dispatched": "in_progress",
    "in_progress": "in_progress",
    "merged": "completed",
    "closed": "cancelled",
}


def _env_enabled() -> bool:
    raw = (
        (os.environ.get("MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED", "1") or "").strip().lower()
    )
    return raw not in ("0", "false", "no", "off")


def _map_status(daily_status: str) -> str:
    return _STATUS_MAP.get(str(daily_status or "open").strip().lower(), "pending")


def _action_id_for_daily(daily_id: int) -> str:
    return f"act-dai-{int(daily_id)}"


def _find_track_decision_id(record_id: int) -> Optional[str]:
    """按 scope + scope_ref 查找已有追踪决策。"""
    from modstore_server.db.base import get_session_factory
    from modstore_server.db.strategic import StrategicDecision as StrategicDecisionModel

    session = get_session_factory()()
    try:
        row = session.execute(
            select(StrategicDecisionModel)
            .where(StrategicDecisionModel.scope == TRACK_SCOPE)
            .where(StrategicDecisionModel.scope_ref == str(int(record_id)))
            .order_by(StrategicDecisionModel.proposed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return str(row.decision_id) if row is not None else None
    except RECOVERABLE_ERRORS:
        logger.debug("find track decision failed record_id=%s", record_id, exc_info=True)
        return None
    finally:
        session.close()


def ensure_digest_track_decision(
    record_id: int,
    *,
    release_kind: str = "daily",
    release_train: str = "",
    decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """确保 digest 有可挂载的战略决策；优先复用传入 / 已有追踪决策。"""
    if not _env_enabled():
        return {
            "ok": True,
            "skipped": True,
            "reason": "strategic_layer integration disabled",
        }

    rid = int(record_id or 0)
    if rid <= 0:
        return {"ok": False, "error": "invalid record_id"}

    if decision_id:
        return {
            "ok": True,
            "decision_id": str(decision_id),
            "reused": True,
            "source": "caller",
        }

    existing = _find_track_decision_id(rid)
    if existing:
        return {
            "ok": True,
            "decision_id": existing,
            "reused": True,
            "source": "track_scope",
        }

    try:
        from modstore_server.strategic_layer import (
            DecisionProposer,
            DecisionType,
            StrategicDecisionLedger,
        )

        ledger = StrategicDecisionLedger()
        record = ledger.propose(
            title=f"digest#{rid} 行动条目战略层追踪",
            action=TRACK_ACTION,
            proposer=DecisionProposer(
                actor="digest-strategic-bridge",
                rationale=(
                    f"auto-track daily_action_items for digest record_id={rid} "
                    f"release_kind={release_kind} release_train={release_train}"
                ),
                payload={
                    "record_id": rid,
                    "release_kind": release_kind,
                    "release_train": release_train,
                    "bridge": "digest_strategic_bridge",
                },
            ),
            decision_type=DecisionType.OPERATIONAL,
            scope=TRACK_SCOPE,
            scope_ref=str(rid),
            execution_plan={
                "record_id": rid,
                "release_kind": release_kind,
                "release_train": release_train,
            },
        )
        return {
            "ok": True,
            "decision_id": record.decision_id,
            "reused": False,
            "source": "proposed",
            "status": record.status.value,
            "autonomy_action": record.autonomy_action,
        }
    except RECOVERABLE_ERRORS as exc:
        logger.exception("ensure_digest_track_decision failed record_id=%s", rid)
        return {"ok": False, "error": str(exc)}


def sync_daily_to_strategic(
    *,
    record_id: int,
    decision_id: Optional[str] = None,
    release_kind: str = "daily",
    release_train: str = "",
) -> Dict[str, Any]:
    """把指定 digest 的 daily_action_items 幂等镜像到 strategic_action_items。"""
    if not _env_enabled():
        return {
            "ok": True,
            "skipped": True,
            "reason": "strategic_layer integration disabled",
        }

    rid = int(record_id or 0)
    if rid <= 0:
        return {"ok": False, "error": "invalid record_id", "created": 0, "updated": 0}

    try:
        ensure_out = ensure_digest_track_decision(
            rid,
            release_kind=release_kind,
            release_train=release_train,
            decision_id=decision_id,
        )
        if not ensure_out.get("ok"):
            return {
                "ok": False,
                "error": ensure_out.get("error") or "ensure decision failed",
                "created": 0,
                "updated": 0,
            }
        if ensure_out.get("skipped"):
            return {**ensure_out, "created": 0, "updated": 0}

        anchor = str(ensure_out.get("decision_id") or "").strip()
        if not anchor:
            return {
                "ok": False,
                "error": "missing decision_id",
                "created": 0,
                "updated": 0,
            }

        from modstore_server.db.base import get_session_factory
        from modstore_server.db.strategic import StrategicActionItem
        from modstore_server.digest_action_items import _dedupe_key, list_action_items

        items = list_action_items(record_id=rid, limit=2000)
        if not items:
            return {
                "ok": True,
                "decision_id": anchor,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "note": "no daily action items",
            }

        created = 0
        updated = 0
        skipped = 0
        now = datetime.now(UTC)
        session = get_session_factory()()
        try:
            for it in items:
                daily_id = int(it.get("id") or 0)
                if daily_id <= 0:
                    skipped += 1
                    continue
                text = str(it.get("text") or "").strip()
                if not text:
                    skipped += 1
                    continue
                assigned = str(it.get("employee_id") or "unassigned").strip()[:64] or "unassigned"
                action_id = _action_id_for_daily(daily_id)
                status = _map_status(str(it.get("status") or "open"))
                day = str(it.get("day") or "")
                kind = str(it.get("kind") or "")
                result_payload = {
                    "daily_action_item_id": daily_id,
                    "dedupe_key": _dedupe_key(day, kind, assigned, text),
                    "kind": kind,
                    "line": str(it.get("line") or ""),
                    "priority": str(it.get("priority") or ""),
                    "rt_version": str(it.get("rt_version") or ""),
                    "day": day,
                    "record_id": rid,
                }
                existing = session.execute(
                    select(StrategicActionItem).where(StrategicActionItem.action_id == action_id)
                ).scalar_one_or_none()
                completed_at = now if status == "completed" else None
                if existing is None:
                    session.add(
                        StrategicActionItem(
                            action_id=action_id,
                            decision_id=anchor,
                            meeting_id=None,
                            description=text[:4000],
                            assigned_to=assigned,
                            status=status,
                            due_at=None,
                            completed_at=completed_at,
                            result_json=json.dumps(result_payload, ensure_ascii=False),
                            block_reason="",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    created += 1
                else:
                    existing.description = text[:4000]
                    existing.assigned_to = assigned
                    existing.status = status
                    existing.decision_id = anchor
                    existing.result_json = json.dumps(result_payload, ensure_ascii=False)
                    existing.updated_at = now
                    if status == "completed" and existing.completed_at is None:
                        existing.completed_at = now
                    if status != "completed":
                        existing.completed_at = None
                    updated += 1
            session.commit()
        except RECOVERABLE_ERRORS:
            session.rollback()
            raise
        finally:
            session.close()

        logger.info(
            "digest_strategic_bridge sync record_id=%s decision_id=%s created=%s updated=%s skipped=%s",
            rid,
            anchor,
            created,
            updated,
            skipped,
        )
        return {
            "ok": True,
            "decision_id": anchor,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "ensure": ensure_out,
        }
    except RECOVERABLE_ERRORS as exc:
        logger.exception("sync_daily_to_strategic failed record_id=%s", rid)
        return {"ok": False, "error": str(exc), "created": 0, "updated": 0}


def mirror_daily_status(daily_item_id: int, status: str) -> Dict[str, Any]:
    """单条 daily 状态推进时镜像到 strategic_action_items。"""
    if not _env_enabled():
        return {
            "ok": True,
            "skipped": True,
            "reason": "strategic_layer integration disabled",
        }

    iid = int(daily_item_id or 0)
    if iid <= 0:
        return {"ok": False, "error": "invalid daily_item_id"}

    action_id = _action_id_for_daily(iid)
    mapped = _map_status(status)
    try:
        from modstore_server.db.base import get_session_factory
        from modstore_server.db.strategic import StrategicActionItem

        now = datetime.now(UTC)
        session = get_session_factory()()
        try:
            row = session.execute(
                select(StrategicActionItem).where(StrategicActionItem.action_id == action_id)
            ).scalar_one_or_none()
            if row is None:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "strategic action item not found",
                }
            row.status = mapped
            row.updated_at = now
            if mapped == "completed":
                if row.completed_at is None:
                    row.completed_at = now
            else:
                row.completed_at = None
            session.commit()
            return {"ok": True, "action_id": action_id, "status": mapped}
        except RECOVERABLE_ERRORS:
            session.rollback()
            raise
        finally:
            session.close()
    except RECOVERABLE_ERRORS as exc:
        logger.exception("mirror_daily_status failed daily_id=%s", iid)
        return {"ok": False, "error": str(exc)}


def sync_record_after_status_writeback(
    *,
    record_id: Optional[int] = None,
    day: Optional[str] = None,
) -> Dict[str, Any]:
    """line-execute / deploy 回写后，按 record_id（或最新 day）再 sync 一次。"""
    if not _env_enabled():
        return {
            "ok": True,
            "skipped": True,
            "reason": "strategic_layer integration disabled",
        }
    try:
        from modstore_server.digest_action_items import latest_day, list_action_items

        rid = int(record_id or 0)
        if rid <= 0:
            use_day = day or latest_day() or None
            if not use_day:
                return {"ok": True, "skipped": True, "reason": "no day"}
            items = list_action_items(day=use_day, limit=1)
            if not items:
                return {"ok": True, "skipped": True, "reason": "no items"}
            rid = int(items[0].get("record_id") or 0)
        if rid <= 0:
            return {"ok": True, "skipped": True, "reason": "no record_id"}
        return sync_daily_to_strategic(record_id=rid)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("sync_record_after_status_writeback failed")
        return {"ok": False, "error": str(exc)}


__all__ = [
    "TRACK_ACTION",
    "TRACK_SCOPE",
    "ensure_digest_track_decision",
    "mirror_daily_status",
    "sync_daily_to_strategic",
    "sync_record_after_status_writeback",
]
