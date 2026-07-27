from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from XCAGI import run_fastapi


def _patch_desktop_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_fastapi, "_load_dotenv_if_present", lambda _path: None)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", lambda _args: None)
    monkeypatch.setattr(run_fastapi, "_apply_desktop_local_market_env", lambda: None)
    monkeypatch.setattr(run_fastapi, "_ensure_sys_path", lambda: None)


def test_migrate_only_refuses_to_continue_when_existing_database_backup_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_desktop_bootstrap(monkeypatch)
    data_dir = tmp_path / "data-root"
    database = data_dir / "data" / "xcagi.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"sqlite")

    from app.desktop_runtime import migrate, paths

    monkeypatch.setattr(paths, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(
        paths,
        "ensure_desktop_dirs",
        lambda _path: {"data": database.parent},
    )
    monkeypatch.setattr(migrate, "backup_database", lambda *_args, **_kwargs: None)
    upgrade = Mock()
    monkeypatch.setattr(migrate, "run_alembic_upgrade", upgrade)

    with pytest.raises(RuntimeError, match="migration backup failed"):
        run_fastapi.main(["--migrate-only", "--backup", "--data-dir", str(data_dir)])
    upgrade.assert_not_called()


def test_migrate_only_emits_machine_readable_backup_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_desktop_bootstrap(monkeypatch)
    data_dir = tmp_path / "data-root"
    database = data_dir / "data" / "xcagi.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"sqlite")
    backup = data_dir / "backups" / "xcagi-before-update.db"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"backup")

    from app.desktop_runtime import migrate, paths

    monkeypatch.setattr(paths, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(
        paths,
        "ensure_desktop_dirs",
        lambda _path: {"data": database.parent},
    )
    monkeypatch.setattr(migrate, "backup_database", lambda *_args, **_kwargs: backup)
    upgrade = Mock()
    monkeypatch.setattr(migrate, "run_alembic_upgrade", upgrade)

    run_fastapi.main(["--migrate-only", "--backup", "--data-dir", str(data_dir)])

    assert f"XCAGI_MIGRATION_BACKUP={backup}" in capsys.readouterr().out
    upgrade.assert_called_once_with(str(data_dir))


def test_migrate_if_needed_skips_backup_when_schema_is_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_desktop_bootstrap(monkeypatch)
    data_dir = tmp_path / "data-root"

    from app.desktop_runtime import migrate, paths

    monkeypatch.setattr(paths, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(migrate, "migration_required", lambda _path: False)
    backup = Mock()
    upgrade = Mock()
    monkeypatch.setattr(migrate, "backup_database", backup)
    monkeypatch.setattr(migrate, "run_alembic_upgrade", upgrade)

    run_fastapi.main(["--migrate-only", "--backup", "--if-needed", "--data-dir", str(data_dir)])

    assert "XCAGI_MIGRATION_STATUS=current" in capsys.readouterr().out
    backup.assert_not_called()
    upgrade.assert_not_called()
