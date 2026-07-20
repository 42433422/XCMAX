"""Tests for ``modstore_server.system_status_daily_report``.

覆盖：默认 endpoints / env override / probe 各分支 / append_sample 落盘 /
sample_once 部分-整体失败 / compute_availability 全量-部分-空 / _classify_health
门槛 / generate_daily_report 聚合 / write_daily_report 原子写 / cleanup_old_samples /
sample_job / daily_summary_job。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from modstore_server import system_status_daily_report as ssr


@pytest.fixture
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离 MODSTORE_RUNTIME_DIR，让样本/日报写到 tmp_path。"""
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(runtime))
    monkeypatch.delenv("MODSTORE_SYSTEM_STATUS_ENDPOINTS", raising=False)
    return runtime


def test_default_endpoints_returns_three(isolated_runtime: Path):
    endpoints = ssr.configured_endpoints()
    names = [name for name, _ in endpoints]
    assert "cvm" in names
    assert "local_api" in names
    assert "local_scheduler" in names
    assert len(endpoints) == 3


def test_env_override_endpoints(isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS",
        "prod|https://example.com/health,backup|http://backup:9999/h",
    )
    endpoints = ssr.configured_endpoints()
    assert endpoints == [
        ("prod", "https://example.com/health"),
        ("backup", "http://backup:9999/h"),
    ]


def test_env_override_ignores_malformed_entries(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS",
        "good|https://example.com/health,bad-no-pipe,|empty-name,empty-url|",
    )
    endpoints = ssr.configured_endpoints()
    assert endpoints == [("good", "https://example.com/health")]


def test_probe_endpoint_success(monkeypatch: pytest.MonkeyPatch):
    def fake_get(self, url):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = ssr.probe_endpoint("cvm", "https://example.com/health")
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["error"] is None
    assert result["body"] == {"ok": True}
    assert result["name"] == "cvm"
    assert result["url"] == "https://example.com/health"
    assert "probed_at" in result
    assert isinstance(result["latency_ms"], int)


