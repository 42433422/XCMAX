from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path
from unittest.mock import patch

from app.desktop_runtime import version as runtime_version
from app.desktop_runtime.backup_scheduler import _run_once
from app.desktop_runtime.migrate import backup_database


def test_runtime_version_prefers_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_VERSION", "9.9.9")

    assert runtime_version.resolve_runtime_version("v10.0.0") == "10.0.0"


def test_runtime_version_fallback_tracks_product_version() -> None:
    root = Path(__file__).resolve().parents[1]
    product = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert product["project"]["version"] == runtime_version._DEFAULT_PRODUCT_VERSION


def test_runtime_version_reads_packaged_build_info_without_environment(
    tmp_path, monkeypatch
) -> None:
    resources = tmp_path / "resources"
    backend = resources / "backend"
    backend.mkdir(parents=True)
    executable = backend / "xcagi-backend.exe"
    executable.touch()
    build_info = resources / "build-info.json"
    build_info.write_text(json.dumps({"version": "10.0.0"}), encoding="utf-8")
    monkeypatch.delenv("XCAGI_VERSION", raising=False)
    monkeypatch.delenv("XCAGI_BUILD_INFO_FILE", raising=False)
    monkeypatch.setattr(runtime_version.sys, "executable", str(executable))
    monkeypatch.delattr(runtime_version.sys, "_MEIPASS", raising=False)

    assert runtime_version.resolve_runtime_version() == "10.0.0"


def test_runtime_version_ignores_unknown_and_unsafe_values(tmp_path, monkeypatch) -> None:
    unsafe = tmp_path / "build-info.json"
    unsafe.write_text(json.dumps({"version": "../../escape"}), encoding="utf-8")
    monkeypatch.setenv("XCAGI_VERSION", "unknown")
    monkeypatch.setattr(runtime_version, "_build_info_candidates", lambda: [unsafe])
    monkeypatch.setattr(runtime_version.metadata, "version", lambda _name: "10.0.0")

    assert runtime_version.resolve_runtime_version() == "10.0.0"


def test_default_backup_filename_uses_packaged_runtime_version(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    database = data_dir / "xcagi.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE release_probe (id INTEGER PRIMARY KEY)")

    build_info = tmp_path / "build-info.json"
    build_info.write_text(json.dumps({"version": "10.0.0"}), encoding="utf-8")
    monkeypatch.delenv("XCAGI_VERSION", raising=False)
    monkeypatch.setattr(runtime_version, "_build_info_candidates", lambda: [build_info])

    result = backup_database(tmp_path)

    assert result is not None
    assert result.name.startswith("xcagi-10.0.0-")
    assert "unknown" not in result.name


def test_scheduler_passes_resolved_runtime_version_to_backup(tmp_path) -> None:
    backup_file = tmp_path / "backups" / "xcagi-10.0.0-20260710120000.db"
    backup_file.parent.mkdir()
    backup_file.touch()

    with (
        patch(
            "app.desktop_runtime.backup_scheduler.ensure_desktop_dirs",
            return_value={"backups": backup_file.parent},
        ),
        patch("app.desktop_runtime.backup_scheduler._has_backup_today", return_value=False),
        patch(
            "app.desktop_runtime.backup_scheduler.resolve_runtime_version",
            return_value="10.0.0",
        ),
        patch(
            "app.desktop_runtime.backup_scheduler.backup_database",
            return_value=backup_file,
        ) as backup,
        patch("app.desktop_runtime.backup_scheduler._sync_to_external"),
        patch("app.desktop_runtime.backup_scheduler._cleanup_old_backups"),
        patch("app.desktop_runtime.backup_scheduler.datetime") as current_time,
    ):
        current_time.now.return_value.weekday.return_value = 0
        _run_once(tmp_path)

    backup.assert_called_once_with(tmp_path, version="10.0.0")


def test_windows_build_embeds_same_build_identity_in_backend() -> None:
    root = Path(__file__).resolve().parents[1]
    backend_script = (root / "scripts" / "package" / "build-backend.ps1").read_text(
        encoding="utf-8"
    )
    installer_script = (root / "scripts" / "package" / "build-installer.ps1").read_text(
        encoding="utf-8"
    )

    assert "dist\\xcagi-backend\\_internal\\build-info.json" in backend_script
    assert "version = $Version" in backend_script
    assert (
        "[System.IO.File]::Copy($buildInfoPath, $backendBuildInfoPath, $true)" in installer_script
    )
