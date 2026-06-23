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
        db.write_bytes(b"SQLite data")
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
        (dirs["logs"] / "xcagi.log").write_bytes(b"log content")

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
