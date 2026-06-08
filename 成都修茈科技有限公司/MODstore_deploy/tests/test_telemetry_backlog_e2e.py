"""P10：遥测 ingest → 建议单 → auto-dispatch 可测闭环。"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _enable_telemetry_backlog(monkeypatch):
    monkeypatch.setenv("XCAGI_TELEMETRY_BACKLOG_ENABLED", "1")


def test_ingest_coverage_drop_creates_suggestion(monkeypatch):
    captured = []

    def _fake_create(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "suggestion_id": 42}

    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.create_employee_suggestion",
        _fake_create,
    )
    monkeypatch.setattr("modstore_server.incident_bus.publish", lambda *a, **k: None)

    from modstore_server.telemetry_backlog_loop import ingest_telemetry_signal  # noqa: E402

    out = ingest_telemetry_signal(
        "coverage_drop",
        {"description": "full app 35%", "coverage_percent": 35},
    )
    assert out.get("ok") is True
    assert captured
    assert "fhd-core-maintainer" in captured[0].get("target_employee_ids", [])


def test_plan_release_candidate_from_market(monkeypatch):
    captured = []

    def _fake_create(**kwargs):
        captured.append(kwargs)
        return {"ok": True, "suggestion_id": 99}

    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.create_employee_suggestion",
        _fake_create,
    )

    from modstore_server.telemetry_backlog_loop import plan_release_candidate_from_market

    out = plan_release_candidate_from_market(
        [
            {"description": "竞品 A 发布 AI 助手", "suggested_theme": "AI 助手对标"},
            {"description": "行业报告：移动优先", "suggested_theme": "移动端体验"},
        ]
    )
    assert out.get("suggestion_id") == 99
    assert captured[0].get("kind") == "release_planning"
    assert "deploy-release-officer" in captured[0].get("target_employee_ids", [])


def test_scan_market_signals_from_file(tmp_path, monkeypatch):
    path = tmp_path / "signals.json"
    path.write_text(
        json.dumps(
            [{"description": "竞品动态", "suggested_theme": "对标功能"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XCAGI_MARKET_SIGNALS_FILE", str(path))

    from modstore_server.telemetry_backlog_loop import _scan_market_signals_from_file

    sigs = _scan_market_signals_from_file()
    assert len(sigs) == 1
    assert sigs[0]["type"] == "market_signal"


def test_ingest_passes_auto_dispatch_to_create(monkeypatch):
    create_calls = []

    def _fake_create(**kwargs):
        create_calls.append(kwargs)
        return {"ok": True, "suggestion_id": 7}

    monkeypatch.setattr(
        "modstore_server.employee_autonomy_service.create_employee_suggestion",
        _fake_create,
    )
    monkeypatch.setattr("modstore_server.incident_bus.publish", lambda *a, **k: None)

    from modstore_server.telemetry_backlog_loop import ingest_telemetry_signal

    ingest_telemetry_signal("error_spike", {"description": "pytest spike"})
    assert create_calls
    assert create_calls[0].get("auto_dispatch") is True
    assert "fhd-core-maintainer" in create_calls[0].get("target_employee_ids", [])
