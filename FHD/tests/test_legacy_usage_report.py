"""A missing legacy log cannot be used as proof that legacy code is unused."""

import json
import time

from scripts.dev.legacy_usage_report import build_report, render_text


def test_missing_legacy_log_is_unknown_not_zero(tmp_path):
    report = build_report(tmp_path / "legacy_usage.log", 168)

    assert report["source_status"] == "missing"
    assert report["total_events"] is None
    assert report["legacy_ratio"] is None
    assert report["modules"] == []
    assert "do not retire" in render_text(report)


def test_empty_legacy_log_does_not_prove_full_window_coverage(tmp_path):
    path = tmp_path / "legacy_usage.log"
    path.write_text("", encoding="utf-8")

    report = build_report(path, 168)
    assert report["source_status"] == "unverified_zero"
    assert report["total_events"] == 0
    assert report["legacy_ratio"] is None


def test_observed_legacy_event_is_counted_without_publishing_host_path(tmp_path):
    path = tmp_path / "legacy_usage.log"
    path.write_text(
        json.dumps(
            {
                "ts": int(time.time()),
                "module": "app.legacy.report",
                "caller": "verified-fixture",
                "symbol": "run",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_report(path, 168)
    assert report["source_status"] == "observed_events"
    assert report["total_events"] == 1
    assert report["legacy_ratio"] == 0.001
    assert report["log_path"] == "legacy_usage.log"
    assert report["modules"][0]["callers"] == [("verified-fixture", 1)]
