# FHD/scripts/dev/tests/test_audit_evolution.py
"""audit_evolution.py CLI 单元测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_audit(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "audit_evolution.py"), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def _seed_ledger(path: Path, events: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def test_audit_since_filter(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    new_ts = datetime.now(UTC).isoformat()
    _seed_ledger(
        ledger,
        [
            {"event_id": "1", "timestamp": old_ts, "event_type": "old", "pack_id": "old@1.0"},
            {"event_id": "2", "timestamp": new_ts, "event_type": "new", "pack_id": "new@1.0"},
        ],
    )
    result = _run_audit("--since", "7d", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "new@1.0" in result.stdout
    assert "old@1.0" not in result.stdout


def test_audit_event_filter(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(
        ledger,
        [
            {"event_id": "1", "timestamp": "2026-07-20T10:00:00Z", "event_type": "signal_detected"},
            {
                "event_id": "2",
                "timestamp": "2026-07-20T11:00:00Z",
                "event_type": "pack_listed",
                "pack_id": "x@1.0",
            },
        ],
    )
    result = _run_audit(
        "--event", "pack_listed", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)}
    )
    assert result.returncode == 0
    assert "x@1.0" in result.stdout
    assert "signal_detected" not in result.stdout


def test_audit_status_filter(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(
        ledger,
        [
            {
                "event_id": "1",
                "timestamp": "2026-07-20T10:00:00Z",
                "event_type": "implement_failed",
                "final_status": "needs_human",
            },
            {
                "event_id": "2",
                "timestamp": "2026-07-20T11:00:00Z",
                "event_type": "pack_listed",
                "final_status": "pack_listed",
                "pack_id": "x@1.0",
            },
        ],
    )
    result = _run_audit(
        "--status", "needs_human", env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)}
    )
    assert result.returncode == 0
    assert "implement_failed" in result.stdout
    assert "pack_listed" not in result.stdout


def test_audit_mark_audited(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    _seed_ledger(
        ledger,
        [
            {
                "event_id": "evt-001",
                "timestamp": "2026-07-20T10:00:00Z",
                "event_type": "pack_listed",
                "pack_id": "x@1.0",
                "owner_audit": {"audited": False, "audited_at": None, "verdict": None},
            },
        ],
    )
    result = _run_audit(
        "--mark-audited",
        "evt-001",
        "--verdict",
        "approved",
        env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)},
    )
    assert result.returncode == 0
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    evt = json.loads(lines[0])
    assert evt["owner_audit"]["audited"] is True
    assert evt["owner_audit"]["verdict"] == "approved"


def test_audit_no_events(tmp_path):
    ledger = tmp_path / "evolution_decisions.jsonl"
    ledger.write_text("", encoding="utf-8")
    result = _run_audit(env={"MODSTORE_EVOLUTION_LEDGER_PATH": str(ledger)})
    assert result.returncode == 0
    assert "no events" in result.stdout.lower()
