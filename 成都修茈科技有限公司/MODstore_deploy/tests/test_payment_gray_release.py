"""Tests for the Python -> Java payment gray release helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import payment_gray_release_check as preflight  # type: ignore  # noqa: E402


def test_contract_alignment_requires_java_backend(monkeypatch):
    monkeypatch.delenv("PAYMENT_BACKEND", raising=False)
    result = preflight.probe_contract_alignment(payment_backend="python")
    assert result.ok is False
    assert "PAYMENT_BACKEND" in result.message


def test_contract_alignment_passes_in_java_mode(monkeypatch):
    result = preflight.probe_contract_alignment(payment_backend="java", java_url="http://java")
    assert result.ok is True
    proxied = result.detail["proxied_prefixes"]
    for prefix in ("/api/payment", "/api/wallet", "/api/refunds"):
        assert proxied[prefix] is True


def test_contract_alignment_blocks_unknown_backend():
    result = preflight.probe_contract_alignment(payment_backend="rust")
    assert result.ok is False


def _stubbed_get(monkeypatch, *, status, body):
    def fake_get(url, *, headers=None, timeout=10.0):
        return status, body, ""

    monkeypatch.setattr(preflight, "_http_get", fake_get)


def test_actuator_health_passes_when_status_up(monkeypatch):
    _stubbed_get(monkeypatch, status=200, body={"status": "UP"})
    result = preflight.probe_actuator_health("http://java")
    assert result.ok is True


def test_actuator_health_fails_when_down(monkeypatch):
    _stubbed_get(monkeypatch, status=200, body={"status": "DOWN"})
    result = preflight.probe_actuator_health("http://java")
    assert result.ok is False


def test_actuator_health_handles_network_error(monkeypatch):
    def fake_get(url, *, headers=None, timeout=10.0):
        return None, None, "ConnectionError: refused"

    monkeypatch.setattr(preflight, "_http_get", fake_get)
    result = preflight.probe_actuator_health("http://java")
    assert result.ok is False
    assert "refused" in result.message


def test_payment_plans_passes_when_plans_returned(monkeypatch):
    _stubbed_get(monkeypatch, status=200, body={"plans": [{"id": "plan_basic"}]})
    result = preflight.probe_payment_plans("http://java")
    assert result.ok is True
    assert result.detail["plan_count"] == 1


def test_payment_plans_fails_on_unexpected_payload(monkeypatch):
    _stubbed_get(monkeypatch, status=500, body="Internal Server Error")
    result = preflight.probe_payment_plans("http://java")
    assert result.ok is False


def test_payment_diagnostics_requires_alipay_configured(monkeypatch):
    _stubbed_get(monkeypatch, status=200, body={"ok": True, "alipay_configured": True})
    result = preflight.probe_payment_diagnostics("http://java", admin_token="x")
    assert result.ok is True

    _stubbed_get(monkeypatch, status=200, body={"ok": True, "alipay_configured": False})
    result = preflight.probe_payment_diagnostics("http://java", admin_token="x")
    assert result.ok is False


def test_format_report_aggregates_failures():
    pass_probe = preflight.ProbeResult(name="a", ok=True)
    fail_probe = preflight.ProbeResult(name="b", ok=False, message="boom")
    report = preflight.format_report([pass_probe, fail_probe])
    assert report["ok"] is False
    assert report["total"] == 2
    assert report["passed"] == 1
    assert len(report["failed"]) == 1
    assert report["failed"][0]["name"] == "b"


def test_run_probes_skips_diagnostics_without_token(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "probe_actuator_health",
        lambda url: preflight.ProbeResult(name="actuator_health", ok=True),
    )
    monkeypatch.setattr(
        preflight,
        "probe_payment_plans",
        lambda url: preflight.ProbeResult(name="payment_plans", ok=True),
    )
    monkeypatch.setattr(
        preflight,
        "probe_payment_diagnostics",
        lambda url, token: pytest.fail("should not be called without admin token"),
    )

    results = preflight.run_probes(
        base_url="http://java", admin_token="", payment_backend="java", java_url="http://java"
    )
    assert {r.name for r in results} == {"contract_match", "actuator_health", "payment_plans"}


def test_run_probes_runs_diagnostics_with_token(monkeypatch):
    called = {}

    def fake_diag(url, token):
        called["token"] = token
        return preflight.ProbeResult(name="payment_diagnostics", ok=True)

    monkeypatch.setattr(
        preflight,
        "probe_actuator_health",
        lambda url: preflight.ProbeResult(name="actuator_health", ok=True),
    )
    monkeypatch.setattr(
        preflight,
        "probe_payment_plans",
        lambda url: preflight.ProbeResult(name="payment_plans", ok=True),
    )
    monkeypatch.setattr(preflight, "probe_payment_diagnostics", fake_diag)

    results = preflight.run_probes(
        base_url="http://java", admin_token="abc", payment_backend="java", java_url="http://java"
    )
    assert called["token"] == "abc"
    assert any(r.name == "payment_diagnostics" for r in results)


def test_main_exits_non_zero_on_failure(capsys, monkeypatch):
    monkeypatch.setattr(
        preflight,
        "run_probes",
        lambda **kwargs: [preflight.ProbeResult(name="x", ok=False, message="bad")],
    )
    code = preflight.main(["--base-url", "http://java", "--json"])
    captured = capsys.readouterr()
    assert code == 1
    assert '"ok": false' in captured.out


def test_main_exits_zero_on_success(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "run_probes",
        lambda **kwargs: [preflight.ProbeResult(name="x", ok=True)],
    )
    code = preflight.main(["--base-url", "http://java", "--json"])
    assert code == 0


def test_env_example_documents_payment_backend_toggle():
    env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "PAYMENT_BACKEND=" in env
    assert "JAVA_PAYMENT_SERVICE_URL" in env
