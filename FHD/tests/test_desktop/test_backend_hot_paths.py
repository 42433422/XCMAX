from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pytest

from app.desktop_runtime import desktop_runtime_paths, migrate
from app.mod_sdk import neuro_bus_compat
from app.utils.http_tls import shared_ssl_context


def test_desktop_dirs_are_created_once_then_reused(tmp_path, monkeypatch) -> None:
    first = desktop_runtime_paths.ensure_desktop_dirs(tmp_path)
    assert all(path.is_dir() for path in first.values())

    calls: list[Path] = []
    original = Path.mkdir

    def counting_mkdir(self: Path, *args, **kwargs) -> None:
        calls.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting_mkdir)
    assert desktop_runtime_paths.ensure_desktop_dirs(tmp_path) == first
    assert desktop_runtime_paths.sqlite_database_url(tmp_path).endswith("/data/xcagi.db")
    assert calls == []


def test_desktop_dirs_are_recreated_when_the_data_dir_disappears(tmp_path) -> None:
    dirs = desktop_runtime_paths.ensure_desktop_dirs(tmp_path)
    shutil.rmtree(dirs["data"])
    assert desktop_runtime_paths.ensure_desktop_dirs(tmp_path)["data"].is_dir()


def test_neuro_bus_installed_check_does_not_rebuild_the_mod_catalog(tmp_path, monkeypatch) -> None:
    from app.infrastructure.mods import mod_manager

    class _Manager:
        def list_all_mods(self):
            raise AssertionError("full Mod catalog rebuilt on a hot path")

    monkeypatch.setattr(mod_manager, "get_mod_manager", lambda: _Manager())
    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: False)
    monkeypatch.setattr(neuro_bus_compat, "_resolve_mod_dir", lambda: tmp_path)
    assert neuro_bus_compat.is_neuro_bus_mod_installed() is True

    monkeypatch.setattr(neuro_bus_compat, "_resolve_mod_dir", lambda: None)
    assert neuro_bus_compat.is_neuro_bus_mod_installed() is False


def test_neuro_bus_installed_check_honours_disabled_mods(tmp_path, monkeypatch) -> None:
    from app.infrastructure.mods import mod_manager

    monkeypatch.setattr(mod_manager, "is_mods_disabled", lambda: True)
    monkeypatch.setattr(neuro_bus_compat, "_resolve_mod_dir", lambda: tmp_path)
    assert neuro_bus_compat.is_neuro_bus_mod_installed() is False


def test_tls_context_is_built_once_per_trust_mode() -> None:
    assert shared_ssl_context() is shared_ssl_context()
    assert shared_ssl_context(trust_env=False) is shared_ssl_context(trust_env=False)


@pytest.mark.parametrize("existing", [1, 2])
def test_corrupt_db_rename_keeps_evidence_within_the_same_second(
    tmp_path, monkeypatch, existing: int
) -> None:
    db = desktop_runtime_paths.ensure_desktop_dirs(tmp_path)["data"] / "xcagi.db"
    db.write_bytes(b"corrupt database")
    monkeypatch.setattr(migrate, "utc_now_naive", lambda: datetime(2026, 11, 4, 12, 0, 0))
    monkeypatch.setattr(migrate, "_quick_check_ok", lambda path: False)
    earlier = [db.with_name("xcagi.db.corrupt-20261104120000")]
    earlier += [db.with_name(f"xcagi.db.corrupt-20261104120000-{n}") for n in range(1, existing)]
    for path in earlier:
        path.write_bytes(b"earlier evidence")

    result = migrate.recover_if_corrupt(tmp_path)

    assert "rename failed" not in result.get("detail", "")
    assert all(path.read_bytes() == b"earlier evidence" for path in earlier)
    assert db.with_name(f"xcagi.db.corrupt-20261104120000-{existing}").read_bytes() == (
        b"corrupt database"
    )
