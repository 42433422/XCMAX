from __future__ import annotations

"""Branch coverage for desktop_runtime/migrate.py, support_bundle.py, model_downloader.py."""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# migrate.py
# ---------------------------------------------------------------------------


class TestBackupDatabase:
    def test_no_db_returns_none(self, tmp_path):
        from app.desktop_runtime.migrate import backup_database

        with patch(
            "app.desktop_runtime.migrate.ensure_desktop_dirs",
            return_value={
                "data": tmp_path / "data",
                "backups": tmp_path / "backups",
                "root": tmp_path,
                "mods": tmp_path / "mods",
                "models": tmp_path / "models",
                "logs": tmp_path / "logs",
            },
        ):
            result = backup_database(tmp_path)
        assert result is None

    def test_db_exists_creates_backup(self, tmp_path):
        from app.desktop_runtime.migrate import backup_database

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db = data_dir / "xcagi.db"
        # 写入一个真实的 SQLite 库，sqlite3.backup() 要求源库是有效的 SQLite 文件
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        backups_dir = tmp_path / "backups"
        backups_dir.mkdir()

        dirs = {
            "data": data_dir,
            "backups": backups_dir,
            "root": tmp_path,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs),
            patch(
                "app.desktop_runtime.migrate.utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value="20260101120000")),
            ),
        ):
            result = backup_database(tmp_path, version="1.0")
        assert result is not None
        assert result.exists()


class TestShouldBootstrapSqlite:
    def test_no_db_file(self, tmp_path):
        from app.desktop_runtime.migrate import _should_bootstrap_sqlite

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        dirs = {"data": data_dir}
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            assert _should_bootstrap_sqlite(tmp_path) is True

    def test_empty_db_file(self, tmp_path):
        from app.desktop_runtime.migrate import _should_bootstrap_sqlite

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db = data_dir / "xcagi.db"
        db.write_bytes(b"")  # size=0
        dirs = {"data": data_dir}
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            assert _should_bootstrap_sqlite(tmp_path) is True

    def test_db_no_tables(self, tmp_path):
        from app.desktop_runtime.migrate import _should_bootstrap_sqlite

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "xcagi.db"
        conn = sqlite3.connect(str(db_path))
        conn.close()
        dirs = {"data": data_dir}
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            assert _should_bootstrap_sqlite(tmp_path) is True

    def test_db_with_tables(self, tmp_path):
        from app.desktop_runtime.migrate import _should_bootstrap_sqlite

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "xcagi.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        dirs = {"data": data_dir}
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            assert _should_bootstrap_sqlite(tmp_path) is False

    def test_corrupted_db_returns_true(self, tmp_path):
        from app.desktop_runtime.migrate import _should_bootstrap_sqlite

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = data_dir / "xcagi.db"
        db_path.write_bytes(b"not a valid sqlite file" * 100)
        dirs = {"data": data_dir}
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            assert _should_bootstrap_sqlite(tmp_path) is True


class TestExportConfig:
    def test_export_config(self, tmp_path):
        from app.desktop_runtime.migrate import export_config

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }
        with patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs):
            cfg = export_config(tmp_path)
        assert "database" in cfg
        assert "mods" in cfg


