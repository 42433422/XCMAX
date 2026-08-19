"""员工自治会议服务 — 议程、决议、action items 闭环。

会议类型：
- ``daily_standup``：每日晨会（08:00 摘要后），同步状态 + 当日 action items
- ``weekly_review``：周度复盘（每周一），回顾上周决策与执行 + 本周规划
- ``monthly_strategy``：月度战略（每月 1 日），战略层方向决策
- ``ad_hoc``：临时会议（incident 触发或 require_council 决策触发）
- ``incident_review``：事故复盘（incident 关闭后 24h 内）

会议生命周期：
    scheduled → in_progress → concluded | cancelled

会议结束后：
- 决议写入 ``StrategicDecisionLedger``（``DecidedBy.COUNCIL_VOTE``）
- action items 写入 ``StrategicActionItem`` 表
- 关联决策状态从 ``proposed`` → ``approved`` / ``rejected``
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from modstore_server.db.base import get_session_factory
from modstore_server.db.strategic import CouncilMeeting as CouncilMeetingModel
from modstore_server.db.strategic import (
    StrategicActionItem,
)
from modstore_server.strategic_layer.decision_ledger import (
    DecidedBy,
    StrategicDecisionLedger,
)
from modstore_server.strategic_layer.council_meeting_models import (
    MeetingDecisionRef,
    MeetingParticipants,
    MeetingStatus,
    MeetingType,
    meeting_row_to_dict as _meeting_row_to_dict,
    parse_json as _loads,
)

logger = logging.getLogger(__name__)


class CouncilMeetingService:
    """员工自治会议服务。

    调度 → 开始 → 结论 → 决议写入决策账本 + action items 闭环。
    """

    def __init__(
        self,
        *,
        decision_ledger: Optional[StrategicDecisionLedger] = None,
        session_factory: Any = None,
    ) -> None:
        self._ledger = decision_ledger or StrategicDecisionLedger()
        self._session_factory = session_factory or get_session_factory

    # ---------------- 调度 ----------------

    def schedule(
        self,
        *,
        title: str,
        agenda: str,
        meeting_type: MeetingType,
        participants: MeetingParticipants,
        scheduled_at: datetime,
        source_digest_record_id: Optional[int] = None,
        source_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """调度新会议。

        Returns:
            meeting_id: 创建后的会议 ID
        """
        if not title or not title.strip():
            raise ValueError("title must not be empty")
        if not agenda or not agenda.strip():
            raise ValueError("agenda must not be empty")
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        meeting_id = f"mtg-{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        session = self._session_factory()()
        try:
            meeting = CouncilMeetingModel(
                meeting_id=meeting_id,
                title=title.strip(),
                agenda=agenda.strip(),
                meeting_type=meeting_type.value,
                scheduled_at=scheduled_at,
                started_at=None,
                concluded_at=None,
                status=MeetingStatus.SCHEDULED.value,
                participants_json=participants.to_json(),
                minutes_md="",
                decisions_json="[]",
                action_items_json="[]",
                source_digest_record_id=source_digest_record_id,
                source_context_json=json.dumps(source_context or {}, ensure_ascii=False),
                created_at=now,
                updated_at=now,
            )
            session.add(meeting)
            session.commit()
            logger.info(
                "meeting scheduled meeting_id=%s type=%s title=%s",
                meeting_id,
                meeting_type.value,
                title,
            )
            return meeting_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- 开始 ----------------

    def start(self, meeting_id: str) -> Dict[str, Any]:
        """开始会议（``scheduled`` → ``in_progress``）。"""
        session = self._session_factory()()
        try:
            row = self._get_meeting(session, meeting_id)
            if row is None:
                raise ValueError(f"meeting not found: {meeting_id}")
            if row.status != MeetingStatus.SCHEDULED.value:
                raise ValueError(f"cannot start meeting in status {row.status}; must be scheduled")
            row.status = MeetingStatus.IN_PROGRESS.value
            row.started_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return _meeting_row_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- 结论 ----------------

    def conclude(
        self,
        meeting_id: str,
        *,
        minutes_md: str,
        decisions: List[MeetingDecisionRef],
        action_items: List[Dict[str, Any]],
        actor: str = "ai-strategist",
    ) -> Dict[str, Any]:
        """结束会议并落地决议与 action items。

        Args:
            meeting_id: 会议 ID
            minutes_md: 会议纪要 Markdown
            decisions: 决议列表（每条引用 StrategicDecision）
            action_items: action items 列表，每项含 ``description``、``assigned_to``、``decision_id``、``due_at``、可选 ``meeting_id``
            actor: 操作者

        Returns:
            会议字典（含 decisions 与 action_items 落地结果）
        """
        if not minutes_md or not minutes_md.strip():
            raise ValueError("minutes_md required for conclusion")

        session = self._session_factory()()
        try:
            row = self._get_meeting(session, meeting_id)
            if row is None:
                raise ValueError(f"meeting not found: {meeting_id}")
            if row.status != MeetingStatus.IN_PROGRESS.value:
                raise ValueError(
                    f"cannot conclude meeting in status {row.status}; must be in_progress"
                )

            now = datetime.now(timezone.utc)
            # 1. 将决议写入决策账本
            decisions_payload: List[Dict[str, Any]] = []
            for ref in decisions:
                try:
                    if ref.vote_outcome == "approved":
                        self._ledger.approve(
                            ref.decision_id,
                            decided_by=DecidedBy.COUNCIL_VOTE,
                            review_notes=f"approved in meeting {meeting_id}",
                        )
                    elif ref.vote_outcome == "rejected":
                        self._ledger.reject(
                            ref.decision_id,
                            decided_by=DecidedBy.COUNCIL_VOTE,
                            review_notes=f"rejected in meeting {meeting_id}",
                        )
                    decisions_payload.append(
                        {
                            "decision_id": ref.decision_id,
                            "vote_outcome": ref.vote_outcome,
                            "vote_summary": ref.vote_summary,
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        "meeting %s failed to apply decision %s: %s",
                        meeting_id,
                        ref.decision_id,
                        exc,
                    )
                    decisions_payload.append(
                        {
                            "decision_id": ref.decision_id,
                            "vote_outcome": ref.vote_outcome,
                            "error": str(exc),
                        }
                    )

            # 2. 落地 action items
            action_items_payload: List[Dict[str, Any]] = []
            for item in action_items:
                description = str(item.get("description") or "").strip()
                assigned_to = str(item.get("assigned_to") or "").strip()
                decision_id = str(item.get("decision_id") or "").strip()
                if not description or not assigned_to or not decision_id:
                    logger.warning(
                        "meeting %s skipping action item missing fields: %s",
                        meeting_id,
                        item,
                    )
                    continue
                action_id = f"act-{uuid.uuid4().hex[:16]}"
                due_at = item.get("due_at")
                if isinstance(due_at, str):
                    due_at = datetime.fromisoformat(due_at)
                ai = StrategicActionItem(
                    action_id=action_id,
                    decision_id=decision_id,
                    meeting_id=meeting_id,
                    description=description,
                    assigned_to=assigned_to,
                    status="pending",
                    due_at=due_at,
                    completed_at=None,
                    result_json="{}",
                    block_reason="",
                    created_at=now,
                    updated_at=now,
                )
                session.add(ai)
                action_items_payload.append(
                    {
                        "action_id": action_id,
                        "decision_id": decision_id,
                        "meeting_id": meeting_id,
                        "description": description,
                        "assigned_to": assigned_to,
                        "due_at": due_at.isoformat() if due_at else None,
                    }
                )

            # 3. 关闭会议
            row.status = MeetingStatus.CONCLUDED.value
            row.concluded_at = now
            row.updated_at = now
            row.minutes_md = minutes_md
            row.decisions_json = json.dumps(decisions_payload, ensure_ascii=False)
            row.action_items_json = json.dumps(action_items_payload, ensure_ascii=False)
            session.commit()

            logger.info(
                "meeting concluded meeting_id=%s decisions=%d action_items=%d",
                meeting_id,
                len(decisions_payload),
                len(action_items_payload),
            )
            return _meeting_row_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def cancel(self, meeting_id: str, *, reason: str) -> Dict[str, Any]:
        """取消会议（仅 ``scheduled`` 或 ``in_progress`` 状态可调用）。"""
        if not reason.strip():
            raise ValueError("reason required for cancellation")
        session = self._session_factory()()
        try:
            row = self._get_meeting(session, meeting_id)
            if row is None:
                raise ValueError(f"meeting not found: {meeting_id}")
            if row.status in (MeetingStatus.CONCLUDED.value, MeetingStatus.CANCELLED.value):
                raise ValueError(f"cannot cancel meeting in terminal status {row.status}")
            row.status = MeetingStatus.CANCELLED.value
            row.updated_at = datetime.now(timezone.utc)
            row.minutes_md = f"[CANCELLED] {reason.strip()}\n\n{row.minutes_md or ''}"
            session.commit()
            return _meeting_row_to_dict(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- 查询 ----------------

    def get(self, meeting_id: str) -> Optional[Dict[str, Any]]:
        session = self._session_factory()()
        try:
            row = self._get_meeting(session, meeting_id)
            return _meeting_row_to_dict(row) if row else None
        finally:
            session.close()

    def list_recent(
        self,
        *,
        status: Optional[MeetingStatus] = None,
        meeting_type: Optional[MeetingType] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        session = self._session_factory()()
        try:
            stmt = (
                select(CouncilMeetingModel)
                .order_by(desc(CouncilMeetingModel.scheduled_at))
                .limit(max(1, min(limit, 200)))
            )
            if status is not None:
                stmt = stmt.where(CouncilMeetingModel.status == status.value)
            if meeting_type is not None:
                stmt = stmt.where(CouncilMeetingModel.meeting_type == meeting_type.value)
            rows = session.execute(stmt).scalars().all()
            return [_meeting_row_to_dict(r) for r in rows]
        finally:
            session.close()

    def list_action_items(
        self,
        *,
        meeting_id: Optional[str] = None,
        assigned_to: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出 action items（可按 meeting / 负责人 / 状态过滤）。"""
        session = self._session_factory()()
        try:
            stmt = (
                select(StrategicActionItem)
                .order_by(desc(StrategicActionItem.created_at))
                .limit(max(1, min(limit, 500)))
            )
            if meeting_id is not None:
                stmt = stmt.where(StrategicActionItem.meeting_id == meeting_id)
            if assigned_to is not None:
                stmt = stmt.where(StrategicActionItem.assigned_to == assigned_to)
            if status is not None:
                stmt = stmt.where(StrategicActionItem.status == status)
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "action_id": r.action_id,
                    "decision_id": r.decision_id,
                    "meeting_id": r.meeting_id,
                    "description": r.description,
                    "assigned_to": r.assigned_to,
                    "status": r.status,
                    "due_at": r.due_at.isoformat() if r.due_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "block_reason": r.block_reason,
                    "result": _loads(r.result_json, {}),
                }
                for r in rows
            ]
        finally:
            session.close()

    def update_action_item(
        self,
        action_id: str,
        *,
        status: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        block_reason: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """更新 action item 状态。"""
        valid_status = {"pending", "in_progress", "completed", "blocked", "cancelled"}
        if status is not None and status not in valid_status:
            raise ValueError(f"invalid status {status}; must be one of {valid_status}")
        session = self._session_factory()()
        try:
            row = session.execute(
                select(StrategicActionItem).where(StrategicActionItem.action_id == action_id)
            ).scalar_one_or_none()
            if row is None:
                raise ValueError(f"action item not found: {action_id}")
            now = datetime.now(timezone.utc)
            if status is not None:
                row.status = status
            if result is not None:
                row.result_json = json.dumps(result, ensure_ascii=False)
            if block_reason is not None:
                row.block_reason = block_reason
            if status == "completed" and completed_at is None:
                row.completed_at = now
            elif completed_at is not None:
                row.completed_at = completed_at
            row.updated_at = now
            session.commit()
            return {
                "action_id": row.action_id,
                "status": row.status,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- 内部 ----------------

    def _get_meeting(self, session: Any, meeting_id: str) -> Optional[CouncilMeetingModel]:
        return session.execute(
            select(CouncilMeetingModel).where(CouncilMeetingModel.meeting_id == meeting_id)
        ).scalar_one_or_none()


__all__ = [
    "CouncilMeetingService",
    "MeetingDecisionRef",
    "MeetingParticipants",
    "MeetingStatus",
    "MeetingType",
]
