from __future__ import annotations

from datetime import datetime, timezone

from modstore_server.db.base import Base
from modstore_server.db.strategic import StrategicDecision
from modstore_server.models import get_engine, get_session_factory
from modstore_server.public_strategic_goals import verified_strategic_goal_items


def _status(
    *,
    integrity: bool = True,
    created_at: str = "2026-07-29T06:00:00+00:00",
) -> dict:
    return {
        "ok": integrity,
        "ready": integrity,
        "hash_chain_verified": integrity,
        "recent_receipts": [
            {
                "receipt_id": "council-goal-one",
                "created_at": created_at,
                "verified": True,
                "goal_id": "goal-one",
                "loop_run_id": "loop-one",
                "para_task_id": "para-one",
                "roles": {"para": {"status": "linked", "source_verified": True}},
            }
        ],
    }


def test_verified_council_goal_reads_real_strategic_decision(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    Base.metadata.create_all(bind=get_engine())
    with get_session_factory()() as session:
        session.query(StrategicDecision).filter(
            StrategicDecision.decision_id == "goal-one"
        ).delete()
        session.add(
            StrategicDecision(
                decision_id="goal-one",
                title="完成 Goal 到 Loop 的真实闭环",
                rationale="test",
                proposed_by="change-request-auditor",
                proposed_at=now,
                decision_type="strategic",
                scope="global",
                status="executing",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    monkeypatch.setattr(
        "modstore_server.strategic_council.strategic_council_status",
        lambda limit=100: _status(),
    )

    items = verified_strategic_goal_items()

    assert len(items) == 1
    assert items[0]["title"] == "完成 Goal 到 Loop 的真实闭环"
    assert items[0]["status"] == "in_progress"
    assert items[0]["goal_id"] == "goal-one"
    assert items[0]["loop_run_id"] == "loop-one"
    assert items[0]["para_task_id"] == "para-one"


def test_broken_council_hash_chain_exposes_no_goal(monkeypatch) -> None:
    monkeypatch.setattr(
        "modstore_server.strategic_council.strategic_council_status",
        lambda limit=100: _status(integrity=False),
    )

    assert verified_strategic_goal_items() == []


def test_verified_goal_uses_shanghai_business_day(monkeypatch) -> None:
    monkeypatch.setattr(
        "modstore_server.strategic_council.strategic_council_status",
        lambda limit=100: _status(created_at="2026-07-28T16:05:00+00:00"),
    )

    [item] = verified_strategic_goal_items()

    assert item["day"] == "2026-07-29"
    assert item["ts"] == "00:05"
