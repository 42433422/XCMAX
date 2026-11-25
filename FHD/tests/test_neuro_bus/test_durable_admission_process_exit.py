"""Subprocess crash boundaries for the durable NeuroBus admission record.

These use real file-backed SQLite/WAL transactions. os._exit bypasses cleanup;
they do not simulate power loss, a handler completion or Redis persistence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.neuro_bus.event_store import EventStore, EventStoreMode
from app.neuro_bus.events.events_base import NeuroEvent


@pytest.mark.parametrize(
    ("phase", "exit_code", "committed"),
    [
        ("before_write", 71, False),
        ("during_write", 72, False),
        ("after_commit_before_ack", 73, True),
    ],
)
def test_process_exit_at_admission_boundary(tmp_path, phase, exit_code, committed):
    """An uncommitted insert must roll back; an ACK-less commit must survive."""
    path = str(tmp_path / "admission.sqlite")
    event = NeuroEvent("test.durable_crash", {"tenant_id": "t1", "value": 21})
    payload = json.dumps(event.to_dict(), ensure_ascii=False)
    fhd_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import hashlib
        import json
        import os
        import sys
        import time

        from app.neuro_bus.event_store import EventStore, EventStoreMode
        from app.neuro_bus.events.events_base import NeuroEvent

        path, phase, encoded = sys.argv[1:]
        event = NeuroEvent.from_dict(
            json.loads(encoded), preserve_queue_identity=True
        )
        store = EventStore(EventStoreMode.SQLITE, path)
        if phase == "before_write":
            os._exit(71)

        if phase == "during_write":
            encoded_event = json.dumps(
                event.to_dict(), ensure_ascii=False, sort_keys=True,
                allow_nan=False, separators=(",", ":"),
            )
            digest = hashlib.sha256(encoded_event.encode("utf-8")).hexdigest()
            with store._storage.transaction() as connection:
                connection.execute(
                    "INSERT INTO neuro_admissions VALUES (?, ?, ?, ?)",
                    (event.metadata.event_id, encoded_event, digest, time.time()),
                ).close()
                # Terminate with an open transaction: no Python finally/rollback.
                os._exit(72)

        receipt = store.admit(event)
        assert receipt.newly_admitted
        # Crash after COMMIT but before the caller can receive an ACK or dispatch.
        os._exit(73)
        """
    )
    child = subprocess.run(
        [sys.executable, "-c", script, path, phase, payload],
        cwd=fhd_root,
        env={
            **os.environ,
            "PYTHONPATH": str(fhd_root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == exit_code, child.stderr
    store = EventStore(EventStoreMode.SQLITE, path)
    try:
        restored = store.get_admitted_event(event.metadata.event_id)
        if committed:
            assert restored is not None
            assert restored.to_dict() == event.to_dict()
            receipt = store.admit(restored)
            assert not receipt.newly_admitted
            assert receipt.event_id == event.metadata.event_id
            assert len(receipt.event_sha256) == 64
        else:
            assert restored is None
            assert store.admit(event).newly_admitted
    finally:
        store.close()
