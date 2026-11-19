# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py
"""aggregate_signals() 单元测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from modstore_server import evolution_signal_collector
from modstore_server.evolution_signal_collector import aggregate_signals

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(
        evolution_signal_collector,
        "datetime",
        SimpleNamespace(now=lambda _tz: NOW, fromisoformat=datetime.fromisoformat),
    )
    monkeypatch.delenv("MODSTORE_EVOLUTION_SIGNAL_LOOKBACK_HOURS", raising=False)
    monkeypatch.delenv("MODSTORE_ENABLE_CATALOG_GAP_SCAN", raising=False)


def _report(**changes):
    return {
        "generated_at": NOW.isoformat(),
        "window": "30d",
        "readings": {"SLO-API-03": {"reading_numeric": 0.0, "meets_target": True}},
        **changes,
    }


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    reports = {
        "LEGACY": {"legacy_ratio": 0.29, "total_files": 120, "legacy_files": 35},
        "INTENT": {"accuracy": 0.72, "test_cases": 200, "failures": 56},
        "SLO": _report(),
    }
    for source, report in reports.items():
        path = tmp_path / f"{source.lower()}_report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        monkeypatch.setenv(f"MODSTORE_{source}_REPORT_PATH", str(path))
    return tmp_path


def _slo_signal(tmp_reports, report):
    (tmp_reports / "slo_report.json").write_text(json.dumps(report), encoding="utf-8")
    return aggregate_signals()["slo_metrics"]


def test_aggregate_returns_three_sources(tmp_reports):
    out = aggregate_signals()
    assert "legacy_usage" in out
    assert "intent_benchmark" in out
    assert "slo_metrics" in out


def test_aggregate_intent_below_threshold(tmp_reports):
    out = aggregate_signals()
    intent = out["intent_benchmark"]
    assert intent["accuracy"] == 0.72
    assert intent["below_threshold"] is True  # < 0.80
    assert intent["signal_score"] > 0  # 触发提议


def test_aggregate_slo_above_threshold_no_signal(tmp_reports, monkeypatch):
    """SLO 正常时不触发 signal。"""
    slo_path = tmp_reports / "slo_report.json"
    slo_path.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "window": "30d",
                "availability": 0.999,
                "p95_latency_ms": 200,
                "error_rate": 0.001,
            }
        ),
        encoding="utf-8",
    )
    out = aggregate_signals()
    assert out["slo_metrics"]["signal_score"] == 0


def test_aggregate_handles_missing_reports(tmp_path, monkeypatch):
    """Missing measurements require review without inventing a target breach."""
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(tmp_path / "nope1.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(tmp_path / "nope2.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(tmp_path / "nope3.json"))
    out = aggregate_signals()
    assert out["legacy_usage"]["signal_score"] == 0
    assert out["intent_benchmark"]["signal_score"] == 0
    assert out["slo_metrics"]["signal_score"] == 0
    assert out["slo_metrics"]["below_threshold"] is False
    assert out["slo_metrics"]["evidence"]["status"] == "needs_human"
    assert "report_missing" in out["slo_metrics"]["evidence"]["reasons"]


def test_aggregate_total_score(tmp_reports):
    out = aggregate_signals()
    assert out["total_score"] > 0
    assert out["signals_to_propose"] >= 1  # 至少 intent 触发


def test_aggregate_legacy_high_ratio_triggers_signal(tmp_reports, monkeypatch):
    """legacy ratio > 0.25 触发 signal。"""
    legacy_path = tmp_reports / "legacy_report.json"
    legacy_path.write_text(
        json.dumps(
            {
                "total_files": 100,
                "legacy_files": 50,
                "legacy_ratio": 0.50,
            }
        ),
        encoding="utf-8",
    )
    out = aggregate_signals()
    assert out["legacy_usage"]["signal_score"] > 0
    assert out["legacy_usage"]["below_threshold"] is True


def test_historical_report_is_evidence_gap_not_seventy_percent_errors(tmp_reports):
    historical = Path(__file__).resolve().parents[3] / "FHD/metrics/slo-measured-20260903.json"
    report = json.loads(historical.read_text(encoding="utf-8"))
    signal = _slo_signal(tmp_reports, report)
    assert signal["report"] == report
    assert signal["signal_score"] == 0
    assert signal["below_threshold"] is False
    evidence = signal["evidence"]
    assert evidence["status"] == "needs_human"
    assert set(evidence["reasons"]) == {"report_stale", "readings_missing_or_invalid"}
    assert evidence["generated_at"] == "2026-09-03T12:40:32Z"
    assert evidence["window"] == "30d"
    assert evidence["missing_readings"] == 7


def test_current_production_report_retains_partial_observed_failures(tmp_reports):
    fixture = (
        Path(__file__).resolve().parents[3]
        / "FHD/metrics/slo-production/20261118T165951Z-44353504218-1.json"
    )
    report = json.loads(fixture.read_text(encoding="utf-8"))
    signal = _slo_signal(tmp_reports, report)
    assert signal["report"] == report
    assert signal["below_threshold"] is True
    assert signal["signal_score"] > 0
    evidence = signal["evidence"]
    assert evidence["status"] == "needs_human"
    assert "report_stale" not in evidence["reasons"]
    assert "scrape_coverage_incomplete" in evidence["reasons"]
    assert evidence["missing_readings"] == 4
    assert evidence["failed_targets"] == 2


@pytest.mark.parametrize(
    "failed,missing", [(False, False), (False, True), (True, False), (True, True)]
)
def test_current_multidimensional_targets_and_partial_evidence(tmp_reports, failed, missing):
    readings = {
        "latency": {"reading": "740", "meets_target": not failed},
        "error_ratio": {"reading_numeric": 0.0, "meets_target": True},
    }
    if missing:
        readings["first_byte"] = {"reading_numeric": None, "meets_target": None}
    signal = _slo_signal(tmp_reports, _report(readings=readings))
    assert signal["below_threshold"] is failed
    assert signal["signal_score"] == float(failed)
    assert signal["evidence"]["score_kind"] == "review_priority"
    assert signal["evidence"]["status"] == ("needs_human" if missing else "available")
    assert signal["evidence"]["failed_targets"] == int(failed)
    assert signal["evidence"]["missing_readings"] == int(missing)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"generated_at": None}, "generated_at_invalid"),
        ({"generated_at": "not-a-date"}, "generated_at_invalid"),
        ({"generated_at": "2026-11-19T12:00:00"}, "generated_at_invalid"),
        ({"generated_at": "2026-11-19T12:00:01Z"}, "generated_at_future"),
        ({"window": None}, "window_invalid"),
        ({"source_status": "source_unavailable"}, "source_unavailable"),
    ],
)
def test_invalid_evidence_never_claims_healthy(tmp_reports, changes, reason):
    signal = _slo_signal(tmp_reports, _report(**changes))
    assert signal["signal_score"] == 0
    assert signal["below_threshold"] is False
    assert signal["evidence"]["status"] == "needs_human"
    assert reason in signal["evidence"]["reasons"]


@pytest.mark.parametrize("scrape_coverage", [0, None, float("nan")])
def test_missing_scrape_coverage_cannot_silently_pass_all_good_readings(
    tmp_reports, scrape_coverage
):
    signal = _slo_signal(tmp_reports, _report(coverage=1, scrape_coverage=scrape_coverage))
    assert signal["below_threshold"] is False
    assert signal["signal_score"] == 0
    assert signal["evidence"]["status"] == "needs_human"
    assert "scrape_coverage_incomplete" in signal["evidence"]["reasons"]


@pytest.mark.parametrize(
    "readings,availability,error_rate,failed,pending",
    [
        (None, 0, 0.2, True, True),
        ({}, 0, 0.2, True, True),
        ({"latency": {"reading_numeric": 700, "meets_target": True}}, 0, 0.2, True, False),
        ({"latency": {"reading_numeric": 700, "meets_target": False}}, 1, 0, False, False),
    ],
)
def test_explicit_summary_precedence_survives_empty_or_conflicting_readings(
    tmp_reports, readings, availability, error_rate, failed, pending
):
    signal = _slo_signal(
        tmp_reports, _report(availability=availability, error_rate=error_rate, readings=readings)
    )
    assert signal["below_threshold"] is failed
    assert signal["signal_score"] == float(failed)
    assert signal["evidence"]["status"] == ("needs_human" if pending else "available")


@pytest.mark.parametrize("lookback,age,stale", [(24, 24, False), (24, 25, True), (48, 25, False)])
def test_generated_at_uses_signal_lookback_not_window_or_recorded_at(
    tmp_reports, monkeypatch, lookback, age, stale
):
    monkeypatch.setenv("MODSTORE_EVOLUTION_SIGNAL_LOOKBACK_HOURS", str(lookback))
    report = _report(
        generated_at=(NOW - timedelta(hours=age)).isoformat(),
        recorded_at=NOW.isoformat(),
        window="90d",
        readings={"latency": {"reading_numeric": 740, "meets_target": False}},
    )
    signal = _slo_signal(tmp_reports, report)
    assert ("report_stale" in signal["evidence"]["reasons"]) is stale
    assert signal["evidence"]["max_age_hours"] == lookback
    assert signal["below_threshold"] is not stale


@pytest.mark.parametrize("invalid", [None, True, float("nan"), float("inf"), {}, "NaN"])
def test_invalid_numbers_are_missing_not_failed_or_passed(tmp_reports, invalid):
    (tmp_reports / "intent_report.json").write_text(json.dumps({"accuracy": invalid}))
    signal = _slo_signal(
        tmp_reports,
        _report(readings={"latency": {"reading_numeric": invalid, "meets_target": False}}),
    )
    assert signal["signal_score"] == 0
    assert signal["below_threshold"] is False
    assert signal["evidence"]["failed_targets"] == 0
    assert signal["evidence"]["status"] == "needs_human"
    assert aggregate_signals()["intent_benchmark"]["accuracy"] is None
    summary = {
        "generated_at": NOW.isoformat(),
        "window": "30d",
        "availability": invalid,
        "error_rate": 0,
    }
    assert _slo_signal(tmp_reports, summary)["evidence"]["status"] == "needs_human"


@pytest.mark.parametrize(
    "count,target,failed", [(0, False, False), (1, False, True), (1, True, False)]
)
def test_sample_shortfall_does_not_invent_failure_or_hide_observed_breach(
    tmp_reports, count, target, failed
):
    signal = _slo_signal(
        tmp_reports,
        _report(
            coverage=0.5,
            readings={
                "latency": {
                    "reading_numeric": 740,
                    "meets_target": target,
                    "sample_count": count,
                    "sample_sufficient": False,
                    "passes": False,
                }
            },
        ),
    )
    assert signal["below_threshold"] is failed
    assert signal["signal_score"] == float(failed)
    assert signal["evidence"]["status"] == "needs_human"


@pytest.mark.parametrize("report", [[], "invalid-report", {"readings": []}])
def test_invalid_report_shapes_require_review(tmp_reports, report):
    signal = _slo_signal(tmp_reports, report)
    assert signal["signal_score"] == 0
    assert signal["evidence"]["status"] == "needs_human"


def test_explicit_zero_accuracy_and_availability_remain_real_failures(tmp_reports):
    (tmp_reports / "intent_report.json").write_text('{"accuracy": 0}', encoding="utf-8")
    _slo_signal(
        tmp_reports,
        {"generated_at": NOW.isoformat(), "window": "30d", "availability": 0, "error_rate": 0},
    )
    signals = aggregate_signals()
    assert signals["intent_benchmark"]["accuracy"] == 0
    assert signals["intent_benchmark"]["below_threshold"] is True
    assert signals["slo_metrics"]["below_threshold"] is True
    assert signals["slo_metrics"]["signal_score"] > 0


def test_catalog_gap_scan_is_explicit_bounded_and_self_closing(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_ENABLE_CATALOG_GAP_SCAN", "true")
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    out = aggregate_signals()
    gap = out["catalog_capability_gap"]
    assert gap["signal_score"] == 1.0
    assert gap["report"]["package_id"] == "autonomy-gap-analyst"
    assert gap["report"]["bounded_files"] == 3

    source_dir = (
        tmp_path
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "catalog_data"
        / "files"
        / "autonomy-gap-analyst@1.0.0"
    )
    source_dir.mkdir(parents=True)
    (source_dir / "manifest.json").write_text("{}", encoding="utf-8")
    closed = aggregate_signals()["catalog_capability_gap"]
    assert closed["signal_score"] == 0.0
    assert closed["report"]["source_present"] is True