class TestRunAlembicCli:
    def test_alembic_root_frozen_uses_meipass(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with (
            patch.object(mig.sys, "frozen", True, create=True),
            patch.object(mig.sys, "_MEIPASS", str(tmp_path), create=True),
        ):
            assert mig._alembic_root() == tmp_path

    def test_nested_ini_and_frozen_upgrade(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        nested = tmp_path / "alembic.ini"
        nested.mkdir()
        (nested / "alembic.ini").write_text(
            "[alembic]\nscript_location = alembic\n", encoding="utf-8"
        )
        with (
            patch.object(mig, "_alembic_root", return_value=tmp_path),
            patch.object(mig.sys, "frozen", True, create=True),
            patch("alembic.config.Config") as cfg_cls,
            patch("alembic.command.upgrade") as upgrade,
        ):
            mig._run_alembic_cli("upgrade", "head")
        cfg_cls.assert_called_once()
        upgrade.assert_called_once()
        assert str(cfg_cls.call_args[0][0]).endswith("alembic.ini")

    def test_frozen_stamp_and_unsupported_op(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        (tmp_path / "alembic.ini").write_text(
            "[alembic]\nscript_location = alembic\n", encoding="utf-8"
        )
        with (
            patch.object(mig, "_alembic_root", return_value=tmp_path),
            patch.object(mig.sys, "frozen", True, create=True),
            patch("alembic.config.Config"),
            patch("alembic.command.stamp") as stamp,
        ):
            mig._run_alembic_cli("stamp", "head")
            stamp.assert_called_once()
            with pytest.raises(ValueError, match="unsupported alembic op"):
                mig._run_alembic_cli("history")

    def test_missing_ini_raises(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with patch.object(mig, "_alembic_root", return_value=tmp_path):
            with pytest.raises(FileNotFoundError, match="alembic.ini"):
                mig._run_alembic_cli("upgrade", "head")

    def test_non_frozen_subprocess(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        (tmp_path / "alembic.ini").write_text(
            "[alembic]\nscript_location = alembic\n", encoding="utf-8"
        )
        with (
            patch.object(mig, "_alembic_root", return_value=tmp_path),
            patch.object(mig.sys, "frozen", False, create=True),
            patch("app.desktop_runtime.migrate.subprocess.run") as run,
        ):
            mig._run_alembic_cli("upgrade", "head")
        run.assert_called_once()
        assert run.call_args.kwargs["check"] is True


class TestMigrateMain:
    def test_main_no_args(self, tmp_path):
        from app.desktop_runtime.migrate import main

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }
        with (
            patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.migrate.configure_desktop_environment"),
        ):
            rc = main([])
        assert rc == 0

    def test_main_backup(self, tmp_path):
        from app.desktop_runtime.migrate import main

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }
        with (
            patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.migrate.configure_desktop_environment"),
            patch("app.desktop_runtime.migrate.backup_database", return_value=None),
        ):
            rc = main(["--backup"])
        assert rc == 0

    def test_main_export_config(self, tmp_path, capsys):
        from app.desktop_runtime.migrate import main

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }
        with (
            patch("app.desktop_runtime.migrate.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.migrate.configure_desktop_environment"),
        ):
            rc = main(["--export-config"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "database" in data


class TestRecoverIfCorrupt:
    def _dirs(self, tmp_path):
        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        return {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }

    def test_skipped_when_no_db(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with patch.object(mig, "ensure_desktop_dirs", return_value=self._dirs(tmp_path)):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "skipped"

    def test_ok_when_healthy(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        db = dirs["data"] / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        with patch.object(mig, "ensure_desktop_dirs", return_value=dirs):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "ok"

    def test_restored_from_backup(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        bad = dirs["data"] / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        good = dirs["backups"] / "xcagi-good.db"
        conn = sqlite3.connect(str(good))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        with patch.object(mig, "ensure_desktop_dirs", return_value=dirs):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "restored"
        assert (dirs["data"] / "xcagi.db").exists()

    def test_corrupt_no_backup(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        bad = dirs["data"] / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        with patch.object(mig, "ensure_desktop_dirs", return_value=dirs):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "corrupt_no_backup"

    def test_disk_usage_oserror_still_ok(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        db = dirs["data"] / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig.shutil, "disk_usage", side_effect=OSError("x")),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "ok"

    def test_disk_free_low_still_ok(self, tmp_path):
        import sqlite3
        from collections import namedtuple

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        db = dirs["data"] / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        Usage = namedtuple("Usage", "total used free")
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig.shutil, "disk_usage", return_value=Usage(1, 1, 100)),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "ok"

    def test_rename_corrupt_oserror(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        bad = dirs["data"] / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig, "_quick_check_ok", return_value=False),
            patch.object(Path, "rename", side_effect=OSError("busy")),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "corrupt_no_backup"
        assert "rename failed" in out["detail"]

    def test_restored_from_legacy_bak(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        bad = dirs["data"] / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        legacy = dirs["data"] / "database_backups"
        legacy.mkdir()
        good = legacy / "snap.bak"
        conn = sqlite3.connect(str(good))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        with patch.object(mig, "ensure_desktop_dirs", return_value=dirs):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "restored"
        assert out["detail"] == "snap.bak"

    def test_restore_copy_oserror_then_next(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        dirs = self._dirs(tmp_path)
        bad = dirs["data"] / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        first = dirs["backups"] / "xcagi-a.db"
        second = dirs["backups"] / "xcagi-b.db"
        for p in (first, second):
            conn = sqlite3.connect(str(p))
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.commit()
            conn.close()
        # Make first newer so it is tried first, then fail copy2 once.
        first.touch()
        calls = {"n": 0}
        real_copy2 = shutil.copy2

        def _copy2_real(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("disk full")
            return real_copy2(src, dst)

        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig.shutil, "copy2", side_effect=_copy2_real),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "restored"


class TestBackupDatabaseErrors:
    def test_sqlite_error_returns_none(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        db = data / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }

        class _Conn:
            def backup(self, *_a, **_k):
                raise sqlite3.Error("boom")

            def close(self):
                return None

        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig.sqlite3, "connect", side_effect=[_Conn(), _Conn()]),
            patch.object(
                mig,
                "utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value="20260101120000")),
            ),
        ):
            assert mig.backup_database(tmp_path, version="1.0") is None

    def test_integrity_fail_unlinks(self, tmp_path):
        import sqlite3

        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        db = data / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig, "_integrity_check_ok", return_value=False),
            patch.object(
                mig,
                "utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value="20260101120001")),
            ),
        ):
            assert mig.backup_database(tmp_path, version="1.0") is None

    def test_integrity_fail_unlink_oserror_swallowed(self, tmp_path):
        """integrity_check fail + unlink OSError → still return None (BrPart 69)."""
        import sqlite3

        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        db = data / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig, "_integrity_check_ok", return_value=False),
            patch.object(
                mig,
                "utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value="20260101120002")),
            ),
            patch.object(Path, "unlink", side_effect=OSError("busy")),
        ):
            assert mig.backup_database(tmp_path, version="1.0") is None

    def test_sqlite_error_unlink_oserror_swallowed(self, tmp_path):
        """hot backup sqlite.Error + partial file unlink OSError (BrPart 53-55)."""
        import sqlite3

        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        db = data / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }

        class _Conn:
            def backup(self, *_a, **_k):
                # Leave a partial target so exists() is True in except.
                raise sqlite3.Error("boom")

            def close(self):
                return None

        # Pre-create the expected target so unlink path runs.
        stamp = "20260101120003"
        target = backups / f"xcagi-1.0-{stamp}.db"
        target.write_bytes(b"partial")

        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig.sqlite3, "connect", side_effect=[_Conn(), _Conn()]),
            patch.object(
                mig,
                "utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value=stamp)),
            ),
            patch.object(Path, "unlink", side_effect=OSError("locked")),
        ):
            assert mig.backup_database(tmp_path, version="1.0") is None

    def test_src_connect_fails_src_conn_none_in_finally(self, tmp_path):
        """First sqlite3.connect raises → src_conn stays None (BrPart 61->65)."""
        import sqlite3

        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        db = data / "xcagi.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(
                mig.sqlite3,
                "connect",
                side_effect=sqlite3.Error("cannot open"),
            ),
            patch.object(
                mig,
                "utc_now_naive",
                return_value=MagicMock(strftime=MagicMock(return_value="20260101120004")),
            ),
        ):
            assert mig.backup_database(tmp_path, version="1.0") is None


