from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from XCAGI import run_fastapi


def test_ledger_handoff_does_not_start_or_migrate_the_backend(monkeypatch, tmp_path):
    from app.infrastructure.billing import model_usage_export

    export = Mock(return_value=0)
    monkeypatch.setattr(model_usage_export, "main", export)
    bootstrap = Mock(side_effect=AssertionError("handoff must not bootstrap the application"))
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", bootstrap)
    ledger = tmp_path / "ledger with spaces.json"
    run_fastapi.main(["--desktop", "--export-model-usage-ledger", str(ledger)])
    export.assert_called_once_with(["--ledger", str(ledger), "--output", str(ledger), "--handoff"])
    bootstrap.assert_not_called()


def test_ledger_handoff_propagates_failure(monkeypatch, tmp_path):
    from app.infrastructure.billing import model_usage_export

    monkeypatch.setattr(model_usage_export, "main", Mock(side_effect=RuntimeError("pending debit")))
    with pytest.raises(RuntimeError, match="pending debit"):
        run_fastapi.main(["--export-model-usage-ledger", str(tmp_path / "ledger.json")])


def test_real_desktop_entry_exports_current_wallet_before_retiring_sqlite(monkeypatch, tmp_path):
    from app.infrastructure.billing import model_usage

    ledger = tmp_path / "ledger with spaces.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(ledger))
    model_usage.set_model_wallet_balance("synthetic-user", 42)
    result = subprocess.run(
        [
            sys.executable,
            str(Path(run_fastapi.__file__)),
            "--export-model-usage-ledger",
            str(ledger),
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert f"XCAGI_MODEL_USAGE_HANDOFF={ledger}" in result.stdout
    assert json.loads(ledger.read_text())["wallets"]["synthetic-user"]["balance_units"] == 42
    assert not Path(f"{ledger}.sqlite3").exists()
    assert list(tmp_path.glob("ledger with spaces.json.rollback-*.sqlite3"))


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

    import app.desktop_runtime.desktop_runtime_paths as desktop_paths
    from app.desktop_runtime import migrate

    # run_fastapi imports configure/ensure from desktop_runtime_paths (not paths).
    monkeypatch.setattr(desktop_paths, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(
        desktop_paths,
        "ensure_desktop_dirs",
        lambda _path: {"data": database.parent, "backups": database.parent.parent / "backups"},
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

    import app.desktop_runtime.desktop_runtime_paths as desktop_paths
    from app.desktop_runtime import migrate

    monkeypatch.setattr(desktop_paths, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(
        desktop_paths,
        "ensure_desktop_dirs",
        lambda _path: {"data": database.parent, "backups": backup.parent},
    )
    monkeypatch.setattr(migrate, "backup_database", lambda *_args, **_kwargs: backup)
    upgrade = Mock()
    monkeypatch.setattr(migrate, "run_alembic_upgrade", upgrade)

    run_fastapi.main(["--migrate-only", "--backup", "--data-dir", str(data_dir)])

    assert f"XCAGI_MIGRATION_BACKUP={backup}" in capsys.readouterr().out
    upgrade.assert_called_once_with(str(data_dir))


@pytest.mark.parametrize("kind", ["valid", "corrupt", "missing", "empty"])
def test_backup_verification_is_read_only_without_bootstrap(monkeypatch, tmp_path, kind):
    backup = tmp_path / "backup space.db"
    if kind == "valid":
        with sqlite3.connect(backup) as db:
            db.execute("CREATE TABLE evidence (id INTEGER)")
    elif kind != "missing":
        backup.write_bytes(bytes(2048) if kind == "corrupt" else b"")
    before = backup.read_bytes() if backup.exists() else None
    bootstrap = Mock(side_effect=AssertionError("verification must not bootstrap"))
    monkeypatch.setattr(run_fastapi, "_apply_desktop_bootstrap", bootstrap)
    if kind == "valid":
        run_fastapi.main(["--verify-backup", str(backup)])
    else:
        with pytest.raises(SystemExit) as error:
            run_fastapi.main(["--verify-backup", str(backup)])
        assert error.value.code == 1
    assert (backup.read_bytes() if backup.exists() else None) == before
    bootstrap.assert_not_called()
