from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "security" / "verify_security_scan_pair.py"
)
GATE_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "security" / "security_release_gate.py"
)
RELEASE_SHA = "a" * 40


def _required_scanners() -> list[str]:
    spec = importlib.util.spec_from_file_location("security_release_gate", GATE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.REQUIRED_SCANNERS)


SCANNERS = _required_scanners()


def _write_scan(directory: Path, start: datetime) -> None:
    """Write a full zero-finding scan run whose scanner stamps span 18 minutes."""
    directory.mkdir(parents=True, exist_ok=True)
    for index, scanner in enumerate(SCANNERS):
        (directory / f"{scanner}.json").write_text(
            json.dumps(
                {
                    "available": True,
                    "scanned_at": (start + timedelta(minutes=2 * index)).isoformat(),
                    "release_sha": RELEASE_SHA,
                    "source_sha": RELEASE_SHA,
                    "findings": [],
                }
            )
        )


def _run_pair(previous: Path, current: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--previous-dir",
            str(previous),
            "--current-dir",
            str(current),
            "--release-sha",
            RELEASE_SHA,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout)


def _same_utc_date(value: str) -> bool:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).date()
        == datetime(2026, 9, 5, tzinfo=UTC).date()
    )


def test_scans_on_consecutive_utc_days_still_pass(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_scan(previous, datetime(2026, 9, 4, 10, 0, tzinfo=UTC))
    _write_scan(current, datetime(2026, 9, 5, 10, 0, tzinfo=UTC))

    result = _run_pair(previous, current)

    pair_blockers = [
        item
        for item in result["blockers"]
        if item.startswith(("scans_are_not", "scan_pair_gap", "scan_pair_timestamp"))
    ]
    assert pair_blockers == []


def test_same_day_pair_with_independent_gap_passes(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_scan(previous, datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    _write_scan(current, datetime(2026, 9, 5, 9, 0, tzinfo=UTC))

    result = _run_pair(previous, current)

    pair_blockers = [
        item
        for item in result["blockers"]
        if item.startswith(("scans_are_not", "scan_pair_gap", "scan_pair_timestamp"))
    ]
    assert pair_blockers == []
    assert _same_utc_date(_read_first_stamp(current)) is True


def test_same_day_pair_copied_report_is_blocked(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_scan(previous, datetime(2026, 9, 5, 8, 0, tzinfo=UTC))
    _write_scan(current, datetime(2026, 9, 5, 8, 10, tzinfo=UTC))

    result = _run_pair(previous, current)

    assert "scan_pair_gap_too_small" in result["blockers"]
    assert "scans_are_not_on_consecutive_utc_days" not in result["blockers"]


def test_same_day_pair_identical_timestamps_are_blocked(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    stamp = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
    _write_scan(previous, stamp)
    _write_scan(current, stamp)

    result = _run_pair(previous, current)

    assert "scan_pair_gap_too_small" in result["blockers"]


def test_current_scan_earlier_than_previous_is_blocked(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_scan(previous, datetime(2026, 9, 6, 8, 0, tzinfo=UTC))
    _write_scan(current, datetime(2026, 9, 5, 9, 0, tzinfo=UTC))

    result = _run_pair(previous, current)

    assert "scans_are_not_on_consecutive_utc_days" in result["blockers"]


def test_scan_pair_two_days_apart_is_blocked(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_scan(previous, datetime(2026, 9, 3, 8, 0, tzinfo=UTC))
    _write_scan(current, datetime(2026, 9, 5, 9, 0, tzinfo=UTC))

    result = _run_pair(previous, current)

    assert "scans_are_not_on_consecutive_utc_days" in result["blockers"]


def _read_first_stamp(directory: Path) -> str:
    payload = json.loads((directory / f"{SCANNERS[0]}.json").read_text())
    return str(payload["scanned_at"])
