from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _desktop_runtime_source(*names: str) -> str:
    return "\n".join((ROOT / "desktop" / name).read_text(encoding="utf-8") for name in names)


def test_windows_uninstall_preserves_user_data_and_cleans_scheduled_task() -> None:
    builder = (ROOT / "desktop/electron-builder.yml").read_text(encoding="utf-8")
    installer = (ROOT / "desktop/build/installer.nsh").read_text(encoding="utf-8")
    assert "deleteAppDataOnUninstall: false" in builder
    assert "uninstallDisplayName: XCAGI 桌面版" in builder
    assert "!macro customUnInstall" in installer
    assert "Uninstall-BackupTask.ps1" in installer


def test_release_contains_upgrade_rollback_crash_and_window_recovery() -> None:
    builder = (ROOT / "desktop/electron-builder.yml").read_text(encoding="utf-8")
    runtime = _desktop_runtime_source("main.ts", "window-manager.ts")
    resilience = (ROOT / "desktop/desktop-resilience.ts").read_text(encoding="utf-8")
    assert "- zip" in builder, "electron-updater requires a ZIP artifact on macOS"
    assert "checkPendingRollback" in runtime and "triggerRollbackSafe" in runtime
    assert "render-process-gone" in runtime
    assert "initializeLocalCrashReporting" in runtime
    assert "crashReporter.start" in resilience
    assert "readWindowState" in runtime and "writeWindowState" in runtime


def test_soak_gate_defaults_to_at_least_eight_hours_and_fails_closed() -> None:
    soak = (ROOT / "scripts/release/desktop-soak.sh").read_text(encoding="utf-8")
    assert "XCAGI_SOAK_DURATION_SECONDS:-28800" in soak
    assert "MAX_CONSECUTIVE_FAILURES" in soak
    assert "exit 1" in soak