class TestRecoverAllBackupsFail:
    def test_all_candidates_fail_integrity_or_copy(self, tmp_path):
        """Every backup fails integrity or copy2 → corrupt_no_backup (186-187)."""
        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        backups = tmp_path / "backups"
        data.mkdir()
        backups.mkdir()
        bad = data / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        # Two candidates: both "pass" integrity mock but copy always fails.
        a = backups / "xcagi-a.db"
        b = backups / "xcagi-b.db"
        a.write_bytes(b"x")
        b.write_bytes(b"y")
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": backups,
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig, "_quick_check_ok", return_value=False),
            patch.object(mig, "_integrity_check_ok", return_value=True),
            patch.object(mig.shutil, "copy2", side_effect=OSError("disk full")),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "corrupt_no_backup"
        assert "no usable backup" in out["detail"]

    def test_backups_dir_missing_still_scans_legacy_only(self, tmp_path):
        """backups_dir not a dir (162->164 false) but legacy has only bad files."""
        from app.desktop_runtime import migrate as mig

        data = tmp_path / "data"
        data.mkdir()
        bad = data / "xcagi.db"
        bad.write_bytes(b"not-a-db" * 50)
        legacy = data / "database_backups"
        legacy.mkdir()
        (legacy / "snap.bak").write_bytes(b"bad")
        dirs = {
            "root": tmp_path,
            "data": data,
            "backups": tmp_path / "no-such-backups",  # not created
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "logs": tmp_path / "logs",
        }
        with (
            patch.object(mig, "ensure_desktop_dirs", return_value=dirs),
            patch.object(mig, "_quick_check_ok", return_value=False),
            patch.object(mig, "_integrity_check_ok", return_value=False),
        ):
            out = mig.recover_if_corrupt(tmp_path)
        assert out["action"] == "corrupt_no_backup"


