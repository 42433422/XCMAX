# mypy: disable-error-code="arg-type"
"""Public value objects and serializers for strategic council meetings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List

from modstore_server.db.strategic import CouncilMeeting as CouncilMeetingModel


class MeetingType(str, Enum):
    DAILY_STANDUP = "daily_standup"
    WEEKLY_REVIEW = "weekly_review"
    MONTHLY_STRATEGY = "monthly_strategy"
    AD_HOC = "ad_hoc"
    INCIDENT_REVIEW = "incident_review"


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    CONCLUDED = "concluded"
    CANCELLED = "cancelled"


@dataclass
class MeetingParticipants:
    required: List[str] = field(default_factory=list)
    optional: List[str] = field(default_factory=list)
    chair: str = ""

    def all_ids(self) -> List[str]:
        ids = list(self.required) + list(self.optional)
        if self.chair and self.chair not in ids:
            ids.insert(0, self.chair)
        return ids

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class MeetingDecisionRef:
    decision_id: str
    vote_outcome: str
    vote_summary: Dict[str, Any] = field(default_factory=dict)


def parse_json(raw: str, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def meeting_row_to_dict(row: CouncilMeetingModel) -> Dict[str, Any]:
    return {
        "meeting_id": row.meeting_id,
        "title": row.title,
        "agenda": row.agenda,
        "meeting_type": row.meeting_type,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "concluded_at": row.concluded_at.isoformat() if row.concluded_at else None,
        "status": row.status,
        "participants": parse_json(
            row.participants_json, {"required": [], "optional": [], "chair": ""}
        ),
        "minutes_md": row.minutes_md or "",
        "decisions": parse_json(row.decisions_json, []),
        "action_items": parse_json(row.action_items_json, []),
        "source_digest_record_id": row.source_digest_record_id,
        "source_context": parse_json(row.source_context_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "MeetingDecisionRef",
    "MeetingParticipants",
    "MeetingStatus",
    "MeetingType",
    "meeting_row_to_dict",
    "parse_json",
]