def test_probe_endpoint_http_500(monkeypatch: pytest.MonkeyPatch):
    def fake_get(self, url):
        req = httpx.Request("GET", url)
        return httpx.Response(500, text="error", request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = ssr.probe_endpoint("cvm", "https://example.com/health")
    assert result["ok"] is False
    assert result["status_code"] == 500
    assert "HTTP 500" in (result["error"] or "")
    assert result["body"] is None


def test_probe_endpoint_connection_error(monkeypatch: pytest.MonkeyPatch):
    def fake_get(self, url):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = ssr.probe_endpoint("cvm", "https://example.com/health")
    assert result["ok"] is False
    assert result["status_code"] is None
    assert "connect_error" in (result["error"] or "")


def test_probe_endpoint_non_json_body(monkeypatch: pytest.MonkeyPatch):
    def fake_get(self, url):
        req = httpx.Request("GET", url)
        return httpx.Response(200, text="not-json", request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = ssr.probe_endpoint("cvm", "https://example.com/health")
    assert result["ok"] is True
    assert result["body"] is None


def test_probe_endpoint_unexpected_exception(monkeypatch: pytest.MonkeyPatch):
    def fake_get(self, url):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = ssr.probe_endpoint("cvm", "https://example.com/health")
    assert result["ok"] is False
    assert "unexpected" in (result["error"] or "")


def test_append_sample_writes_jsonl(isolated_runtime: Path):
    sample = {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": [{"name": "cvm", "ok": True}],
        "total": 1,
        "ok_count": 1,
    }
    ssr.append_sample(sample)
    path = ssr.samples_path()
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["ok_count"] == 1


def test_sample_once_success(isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS", "cvm|https://example.com/health"
    )

    def fake_get(self, url):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    sample = ssr.sample_once()
    assert sample["total"] == 1
    assert sample["ok_count"] == 1
    assert sample["endpoints"][0]["ok"] is True
    lines = ssr.samples_path().read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_sample_once_partial_failure(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS",
        "good|https://good.example/health,bad|https://bad.example/health",
    )

    def fake_get(self, url):
        if "bad.example" in url:
            raise httpx.ConnectError("refused")
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    sample = ssr.sample_once()
    assert sample["total"] == 2
    assert sample["ok_count"] == 1
    bad = [e for e in sample["endpoints"] if e["name"] == "bad"][0]
    assert bad["ok"] is False


def test_compute_availability_all_ok(isolated_runtime: Path):
    now = datetime.now(timezone.utc)
    samples = []
    for i in range(10):
        samples.append(
            {
                "sampled_at": (now - timedelta(minutes=i * 5)).isoformat(),
                "endpoints": [
                    {"name": "cvm", "ok": True},
                    {"name": "local_api", "ok": True},
                ],
            }
        )
    result = ssr.compute_availability(samples, period_hours=24)
    assert result["overall"] == 1.0
    assert result["per_endpoint"]["cvm"]["availability"] == 1.0
    assert result["per_endpoint"]["local_api"]["availability"] == 1.0


def test_compute_availability_partial(isolated_runtime: Path):
    now = datetime.now(timezone.utc)
    samples = [
        {
            "sampled_at": now.isoformat(),
            "endpoints": [
                {"name": "cvm", "ok": True},
                {"name": "local_api", "ok": False, "error": "HTTP 500"},
            ],
        },
        {
            "sampled_at": (now - timedelta(minutes=10)).isoformat(),
            "endpoints": [
                {"name": "cvm", "ok": True},
                {"name": "local_api", "ok": True},
            ],
        },
    ]
    result = ssr.compute_availability(samples, period_hours=24)
    assert result["per_endpoint"]["cvm"]["availability"] == 1.0
    assert result["per_endpoint"]["local_api"]["availability"] == 0.5
    assert result["overall"] < 1.0


def test_compute_availability_empty_returns_zero(isolated_runtime: Path):
    result = ssr.compute_availability([], period_hours=24)
    assert result["overall"] == 0.0
    assert result["per_endpoint"] == {}


def test_compute_availability_filters_old_samples(isolated_runtime: Path):
    now = datetime.now(timezone.utc)
    samples = [
        {
            "sampled_at": (now - timedelta(hours=48)).isoformat(),
            "endpoints": [{"name": "cvm", "ok": False}],
        },
        {
            "sampled_at": now.isoformat(),
            "endpoints": [{"name": "cvm", "ok": True}],
        },
    ]
    result = ssr.compute_availability(samples, period_hours=24)
    assert result["per_endpoint"]["cvm"]["total"] == 1
    assert result["per_endpoint"]["cvm"]["ok"] == 1
    assert result["per_endpoint"]["cvm"]["availability"] == 1.0


def test_classify_health_thresholds():
    assert ssr._classify_health(1.0) == "ok"
    assert ssr._classify_health(0.99) == "ok"
    assert ssr._classify_health(0.95) == "warn"
    assert ssr._classify_health(0.94) == "critical"
    assert ssr._classify_health(0.0) == "critical"


def test_generate_daily_report_aggregates(isolated_runtime: Path):
    now = datetime.now(timezone.utc)
    for i in range(5):
        ssr.append_sample(
            {
                "sampled_at": (now - timedelta(minutes=i * 30)).isoformat(),
                "endpoints": [{"name": "cvm", "ok": True, "latency_ms": 10}],
                "total": 1,
                "ok_count": 1,
            }
        )
    report = ssr.generate_daily_report(period_hours=24)
    assert report["overall_availability"] == 1.0
    assert report["overall_health"] == "ok"
    assert report["per_endpoint"]["cvm"]["availability"] == 1.0
    assert report["per_endpoint"]["cvm"]["health"] == "ok"
    assert report["sample_count"] >= 5
    assert "generated_at" in report


def test_write_daily_report_atomic(isolated_runtime: Path):
    report = {"overall_availability": 0.99, "overall_health": "ok"}
    path = ssr.write_daily_report(report)
    assert path.is_file()
    assert path == ssr.daily_report_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    assert not tmp.exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["overall_availability"] == 0.99


def test_cleanup_old_samples_removes_old(isolated_runtime: Path):
    now = datetime.now(timezone.utc)
    ssr.append_sample(
        {
            "sampled_at": (now - timedelta(days=10)).isoformat(),
            "endpoints": [{"name": "cvm", "ok": True}],
            "total": 1,
            "ok_count": 1,
        }
    )
    ssr.append_sample(
        {
            "sampled_at": now.isoformat(),
            "endpoints": [{"name": "cvm", "ok": True}],
            "total": 1,
            "ok_count": 1,
        }
    )
    removed = ssr.cleanup_old_samples(max_age_days=7)
    assert removed == 1
    lines = ssr.samples_path().read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1


def test_cleanup_old_samples_no_file_returns_zero(isolated_runtime: Path):
    assert ssr.cleanup_old_samples(max_age_days=7) == 0


def test_system_status_sample_job_writes_sample(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS", "cvm|https://example.com/health"
    )

    def fake_get(self, url):
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    ssr.system_status_sample_job()
    assert ssr.samples_path().is_file()


def test_system_status_daily_summary_job_writes_report(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "MODSTORE_SYSTEM_STATUS_ENDPOINTS", "cvm|https://example.com/health"
    )
    now = datetime.now(timezone.utc)
    ssr.append_sample(
        {
            "sampled_at": now.isoformat(),
            "endpoints": [{"name": "cvm", "ok": True}],
            "total": 1,
            "ok_count": 1,
        }
    )
    ssr.system_status_daily_summary_job()
    assert ssr.daily_report_path().is_file()
    parsed = json.loads(ssr.daily_report_path().read_text(encoding="utf-8"))
    assert "overall_availability" in parsed


def test_system_status_sample_job_swallows_exception(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    """sample_once 抛异常时 job 不应抛——避免 APScheduler job 实例槽位泄漏。"""

    def boom():
        raise RuntimeError("unexpected")

    monkeypatch.setattr(ssr, "sample_once", boom)
    ssr.system_status_sample_job()


def test_system_status_daily_summary_job_swallows_exception(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(ssr, "generate_daily_report", boom)
    ssr.system_status_daily_summary_job()