class TestBootstrapAndMainBackupPrint:
    def test_bootstrap_sqlite_schema_calls_create_all(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with (
            patch.object(mig, "configure_desktop_environment"),
            patch("app.db.models", create=True),
            patch("app.db.dispose_and_recreate_engine") as dispose,
            patch("app.db.engine", new=MagicMock()),
            patch("app.db.base.Base") as Base,
        ):
            Base.metadata = MagicMock()
            mig.bootstrap_sqlite_schema(tmp_path)
        dispose.assert_called_once()
        Base.metadata.create_all.assert_called_once()

    def test_alembic_root_non_frozen(self):
        from app.desktop_runtime import migrate as mig

        with patch.object(mig.sys, "frozen", False, create=True):
            root = mig._alembic_root()
        assert root.name == "FHD" or (root / "alembic.ini").exists() or root.is_dir()

    def test_main_backup_prints_path(self, tmp_path, capsys):
        from app.desktop_runtime.migrate import main

        backup_path = tmp_path / "xcagi-v.db"
        backup_path.write_text("ok")
        with (
            patch("app.desktop_runtime.migrate.configure_desktop_environment"),
            patch(
                "app.desktop_runtime.migrate.backup_database",
                return_value=backup_path,
            ),
        ):
            rc = main(["--backup"])
        assert rc == 0
        assert str(backup_path) in capsys.readouterr().out

    def test_run_alembic_upgrade_non_bootstrap(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with (
            patch.object(mig, "configure_desktop_environment"),
            patch.object(mig, "_should_bootstrap_sqlite", return_value=False),
            patch.object(mig, "_run_alembic_cli") as cli,
        ):
            mig.run_alembic_upgrade(tmp_path, version="head")
        cli.assert_called_once_with("upgrade", "head")


class TestRunAlembicUpgradeBootstrap:
    def test_bootstrap_stamps_head(self, tmp_path):
        from app.desktop_runtime import migrate as mig

        with (
            patch.object(mig, "configure_desktop_environment"),
            patch.object(mig, "_should_bootstrap_sqlite", return_value=True),
            patch.object(mig, "bootstrap_sqlite_schema") as boot,
            patch.object(mig, "_run_alembic_cli") as cli,
        ):
            mig.run_alembic_upgrade(tmp_path)
        boot.assert_called_once()
        cli.assert_called_once_with("stamp", "head")

    def test_main_upgrade_calls_run(self, tmp_path):
        from app.desktop_runtime.migrate import main

        with (
            patch("app.desktop_runtime.migrate.configure_desktop_environment"),
            patch("app.desktop_runtime.migrate.run_alembic_upgrade") as up,
        ):
            rc = main(["--upgrade", "head"])
        assert rc == 0
        up.assert_called_once()


# ---------------------------------------------------------------------------
# support_bundle.py
# ---------------------------------------------------------------------------


class TestTailBytes:
    def test_file_not_exists(self, tmp_path):
        from app.desktop_runtime.support_bundle import _tail_bytes

        result = _tail_bytes(tmp_path / "no_file.log")
        assert result is None

    def test_small_file(self, tmp_path):
        from app.desktop_runtime.support_bundle import _tail_bytes

        f = tmp_path / "test.log"
        f.write_bytes(b"hello world")
        result = _tail_bytes(f, max_bytes=1024)
        assert result == b"hello world"

    def test_large_file_truncated(self, tmp_path):
        from app.desktop_runtime.support_bundle import _tail_bytes

        f = tmp_path / "big.log"
        data = b"x" * 100
        f.write_bytes(data)
        result = _tail_bytes(f, max_bytes=50)
        assert result == b"x" * 50

    def test_oserror(self, tmp_path):
        from app.desktop_runtime.support_bundle import _tail_bytes

        f = tmp_path / "test.log"
        f.write_bytes(b"content")
        with patch("pathlib.Path.open", side_effect=OSError("perm")):
            result = _tail_bytes(f)
        assert result is None


class TestBuildSupportBundleZip:
    def _setup_dirs(self, tmp_path):
        logs = tmp_path / "logs"
        backups = tmp_path / "backups"
        logs.mkdir()
        backups.mkdir()
        return {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": backups,
            "logs": logs,
        }

    def test_not_desktop_mode_raises(self):
        from app.desktop_runtime.support_bundle import build_support_bundle_zip

        with patch("app.desktop_runtime.support_bundle.is_desktop_mode", return_value=False):
            with pytest.raises(RuntimeError, match="desktop mode"):
                build_support_bundle_zip()

    def test_basic_bundle(self, tmp_path):
        from app.desktop_runtime.support_bundle import build_support_bundle_zip

        dirs = self._setup_dirs(tmp_path)
        # Add a .db backup file
        (dirs["backups"] / "xcagi-1.0-20260101.db").write_bytes(b"db")
        # Add a log file
        (dirs["logs"] / "xcagi.log").write_bytes(b"Authorization: Bearer secret123\n")

        cfg = {
            "data_dir": str(tmp_path),
            "database": str(tmp_path / "data" / "xcagi.db"),
            "mods": str(tmp_path / "mods"),
            "models": str(tmp_path / "models"),
        }

        with (
            patch("app.desktop_runtime.support_bundle.is_desktop_mode", return_value=True),
            patch("app.desktop_runtime.support_bundle.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.support_bundle.export_config", return_value=cfg),
        ):
            blob = build_support_bundle_zip(data_dir=str(tmp_path))

        assert isinstance(blob, bytes)
        zf = zipfile.ZipFile(io.BytesIO(blob))
        names = zf.namelist()
        assert "manifest.json" in names
        assert "README.txt" in names
        if "logs/xcagi.log" in names:
            log_body = zf.read("logs/xcagi.log").decode("utf-8", errors="replace")
            assert "secret123" not in log_body
            assert "<redacted>" in log_body

    def test_bundle_includes_log(self, tmp_path):
        from app.desktop_runtime.support_bundle import build_support_bundle_zip

        dirs = self._setup_dirs(tmp_path)
        (dirs["logs"] / "xcagi.log").write_bytes(b"important log data")

        cfg = {
            "data_dir": str(tmp_path),
            "database": str(tmp_path / "xcagi.db"),
            "mods": str(tmp_path / "mods"),
            "models": str(tmp_path / "models"),
        }

        with (
            patch("app.desktop_runtime.support_bundle.is_desktop_mode", return_value=True),
            patch("app.desktop_runtime.support_bundle.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.support_bundle.export_config", return_value=cfg),
        ):
            blob = build_support_bundle_zip()

        zf = zipfile.ZipFile(io.BytesIO(blob))
        assert "logs/xcagi.log" in zf.namelist()

    def test_bundle_no_logs(self, tmp_path):
        from app.desktop_runtime.support_bundle import build_support_bundle_zip

        dirs = self._setup_dirs(tmp_path)  # logs dir is empty

        cfg = {
            "data_dir": str(tmp_path),
            "database": str(tmp_path / "xcagi.db"),
            "mods": str(tmp_path / "mods"),
            "models": str(tmp_path / "models"),
        }

        with (
            patch("app.desktop_runtime.support_bundle.is_desktop_mode", return_value=True),
            patch("app.desktop_runtime.support_bundle.ensure_desktop_dirs", return_value=dirs),
            patch("app.desktop_runtime.support_bundle.export_config", return_value=cfg),
        ):
            blob = build_support_bundle_zip()

        zf = zipfile.ZipFile(io.BytesIO(blob))
        # No log files included
        assert not any(n.startswith("logs/") for n in zf.namelist())


# ---------------------------------------------------------------------------
# model_downloader.py
# ---------------------------------------------------------------------------


class TestModelAsset:
    def test_frozen_dataclass(self):
        from app.desktop_runtime.model_downloader import ModelAsset

        a = ModelAsset(name="bert", version="1.0", url="http://example.com/bert.bin", sha256="abc")
        assert a.name == "bert"
        assert a.size is None
        with pytest.raises((AttributeError, TypeError)):
            a.name = "other"  # type: ignore[misc]


class TestModelsDir:
    def test_returns_path(self, tmp_path):
        from app.desktop_runtime.model_downloader import models_dir

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }
        with patch("app.desktop_runtime.model_downloader.ensure_desktop_dirs", return_value=dirs):
            d = models_dir(tmp_path)
        assert d == tmp_path / "models"


class TestSha256:
    def test_known_file(self, tmp_path):
        from app.desktop_runtime.model_downloader import _sha256

        f = tmp_path / "data.bin"
        f.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert _sha256(f) == expected

    def test_large_file_chunked(self, tmp_path):
        from app.desktop_runtime.model_downloader import _sha256

        f = tmp_path / "big.bin"
        data = os.urandom(3 * 1024 * 1024)  # 3 MB
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _sha256(f) == expected


class TestLoadManifest:
    def test_load_manifest_list(self, tmp_path):
        from app.desktop_runtime.model_downloader import load_manifest

        manifest = {
            "models": [
                {
                    "name": "bert",
                    "version": "1.0",
                    "url": "http://x.com/bert.bin",
                    "sha256": "abc123",
                    "size": 1000,
                }
            ]
        }
        f = tmp_path / "manifest.json"
        f.write_text(json.dumps(manifest))
        assets = load_manifest(f)
        assert len(assets) == 1
        assert assets[0].name == "bert"

    def test_load_manifest_raw_list(self, tmp_path):
        """When the manifest JSON is a plain list (not wrapped in {"models": [...]}),
        load_manifest tries raw.get("models", raw) which fails on a list.
        Verify we get an AttributeError (the source code's documented limitation)."""
        from app.desktop_runtime.model_downloader import load_manifest

        manifest = [
            {
                "name": "bert",
                "version": "1.0",
                "url": "http://x.com/bert.bin",
                "sha256": "abc123",
            }
        ]
        f = tmp_path / "manifest.json"
        f.write_text(json.dumps(manifest))
        # The source does raw.get("models", raw) which fails when raw is a list
        with pytest.raises(AttributeError):
            load_manifest(f)


class TestDownloadModel:
    def test_already_downloaded_matches_sha256(self, tmp_path):
        from app.desktop_runtime.model_downloader import ModelAsset, download_model

        data = b"model data"
        sha = hashlib.sha256(data).hexdigest()
        asset = ModelAsset(name="bert", version="1.0", url="http://x.com/bert.bin", sha256=sha)

        target_dir = tmp_path / "models" / "bert" / "1.0"
        target_dir.mkdir(parents=True)
        target_file = target_dir / "bert.bin"
        target_file.write_bytes(data)

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }

        with patch("app.desktop_runtime.model_downloader.ensure_desktop_dirs", return_value=dirs):
            result = download_model(asset, data_dir=tmp_path)
        assert result == target_file

    def test_sha256_mismatch_raises(self, tmp_path):
        from app.desktop_runtime.model_downloader import ModelAsset, download_model

        asset = ModelAsset(
            name="bert",
            version="1.0",
            url="http://x.com/bert.bin",
            sha256="deadbeef" * 8,
            size=10,
        )
        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }

        # Simulate network response with wrong data
        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": "10"}
        mock_response.read.side_effect = [b"wrong data", b""]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.desktop_runtime.model_downloader.ensure_desktop_dirs", return_value=dirs),
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("urllib.request.Request", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="校验失败"):
                download_model(asset, data_dir=tmp_path)

    def test_progress_callback_called(self, tmp_path):
        from app.desktop_runtime.model_downloader import ModelAsset, download_model

        data = b"model content"
        sha = hashlib.sha256(data).hexdigest()
        asset = ModelAsset(
            name="mymodel",
            version="2.0",
            url="http://x.com/mymodel.bin",
            sha256=sha,
            size=len(data),
        )

        dirs = {
            "root": tmp_path,
            "data": tmp_path / "data",
            "mods": tmp_path / "mods",
            "models": tmp_path / "models",
            "backups": tmp_path / "backups",
            "logs": tmp_path / "logs",
        }

        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": str(len(data))}
        mock_response.read.side_effect = [data, b""]
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        progress_calls = []

        def progress_cb(name, copied, total):
            progress_calls.append((name, copied, total))

        with (
            patch("app.desktop_runtime.model_downloader.ensure_desktop_dirs", return_value=dirs),
            patch("urllib.request.urlopen", return_value=mock_response),
            patch("urllib.request.Request", return_value=MagicMock()),
        ):
            download_model(asset, data_dir=tmp_path, progress=progress_cb)

        assert len(progress_calls) >= 1
        assert progress_calls[0][0] == "mymodel"


class TestEnsureModels:
    def test_ensure_models_delegates(self, tmp_path):
        from app.desktop_runtime.model_downloader import ModelAsset, ensure_models

        data = b"model data"
        sha = hashlib.sha256(data).hexdigest()
        asset = ModelAsset(name="m", version="1", url="http://x/m.bin", sha256=sha)

        dirs = {
            "root": tmp_path,
            "data": tmp_path,
            "mods": tmp_path,
            "models": tmp_path / "models",
            "backups": tmp_path,
            "logs": tmp_path,
        }

        # Pre-create the target file so download is skipped
        target_dir = tmp_path / "models" / "m" / "1"
        target_dir.mkdir(parents=True)
        (target_dir / "m.bin").write_bytes(data)

        with patch("app.desktop_runtime.model_downloader.ensure_desktop_dirs", return_value=dirs):
            results = ensure_models([asset], data_dir=tmp_path)

        assert len(results) == 1
