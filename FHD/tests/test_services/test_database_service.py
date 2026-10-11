"""测试 database_service 模块 - 数据库管理服务。"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import make_url

from app.services.database_service import DatabaseService


class TestGetDbPath:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("sqlite:///relative.db", os.path.join(os.getcwd(), "relative.db")),
            ("sqlite:////absolute/path/test.db", "/absolute/path/test.db"),
            ("postgresql://test@localhost/test", None),
            ("sqlite://", None),
        ],
    )
    def test_runtime_engine_path(self, url, expected):
        with patch("app.db.get_runtime_engine", return_value=SimpleNamespace(url=make_url(url))):
            assert DatabaseService()._get_db_path() == expected


class TestGetBackupDir:
    def test_creates_backup_dir(self, tmp_path):
        svc = DatabaseService()
        with patch("app.utils.path_io.path_utils.get_data_dir", return_value=str(tmp_path)):
            backup_dir = svc._get_backup_dir()
            assert os.path.isdir(backup_dir)
            assert "database_backups" in backup_dir


class TestBackupDatabase:
    @pytest.mark.parametrize(
        "path,message", [(None, "仅支持 SQLite"), ("/nonexistent/path/test.db", "不存在")]
    )
    def test_backup_unavailable(self, path, message):
        with patch.object(DatabaseService, "_get_db_path", return_value=path):
            result = DatabaseService().backup_database()
        assert result["success"] is False
        assert message in result["message"]

    def test_backup_copies_content(self, tmp_path):
        """sqlite3.backup() API 备份出来的库必须包含全部已提交数据。"""
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('important data')")
        conn.commit()
        conn.close()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
                result = svc.backup_database()

        assert result["success"] is True
        assert os.path.exists(result["file_path"])
        assert result["filename"].endswith(".bak")
        verify_conn = sqlite3.connect(result["file_path"])
        rows = verify_conn.execute("SELECT v FROM t").fetchall()
        verify_conn.close()
        assert rows == [("important data",)]


class TestRestoreDatabase:
    @pytest.mark.parametrize(
        "case", ["new-audit", "schema-mismatch", "concurrent-write", "slow-copy"]
    )
    def test_restore_preserves_live_audit_or_refuses_before_commit(
        self, tmp_path, monkeypatch, case
    ):
        live, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
        with sqlite3.connect(backup) as db:
            db.execute("create table products(price real)")
            db.execute("insert into products values(12.5)")
            if case != "new-audit":
                db.execute(
                    "create table ai_action_audit(id integer primary key autoincrement, result text)"
                )
                db.execute("insert into ai_action_audit values(1, 'old')")
        with sqlite3.connect(live) as db:
            db.execute("pragma journal_mode=wal")
            db.execute("create table products(price real)")
            db.execute("insert into products values(13.75)")
            db.execute(
                "create table ai_action_audit(id integer primary key autoincrement, result text)"
            )
            db.execute("create unique index audit_unique_result on ai_action_audit(result)")
            db.execute(
                "create trigger audit_no_blank before insert on ai_action_audit when new.result='' begin select raise(abort, 'blank receipt'); end"
            )
            db.execute("insert into ai_action_audit values(1, 'completed')")
            db.execute("insert into ai_action_audit values(3, 'retired receipt')")
            db.execute("delete from ai_action_audit where id=3")
            if case == "schema-mismatch":
                db.execute("alter table ai_action_audit add column actor text")
            audit_schema = db.execute(
                "select sql from sqlite_master where name='ai_action_audit'"
            ).fetchone()[0]
        original_backup = backup.read_bytes()
        service = DatabaseService()
        monkeypatch.setattr(service, "_get_db_path", lambda: str(live))
        stage = service._stage_restore

        def stage_then_write(*args):
            version = stage(*args)
            with sqlite3.connect(live) as writer:
                writer.execute("insert into ai_action_audit values(2, 'late receipt')")
            return version

        if case == "concurrent-write":
            monkeypatch.setattr(service, "_stage_restore", stage_then_write)
        if case == "slow-copy":
            monkeypatch.setattr(
                "app.services.database_service.time",
                SimpleNamespace(monotonic=Mock(side_effect=[0, 3])),
            )
        result = service.restore_database(str(backup))
        restored = case != "concurrent-write"
        assert result["success"] is restored
        with sqlite3.connect(live) as reopened:
            assert reopened.execute("select price from products").fetchone()[0] == (
                12.5 if restored else 13.75
            )
            assert reopened.execute(
                "select result from ai_action_audit order by id"
            ).fetchall() == (
                [("completed",), ("late receipt",)]
                if case == "concurrent-write"
                else [("completed",)]
            )
            assert reopened.execute("pragma integrity_check").fetchone()[0] == "ok"
            assert (
                reopened.execute(
                    "select sql from sqlite_master where name='ai_action_audit'"
                ).fetchone()[0]
                == audit_schema
            )
            if restored:
                assert (
                    reopened.execute(
                        "insert into ai_action_audit(result) values('after restore')"
                    ).lastrowid
                    == 4
                )
                with pytest.raises(sqlite3.IntegrityError):
                    reopened.execute("insert into ai_action_audit(result) values('completed')")
                with pytest.raises(sqlite3.IntegrityError):
                    reopened.execute("insert into ai_action_audit(result) values('')")
        assert backup.read_bytes() == original_backup
        assert not list(tmp_path.glob("xcagi-restore-*"))

    @pytest.mark.parametrize("path,message", [(None, "仅支持 SQLite"), ("live.db", "不存在")])
    def test_restore_unavailable(self, tmp_path, path, message):
        svc = DatabaseService()
        with (
            patch.object(svc, "_get_db_path", return_value=path),
            patch.object(svc, "_get_backup_dir", return_value=str(tmp_path)),
        ):
            result = svc.restore_database("nonexistent.bak")
        assert result["success"] is False
        assert message in result["message"]

    @pytest.mark.parametrize("absolute", [False, True])
    def test_restore_success_with_live_wal_connection(self, tmp_path, absolute):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_file = backup_dir / "test.db.20240101_000000.bak"
        with sqlite3.connect(backup_file) as snapshot:
            snapshot.execute("create table products(price real)")
            snapshot.execute("insert into products values (12.50)")
        live = sqlite3.connect(db_file)
        try:
            live.execute("pragma journal_mode=wal")
            live.execute("create table products(price real)")
            live.execute("insert into products values (13.50)")
            live.commit()
            with (
                patch.object(svc, "_get_db_path", return_value=str(db_file)),
                patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)),
            ):
                result = svc.restore_database(str(backup_file) if absolute else backup_file.name)
            assert result["success"] is True
            assert live.execute("select price from products").fetchone()[0] == 12.50
            assert live.execute("pragma integrity_check").fetchone()[0] == "ok"
        finally:
            live.close()
        with sqlite3.connect(db_file) as reopened:
            assert reopened.execute("select price from products").fetchone()[0] == 12.50
            assert reopened.execute("pragma integrity_check").fetchone()[0] == "ok"

    def test_restore_invalid_backup_preserves_database(self, tmp_path):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        with sqlite3.connect(db_file) as db:
            db.execute("create table products(price real)")
            db.execute("insert into products values (13.50)")
        original = db_file.read_bytes()
        backup_file = tmp_path / "custom_backup.bak"
        backup_file.write_text("new")

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            result = svc.restore_database(str(backup_file))

        assert result["success"] is False
        assert db_file.read_bytes() == original

    def test_restore_locked_database_fails_without_overwriting_or_hanging(self, tmp_path):
        svc = DatabaseService()
        live_path, backup = tmp_path / "live.db", tmp_path / "snapshot.bak"
        with sqlite3.connect(backup) as snapshot:
            snapshot.execute("create table products(price real)")
            snapshot.execute("insert into products values (12.50)")
        writer = sqlite3.connect(live_path)
        try:
            writer.execute("pragma journal_mode=wal")
            writer.execute("create table products(price real)")
            writer.execute("insert into products values (13.50)")
            writer.commit()
            writer.execute("update products set price=14.50")
            with patch.object(svc, "_get_db_path", return_value=str(live_path)):
                result = svc.restore_database(str(backup))
            assert result["success"] is False
            assert writer.execute("select price from products").fetchone()[0] == 14.50
            writer.rollback()
            assert writer.execute("select price from products").fetchone()[0] == 13.50
            assert writer.execute("pragma integrity_check").fetchone()[0] == "ok"
        finally:
            writer.close()


class TestListBackups:
    @pytest.mark.parametrize("exists", [False, True])
    def test_list_empty_or_missing_dir(self, tmp_path, exists):
        folder = tmp_path / "backups"
        if exists:
            folder.mkdir()
        with patch.object(DatabaseService, "_get_backup_dir", return_value=str(folder)):
            result = DatabaseService().list_backups()
        assert result["success"] is True
        assert result["count"] == 0

    def test_list_finds_bak_files(self, tmp_path):
        svc = DatabaseService()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "test1.bak").write_text("b1")
        (backup_dir / "test2.bak").write_text("b2")
        (backup_dir / "other.txt").write_text("not a backup")

        with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
            result = svc.list_backups()

        assert result["success"] is True
        assert result["count"] == 2
        filenames = [b["filename"] for b in result["backups"]]
        assert "test1.bak" in filenames
        assert "test2.bak" in filenames
        assert "other.txt" not in filenames
        for backup in result["backups"]:
            assert {"filename", "file_path", "size", "created_at"} <= backup.keys()
        dates = [backup["created_at"] for backup in result["backups"]]
        assert dates == sorted(dates, reverse=True)


class TestDeleteBackup:
    def test_delete_nonexistent_returns_failure(self, tmp_path):
        svc = DatabaseService()
        with patch.object(svc, "_get_backup_dir", return_value=str(tmp_path)):
            result = svc.delete_backup("nonexistent.bak")
        assert result["success"] is False

    @pytest.mark.parametrize("absolute", [False, True])
    def test_delete_success(self, tmp_path, absolute):
        backup_file = tmp_path / "test.bak"
        backup_file.write_text("backup data")
        with patch.object(DatabaseService, "_get_backup_dir", return_value=str(tmp_path)):
            result = DatabaseService().delete_backup(
                str(backup_file) if absolute else backup_file.name
            )
        assert result["success"] is True
        assert not backup_file.exists()


class TestServiceReExportGuard:
    def test_reexports_services_version_not_utils(self):
        import app.services as services_pkg
        import app.services.database_service as correct_mod

        assert services_pkg.get_database_service is correct_mod.get_database_service
        assert isinstance(services_pkg.get_database_service(), DatabaseService)

    def test_backup_database_uses_hot_backup_not_shutil_copy(self, tmp_path):
        db_file = tmp_path / "test.db"
        with sqlite3.connect(db_file) as db:
            db.execute("CREATE TABLE t (id INTEGER)")
        svc = DatabaseService()
        with (
            patch.object(svc, "_get_db_path", return_value=str(db_file)),
            patch.object(svc, "_get_backup_dir", return_value=str(tmp_path)),
            patch.object(DatabaseService, "_hot_backup", return_value=False) as mock_hot,
        ):
            result = svc.backup_database()
        assert result["success"] is False
        assert "热备份失败" in result["message"]
        mock_hot.assert_called_once()
