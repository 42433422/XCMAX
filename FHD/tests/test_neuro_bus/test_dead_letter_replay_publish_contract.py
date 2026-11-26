"""Replaying a dead letter is not successful when NeuroBus rejects admission."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    entry_id = dlq.enqueue(
        NeuroEvent(event_type="test.legacy", payload={}),
        DeadLetterReason.TIMEOUT,
        "first failure",
        0,
    )
    assert dlq.replay(entry_id) == (True, "")
    assert observed == ["test.legacy"]


def test_process_death_after_publish_does_not_republish_unknown_outcome(tmp_path):
    path = tmp_path / "dead-letter.sqlite3"
    receipt = tmp_path / "external-receipt.txt"
    dlq = DeadLetterQueue(storage_path=str(path))
    event = NeuroEvent(event_type="test.crash", payload={})
    event_id = event.metadata.event_id
    entry_id = dlq.enqueue(event, DeadLetterReason.TIMEOUT, "first failure", 0)
    dlq.close()

    script = """
import os
import sys
from pathlib import Path
from app.neuro_bus.dead_letter_queue import DeadLetterQueue

queue = DeadLetterQueue(storage_path=sys.argv[1])

def publish(event):
    Path(sys.argv[3]).write_text(event.metadata.event_id, encoding="utf-8")
    os._exit(17)

queue.on_replay(publish)
queue.replay(sys.argv[2])
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), entry_id, str(receipt)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 17, result.stderr
    assert receipt.read_text(encoding="utf-8") == event_id

    reopened = DeadLetterQueue(storage_path=str(path))
    seen: list[str] = []
    try:
        reopened.on_replay(lambda incoming: seen.append(incoming.metadata.event_id))
        assert reopened.replay(entry_id) == (False, "replay_outcome_unknown")
        assert reopened.dequeue(entry_id) is not None
        assert reopened.get_stats()["replayed"] == 0
        assert seen == []
    finally:
        reopened.close()


def test_persistent_replay_audit_only_advances_after_acceptance(tmp_path):
    path = str(tmp_path / "joint.sqlite3")
    first = DeadLetterQueue(storage_path=path)
    publisher = _Publisher()
    event = NeuroEvent(event_type="test.joint", payload={})
    try:
        NeuroBusDLQIntegration(first).setup_replay_to_bus(publisher)
        entry_id = first.enqueue(event, DeadLetterReason.TIMEOUT, "first failure", 0)
        assert first.replay(entry_id) == (False, "publish_rejected")
        assert first.dequeue(entry_id) is not None
        assert [row["action"] for row in first.get_audit_history(entry_id)] == ["enqueued"]
    finally:
        first.close()

    second = DeadLetterQueue(storage_path=path)
    try:
        NeuroBusDLQIntegration(second).setup_replay_to_bus(publisher)
        assert second.replay(entry_id) == (True, "")
        assert [row["action"] for row in second.get_audit_history(entry_id)] == [
            "enqueued",
            "replay_recorded",
        ]
    finally:
        second.close()

    third = DeadLetterQueue(storage_path=path)
    try:
        assert third.replay(entry_id) == (False, "already_replayed")
        assert third.dequeue(entry_id).original_event.metadata.event_id == event.metadata.event_id
        assert publisher.seen == [event.metadata.event_id, event.metadata.event_id]
    finally:
        third.close()
