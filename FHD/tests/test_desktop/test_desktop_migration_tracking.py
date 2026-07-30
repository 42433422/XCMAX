from __future__ import annotations

from pathlib import Path
from unittest.mock import call

from app.desktop_runtime import migrate


def test_unversioned_desktop_database_is_rebased_then_upgraded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(migrate, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(migrate, "_should_bootstrap_sqlite", lambda _path: False)
    monkeypatch.setattr(migrate, "_sqlite_current_revisions", lambda _path: None)
    monkeypatch.setattr(
        migrate,
        "_script_revisions",
        lambda: ({"2026_06_22_baseline", "head"}, {"head"}),
    )
    calls = []
    monkeypatch.setattr(migrate, "_run_alembic_cli", lambda *args: calls.append(call(*args)))

    migrate.run_alembic_upgrade(tmp_path)

    assert calls == [
        call("stamp", "--purge", "2026_06_22_baseline"),
        call("upgrade", "head"),
    ]


def test_current_desktop_database_does_not_require_migration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(migrate, "configure_desktop_environment", lambda _path: None)
    monkeypatch.setattr(migrate, "_should_bootstrap_sqlite", lambda _path: False)
    monkeypatch.setattr(migrate, "_sqlite_current_revisions", lambda _path: {"bundled-head"})
    monkeypatch.setattr(
        migrate,
        "_script_revisions",
        lambda: ({"baseline", "bundled-head"}, {"bundled-head"}),
    )

    assert migrate.migration_required(tmp_path) is False
