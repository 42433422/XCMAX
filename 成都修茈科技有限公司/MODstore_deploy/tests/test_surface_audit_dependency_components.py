"""Dependency preparation reports actual readiness and preserves the persistent API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from modstore_server import surface_audit_deps as deps


def test_playwright_install_nonzero_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_AUTO_START", "1")
    monkeypatch.setitem(
        sys.modules, "playwright.async_api", SimpleNamespace(async_playwright=object())
    )
    monkeypatch.setattr(deps, "_python_bin", lambda: "synthetic-python")
    calls = []

    def failed_install(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 7, b"", b"synthetic browser download failed")

    monkeypatch.setattr(deps.subprocess, "run", failed_install)
    result = deps._ensure_playwright()

    assert result["ok"] is False
    assert "synthetic browser download failed" in result["error"]
    assert calls[0][0] == ["synthetic-python", "-m", "playwright", "install", "chromium"]
    assert calls[0][1]["timeout"] == 300


def test_auto_start_disabled_does_not_claim_unavailable_services_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_AUTO_START", "0")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_PS_BASE_URL", "http://127.0.0.1:59991")
    monkeypatch.setenv("MODSTORE_INTERNAL_API_BASE", "http://127.0.0.1:59992")
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL", "https://example.invalid")

    def unavailable(*args):
        return {"ok": False, "skipped": True, "reason": "auto_start_disabled"}

    monkeypatch.setattr(deps, "_ensure_playwright", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(deps, "_ensure_android_emulator", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(deps, "_ensure_fhd_api", unavailable)
    monkeypatch.setattr(deps, "_ensure_vite", unavailable)
    monkeypatch.setattr(deps, "_ensure_modstore_api", unavailable)

    result = deps.ensure_surface_audit_deps()

    assert result["ok"] is False
    assert set(result["failures"]) == {
        "fhd_api:not_ready",
        "vite_ps:not_ready",
        "modstore_api:not_ready",
    }


def test_ephemeral_cleanup_keeps_modstore_api_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    temporary = tmp_path / "surface-audit-fhd-api.pid"
    persistent = tmp_path / "surface-audit-modstore.pid"
    temporary.write_text("999998", encoding="utf-8")
    persistent.write_text("999999", encoding="utf-8")
    killed = []
    monkeypatch.setattr(deps, "_pids_dir", lambda: tmp_path)
    monkeypatch.setattr(deps, "_fhd_root", lambda: tmp_path)
    monkeypatch.setattr(deps.os, "kill", lambda pid, signal: killed.append((pid, signal)))
    monkeypatch.setattr(deps.time, "sleep", lambda delay: None)

    result = deps.stop_surface_audit_ephemeral()

    assert result == {"ok": True, "stopped": ["surface-audit-fhd-api"]}
    assert (999998, 15) in killed
    assert not any(pid == 999999 for pid, _ in killed)
    assert persistent.read_text(encoding="utf-8") == "999999"
    assert not temporary.exists()


@pytest.mark.parametrize("pid", ["0", "-1", "1"])
def test_invalid_pid_file_cannot_signal_a_process_group_or_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pid: str
) -> None:
    pid_file = tmp_path / "surface-audit-fhd-api.pid"
    pid_file.write_text(pid, encoding="utf-8")
    signals = []
    monkeypatch.setattr(deps.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(deps.time, "sleep", lambda delay: None)

    deps._kill_pid_file("fhd-api", pid_file)

    assert signals == []
    assert not pid_file.exists()


@pytest.mark.parametrize("resolver", ["_pids_dir", "_logs_dir"])
def test_audit_runtime_defaults_outside_source_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, resolver: str
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "FHD").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setenv("XCMAX_MONOREPO_ROOT", str(checkout))
    for key in (
        "MODSTORE_SURFACE_AUDIT_PIDS_DIR",
        "MODSTORE_SURFACE_AUDIT_LOG_DIR",
        "MODSTORE_RUNTIME_STATE_ROOT",
        "MODSTORE_RUNTIME_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    assert not getattr(deps, resolver)().is_relative_to(checkout)


@pytest.mark.parametrize(
    ("resolver", "override"),
    [
        ("_pids_dir", "MODSTORE_SURFACE_AUDIT_PIDS_DIR"),
        ("_logs_dir", "MODSTORE_SURFACE_AUDIT_LOG_DIR"),
    ],
)
def test_configured_audit_runtime_rejects_checkout_and_accepts_external_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, resolver: str, override: str
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    destination = checkout / "runtime"
    monkeypatch.setenv(override, str(destination))

    with pytest.raises(ValueError, match="outside a Git checkout"):
        getattr(deps, resolver)()
    assert not destination.exists()

    external = tmp_path / "external-runtime"
    monkeypatch.setenv(override, str(external))
    assert getattr(deps, resolver)() == external.resolve()
    assert external.is_dir()
