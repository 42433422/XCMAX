# 成都修茈科技有限公司/MODstore_deploy/tests/test_evolution_signal_aggregator.py
"""aggregate_signals() 单元测试。"""

from __future__ import annotations

import json

import pytest

from modstore_server.evolution_signal_collector import aggregate_signals


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    """伪造 3 个扫描 workflow 的 JSON 报告。"""
    legacy = tmp_path / "legacy_usage_report.json"
    legacy.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-20T08:00:00Z",
                "total_files": 120,
                "legacy_files": 35,
                "legacy_ratio": 0.29,
            }
        ),
        encoding="utf-8",
    )

    intent = tmp_path / "intent_benchmark_report.json"
    intent.write_text(
        json.dumps(
            {
                "generated_at": "2026-07-20T03:00:00Z",
                "accuracy": 0.72,
                "test_cases": 200,
                "failures": 56,
            }
        ),
        encoding="utf-8",
    )

    slo = tmp_path / "slo_metrics.json"
    slo.write_text(
        json.dumps(
            {
                "window": "30d",
                "availability": 0.987,
                "p95_latency_ms": 450,
                "error_rate": 0.013,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(legacy))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(intent))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(slo))
    return tmp_path


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
    slo_path = tmp_reports / "slo_metrics.json"
    slo_path.write_text(
        json.dumps(
            {
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
    """3 个报告都不存在时返回空 signal。"""
    monkeypatch.setenv("MODSTORE_LEGACY_REPORT_PATH", str(tmp_path / "nope1.json"))
    monkeypatch.setenv("MODSTORE_INTENT_REPORT_PATH", str(tmp_path / "nope2.json"))
    monkeypatch.setenv("MODSTORE_SLO_REPORT_PATH", str(tmp_path / "nope3.json"))
    out = aggregate_signals()
    assert out["legacy_usage"]["signal_score"] == 0
    assert out["intent_benchmark"]["signal_score"] == 0
    assert out["slo_metrics"]["signal_score"] == 0


def test_aggregate_total_score(tmp_reports):
    out = aggregate_signals()
    assert out["total_score"] > 0
    assert out["signals_to_propose"] >= 1  # 至少 intent 触发


def test_aggregate_legacy_high_ratio_triggers_signal(tmp_reports, monkeypatch):
    """legacy ratio > 0.25 触发 signal。"""
    legacy_path = tmp_reports / "legacy_usage_report.json"
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
