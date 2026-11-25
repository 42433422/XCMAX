"""Replaying a dead letter is not successful when NeuroBus rejects admission."""

from __future__ import annotations

import pytest

from app.neuro_bus.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterReason,
    NeuroBusDLQIntegration,
)
from app.neuro_bus.events.events_base import NeuroEvent


class _Publisher:
    def __init__(self) -> None:
        self.results = [False, True]
        self.seen: list[str] = []

    def publish(self, event: NeuroEvent) -> bool:
        self.seen.append(event.metadata.event_id)
        return self.results.pop(0)


@pytest.mark.parametrize("persistent", [False, True])
def test_replay_publish_rejection_preserves_entry_and_dedup_identity(
    tmp_path, persistent: bool
) -> None:
    path = str(tmp_path / "dead-letter.sqlite3") if persistent else None
    dlq = DeadLetterQueue(storage_path=path)
    try:
        publisher = _Publisher()
        NeuroBusDLQIntegration(dlq).setup_replay_to_bus(publisher)
        event = NeuroEvent(event_type="test.replay", payload={"source": "dlq"})
        entry_id = dlq.enqueue(event, DeadLetterReason.TIMEOUT, "first failure", 0)
        original = dlq.dequeue(entry_id)
        assert original is not None

        assert dlq.replay(entry_id) == (False, "publish_rejected")
        assert dlq.dequeue(entry_id) is not None
        assert dlq._deduplicator.is_replayed(entry_id, original.retry_count) is False
        assert dlq.get_stats()["replayed"] == 0

        assert dlq.replay(entry_id) == (True, "")
        assert publisher.seen == [event.metadata.event_id, event.metadata.event_id]
        assert dlq.get_stats()["replayed"] == 1
        assert dlq.replay(entry_id) == (False, "already_replayed")
    finally:
        dlq.close()


def test_legacy_callback_none_still_means_callback_completed() -> None:
    dlq = DeadLetterQueue()
    observed: list[str] = []
    dlq.on_replay(lambda event: observed.append(event.event_type))
    entry_id = dlq.enqueue(NeuroEvent(event_type="test.legacy", payload={}),
                           DeadLetterReason.TIMEOUT, "first failure", 0)
    assert dlq.replay(entry_id) == (True, "")
    assert observed == ["test.legacy"]
