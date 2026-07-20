"""Tests for ``system_status_daily_report`` (2026-07-20 Week 3 任务 4).

验证：
- configured_endpoints：默认三端 / env override / 异常条目跳过
- probe_endpoint：200 / 500 / 连接错误 / 非 JSON / 异常 status
- append_sample / sample_once：写盘 / 部分失败也写
- compute_availability：全 ok / 部分 ok / 空样本 / 旧样本过滤
- _classify_health：阈值边界
- generate_daily_report：结构正确
- write_daily_report：原子写 + 文件可读回
- cleanup_old_samples：旧样本删除 / 新样本保留
- system_status_sample_job / system_status_daily_summary_job：端到端跑通 + 异常吞
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest

from modstore_server import system_status_daily_report as ssd


# ---- configured_endpoints --------------------------------------------------


def test_configured_endpoints_defaults(monkeypatch):
    """env 未设 → 返回 CVM + local_api + local_scheduler 三端。"""
    monkeypatch.delenv("MODSTORE_SYSTEM_STATUS_ENDPOINTS", raising=False)
    endpoints = ssd.configured_endpoints()
    assert len(endpoints) == 3
    names = [name for name, _ in endpoints]
    assert "cvm" in names
    assert "local_api" in names
    assert "local_scheduler" in names


def test_configured_endpoints_env_override(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS",
        "primary|https://example.com/health,secondary|http://127.0.0.1:9000/health",
    )
    endpoints = ssd.configured_endpoints()
    assert endpoints == [
        ("primary", "https://example.com/health"),
        ("secondary", "http://127.0.0.1:9000/health"),
    ]


def test_configured_endpoints_drops_malformed(monkeypatch):
    """空条目 / 无 | 条目 / 空 name 都跳过。"""
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS",
        "ok|https://example.com,,bad_no_pipe,|empty_name",
    )
    endpoints = ssd.configured_endpoints()
    assert endpoints == [("ok", "https://example.com")]


# ---- probe_endpoint --------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any = None):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


class _FakeClient:
    """Stand-in for httpx.Client that returns a queued response or raises."""

    def __init__(self, response: Any = None, error: Exception | None = None):
        self._response = response
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        if self._error is not None:
            raise self._error
        return self._response


def test_probe_endpoint_success(monkeypatch):
    fake_client = _FakeClient(response=_FakeResponse(200, body={"ok": True}))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake_client)
    probe = ssd.probe_endpoint("cvm", "https://example.com/health")
    assert probe["ok"] is True
    assert probe["status_code"] == 200
    assert probe["error"] is None
    assert probe["body"] == {"ok": True}
    assert probe["latency_ms"] >= 0.0


def test_probe_endpoint_500_is_not_ok(monkeypatch):
    fake_client = _FakeClient(response=_FakeResponse(500, body=None))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake_client)
    probe = ssd.probe_endpoint("cvm", "https://example.com/health")
    assert probe["ok"] is False
    assert probe["status_code"] == 500
    assert "500" in probe["error"]
    assert probe["body"] is None


def test_probe_endpoint_connect_error_is_not_ok(monkeypatch):
    import httpx

    fake_client = _FakeClient(error=httpx.ConnectError("connection refused"))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake_client)
    probe = ssd.probe_endpoint("cvm", "https://example.com/health")
    assert probe["ok"] is False
    assert probe["status_code"] is None
    assert "ConnectError" in probe["error"]
    assert "connection refused" in probe["error"]


def test_probe_endpoint_non_json_body_still_ok_for_200(monkeypatch):
    fake_client = _FakeClient(response=_FakeResponse(200, body=None))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake_client)
    probe = ssd.probe_endpoint("cvm", "https://example.com/health")
    # 200 即使 body 不是 JSON 也算 ok
    assert probe["ok"] is True
    assert probe["body"] is None


def test_probe_endpoint_unexpected_status_records_error(monkeypatch):
    fake_client = _FakeClient(response=_FakeResponse(404))
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake_client)
    probe = ssd.probe_endpoint("cvm", "https://example.com/health")
    assert probe["ok"] is False
    assert probe["status_code"] == 404
    assert "404" in probe["error"]


# ---- append_sample / sample_once -------------------------------------------


def test_append_sample_writes_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    sample = {"timestamp": "2026-07-20T12:00:00+00:00", "ok": True}
    ssd.append_sample(sample)
    sample_file = tmp_path / "system_status_health.jsonl"
    assert sample_file.exists()
    content = sample_file.read_text(encoding="utf-8")
    assert content.endswith("\n")
    parsed = json.loads(content.strip())
    assert parsed["ok"] is True


def test_sample_once_writes_aggregate(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        ssd,
        "configured_endpoints",
        lambda: [("cvm", "https://example.com/h"), ("local", "http://127.0.0.1:8788/h")],
    )
    probes = [
        {"name": "cvm", "ok": True, "status_code": 200, "latency_ms": 5.0, "error": None},
        {"name": "local", "ok": False, "status_code": None, "latency_ms": 1.0, "error": "conn refused"},
    ]
    probe_iter = iter(probes)
    monkeypatch.setattr(ssd, "probe_endpoint", lambda name, url, timeout=5.0: next(probe_iter))
    sample = ssd.sample_once()
    assert sample["ok_count"] == 1
    assert sample["total_count"] == 2
    sample_file = tmp_path / "system_status_health.jsonl"
    parsed = json.loads(sample_file.read_text(encoding="utf-8").strip())
    assert parsed["ok_count"] == 1


# ---- compute_availability --------------------------------------------------


def _sample_at(minutes_ago: float, ok: bool, name: str = "cvm") -> Dict[str, Any]:
    from modstore_server.system_status_daily_report import _iso, _utc_now

    return {
        "timestamp": _iso(_utc_now() - timedelta(minutes=minutes_ago)),
        "endpoints": [
            {"name": name, "ok": ok, "status_code": 200 if ok else None, "error": None if ok else "x"}
        ],
    }


def test_compute_availability_all_ok():
    samples = [_sample_at(5, True), _sample_at(10, True), _sample_at(20, True)]
    avail = ssd.compute_availability(samples, window_hours=24)
    assert "cvm" in avail
    assert avail["cvm"]["total"] == 3
    assert avail["cvm"]["ok"] == 3
    assert avail["cvm"]["availability_pct"] == 100.0


def test_compute_availability_partial():
    samples = [_sample_at(5, True), _sample_at(10, False), _sample_at(20, True)]
    avail = ssd.compute_availability(samples, window_hours=24)
    assert avail["cvm"]["total"] == 3
    assert avail["cvm"]["ok"] == 2
    assert avail["cvm"]["availability_pct"] == pytest.approx(66.67, rel=0.01)


def test_compute_availability_empty_samples():
    avail = ssd.compute_availability([], window_hours=24)
    assert avail == {}


def test_compute_availability_filters_old_samples():
    """window 外的样本不计入。"""
    samples = [
        _sample_at(1, True),  # 在 24h 窗口内
        _sample_at(48 * 60, True),  # 48h 前，超出窗口
    ]
    avail = ssd.compute_availability(samples, window_hours=24)
    assert avail["cvm"]["total"] == 1


def test_compute_availability_zero_division_safety():
    """endpoints 名为空的样本被跳过，不导致除零。"""
    samples = [
        {"timestamp": ssd._iso(ssd._utc_now()), "endpoints": [{"name": "", "ok": True}]}
    ]
    avail = ssd.compute_availability(samples, window_hours=24)
    assert avail == {}


# ---- _classify_health ------------------------------------------------------


def test_classify_health_thresholds():
    assert ssd._classify_health(100.0) == "ok"
    assert ssd._classify_health(99.0) == "ok"
    assert ssd._classify_health(98.99) == "warn"
    assert ssd._classify_health(95.0) == "warn"
    assert ssd._classify_health(94.99) == "critical"
    assert ssd._classify_health(0.0) == "critical"


# ---- generate_daily_report -------------------------------------------------


def test_generate_daily_report_structure():
    samples = [_sample_at(5, True), _sample_at(60, False)]
    report = ssd.generate_daily_report(samples)
    assert "report_date" in report
    assert report["window_hours"] == 24
    assert "overall" in report
    assert "endpoints" in report
    assert isinstance(report["endpoints"], list)
    assert len(report["endpoints"]) == 1
    endpoint = report["endpoints"][0]
    assert endpoint["name"] == "cvm"
    assert endpoint["total_samples"] == 2
    assert endpoint["ok_samples"] == 1
    assert endpoint["availability_pct"] == 50.0
    assert endpoint["health"] == "critical"
    assert "sample_file" in report


def test_generate_daily_report_overall_aggregates_across_endpoints():
    samples = [
        {"timestamp": ssd._iso(ssd._utc_now()),
         "endpoints": [{"name": "a", "ok": True}, {"name": "b", "ok": False}]},
        {"timestamp": ssd._iso(ssd._utc_now()),
         "endpoints": [{"name": "a", "ok": True}, {"name": "b", "ok": True}]},
    ]
    report = ssd.generate_daily_report(samples)
    assert report["overall"]["total_samples"] == 4
    assert report["overall"]["ok_samples"] == 3
    assert report["overall"]["availability_pct"] == 75.0
    assert report["overall"]["health"] == "critical"


# ---- write_daily_report ----------------------------------------------------


def test_write_daily_report_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    report = {"report_date": "2026-07-20T00:00:00+00:00", "overall": {"availability_pct": 100.0}}
    path = ssd.write_daily_report(report)
    assert path.exists()
    assert path.name == "system_status_daily_report.json"
    # 临时文件已被 rename 删除
    assert not (tmp_path / "system_status_daily_report.json.tmp").exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["report_date"] == "2026-07-20T00:00:00+00:00"


def test_write_daily_report_overwrites_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    path = ssd.write_daily_report({"version": 1})
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    # 二次写覆盖
    path = ssd.write_daily_report({"version": 2})
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


# ---- cleanup_old_samples ---------------------------------------------------


def test_cleanup_old_samples_drops_old_keeps_new(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    sample_file = tmp_path / "system_status_health.jsonl"
    old_sample = _sample_at(48 * 60, True)  # 48h 前
    new_sample = _sample_at(5, True)  # 5min 前
    sample_file.write_text(
        json.dumps(old_sample) + "\n" + json.dumps(new_sample) + "\n",
        encoding="utf-8",
    )
    dropped = ssd.cleanup_old_samples(days=1)
    assert dropped == 1
    lines = sample_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["timestamp"] == new_sample["timestamp"]


def test_cleanup_old_samples_no_file_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    assert ssd.cleanup_old_samples() == 0


def test_cleanup_old_samples_all_recent_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    sample_file = tmp_path / "system_status_health.jsonl"
    sample_file.write_text(
        json.dumps(_sample_at(5, True)) + "\n",
        encoding="utf-8",
    )
    assert ssd.cleanup_old_samples() == 0


# ---- system_status_sample_job / system_status_daily_summary_job ------------


def test_system_status_sample_job_writes_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        ssd,
        "configured_endpoints",
        lambda: [("test", "http://127.0.0.1:9999/health")],
    )
    monkeypatch.setattr(
        ssd,
        "probe_endpoint",
        lambda name, url, timeout=5.0: {
            "name": name, "ok": True, "status_code": 200, "latency_ms": 1.0, "error": None
        },
    )
    ssd.system_status_sample_job()
    sample_file = tmp_path / "system_status_health.jsonl"
    assert sample_file.exists()
    parsed = json.loads(sample_file.read_text(encoding="utf-8").strip())
    assert parsed["ok_count"] == 1


def test_system_status_sample_job_swallows_exception(monkeypatch, tmp_path):
    """sample_once 抛异常时 job 不抛（APScheduler 不能让 job 失败卡住调度器）。"""
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(ssd, "sample_once", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(ssd, "cleanup_old_samples", lambda days=14: 0)
    # 不应抛
    ssd.system_status_sample_job()


def test_system_status_daily_summary_job_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    sample_file = tmp_path / "system_status_health.jsonl"
    sample_file.write_text(
        json.dumps(_sample_at(5, True)) + "\n" + json.dumps(_sample_at(60, False)) + "\n",
        encoding="utf-8",
    )
    ssd.system_status_daily_summary_job()
    report_file = tmp_path / "system_status_daily_report.json"
    assert report_file.exists()
    parsed = json.loads(report_file.read_text(encoding="utf-8"))
    assert "overall" in parsed
    assert "endpoints" in parsed


def test_system_status_daily_summary_job_swallows_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(ssd, "_read_samples", lambda limit=5000: (_ for _ in ()).throw(RuntimeError("boom")))
    # 不应抛
    ssd.system_status_daily_summary_job()


# ---- _runtime_dir fallback -------------------------------------------------


def test_runtime_dir_fallback_when_env_unset(monkeypatch):
    monkeypatch.delenv("MODSTORE_RUNTIME_DIR", raising=False)
    # 默认路径在 ~/Library/Application Support/XCMAX/modstore-daily/runtime
    path = ssd._runtime_dir()
    assert "modstore-daily" in str(path)
    assert "runtime" in str(path)
