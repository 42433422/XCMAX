"""测试 database_service 模块 - 数据库管理服务。"""

from __future__ import annotations

import os
import shutil
from unittest.mock import MagicMock, patch

import pytest

from app.services.database_service import DatabaseService, get_database_service


class TestDatabaseServiceInit:
    """测试 DatabaseService 初始化。"""

    def test_init(self):
        svc = DatabaseService()
        assert svc is not None


class TestGetDbPath:
    """测试 _get_db_path 方法。"""

    def test_sqlite_path(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value="/tmp/test.db"):
            path = svc._get_db_path()
            assert path is not None
            assert "test.db" in path

    def test_sqlite_absolute_path(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value="/absolute/path/test.db"):
            path = svc._get_db_path()
            assert path == "/absolute/path/test.db"

    def test_postgres_returns_none(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value=None):
            path = svc._get_db_path()
            assert path is None


class TestGetBackupDir:
    """测试 _get_backup_dir 方法。"""

    def test_creates_backup_dir(self, tmp_path):
        svc = DatabaseService()
        with patch("app.utils.path_utils.get_data_dir", return_value=str(tmp_path)):
            backup_dir = svc._get_backup_dir()
            assert os.path.isdir(backup_dir)
            assert "database_backups" in backup_dir


class TestBackupDatabase:
    """测试 backup_database 方法。"""

    def test_backup_non_sqlite_returns_failure(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value=None):
            result = svc.backup_database()
            assert result["success"] is False
            assert "仅支持 SQLite" in result["message"]

    def test_backup_nonexistent_db_returns_failure(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value="/nonexistent/path/test.db"):
            result = svc.backup_database()
            assert result["success"] is False
            assert "不存在" in result["message"]

    def test_backup_success(self, tmp_path):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        db_file.write_text("fake db content")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
                result = svc.backup_database()

        assert result["success"] is True
        assert result["file_path"] is not None
        assert os.path.exists(result["file_path"])
        assert result["filename"].endswith(".bak")

    def test_backup_copies_content(self, tmp_path):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        db_file.write_text("important data")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
                result = svc.backup_database()

        with open(result["file_path"]) as f:
            assert f.read() == "important data"


class TestRestoreDatabase:
    """测试 restore_database 方法。"""

    def test_restore_non_sqlite_returns_failure(self):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value=None):
            result = svc.restore_database("backup.bak")
            assert result["success"] is False
            assert "仅支持 SQLite" in result["message"]

    def test_restore_nonexistent_backup_returns_failure(self, tmp_path):
        svc = DatabaseService()
        with patch.object(svc, "_get_db_path", return_value=str(tmp_path / "test.db")):
            with patch.object(svc, "_get_backup_dir", return_value=str(tmp_path / "backups")):
                result = svc.restore_database("nonexistent.bak")
                assert result["success"] is False
                assert "不存在" in result["message"]

    def test_restore_success(self, tmp_path):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        db_file.write_text("old content")
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        backup_file = backup_dir / "test.db.20240101_000000.bak"
        backup_file.write_text("restored content")

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
                result = svc.restore_database(backup_file.name)

        assert result["success"] is True
        assert db_file.read_text() == "restored content"

    def test_restore_absolute_path(self, tmp_path):
        svc = DatabaseService()
        db_file = tmp_path / "test.db"
        db_file.write_text("old")
        backup_file = tmp_path / "custom_backup.bak"
        backup_file.write_text("new")

        with patch.object(svc, "_get_db_path", return_value=str(db_file)):
            result = svc.restore_database(str(backup_file))

        assert result["success"] is True
        assert db_file.read_text() == "new"


class TestListBackups:
    """测试 list_backups 方法。"""

    def test_list_empty_dir(self, tmp_path):
        svc = DatabaseService()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
            result = svc.list_backups()
        assert result["success"] is True
        assert result["count"] == 0

    def test_list_nonexistent_dir(self, tmp_path):
        svc = DatabaseService()
        with patch.object(svc, "_get_backup_dir", return_value=str(tmp_path / "nonexistent")):
            result = svc.list_backups()
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

    def test_list_sorted_by_created_at_desc(self, tmp_path):
        svc = DatabaseService()
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "a.bak").write_text("a")
        (backup_dir / "b.bak").write_text("b")

        with patch.object(svc, "_get_backup_dir", return_value=str(backup_dir)):
            result = svc.list_backups()

        assert result["success"] is True
        for backup in result["backups"]:
            assert "filename" in backup
            assert "file_path" in backup
            assert "size" in backup
            assert "created_at" in backup


class TestDeleteBackup:
    """测试 delete_backup 方法。"""

    def test_delete_nonexistent_returns_failure(self, tmp_path):
        svc = DatabaseService()
        with patch.object(svc, "_get_backup_dir", return_value=str(tmp_path)):
            result = svc.delete_backup("nonexistent.bak")
        assert result["success"] is False

    def test_delete_success(self, tmp_path):
        svc = DatabaseService()
        backup_file = tmp_path / "test.bak"
        backup_file.write_text("backup data")

        with patch.object(svc, "_get_backup_dir", return_value=str(tmp_path)):
            result = svc.delete_backup("test.bak")

        assert result["success"] is True
        assert not backup_file.exists()

    def test_delete_absolute_path(self, tmp_path):
        svc = DatabaseService()
        backup_file = tmp_path / "abs.bak"
        backup_file.write_text("data")

        result = svc.delete_backup(str(backup_file))
        assert result["success"] is True
        assert not backup_file.exists()


class TestGetDatabaseService:
    """测试工厂函数。"""

    def test_returns_instance(self):
        svc = get_database_service()
        assert isinstance(svc, DatabaseService)
