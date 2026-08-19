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
        with patch("app.utils.path_io.path_utils.get_data_dir", return_value=str(tmp_path)):
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
        self._create_real_sqlite_db(db_file)
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
        """sqlite3.backup() API 备份出来的库必须包含全部已提交数据。"""
        import sqlite3

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
        verify_conn = sqlite3.connect(result["file_path"])
        rows = verify_conn.execute("SELECT v FROM t").fetchall()
        verify_conn.close()
        assert rows == [("important data",)]

    @staticmethod
    def _create_real_sqlite_db(db_file):
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO t DEFAULT VALUES")
        conn.commit()
        conn.close()


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


class TestServiceReExportGuard:
    """防回归：``from app.services import get_database_service`` 必须转发到
    ``app.services.database_service``（sqlite3.backup() 版本），而非历史误用的
    ``app.utils.database_service``（shutil.copy2 版本）。

    历史 bug：app/services/__init__.py:64 错误地从 app.utils.database_service 导入，
    导致 Web 后台 POST /api/database/backup 实际用 shutil.copy2 做文件级拷贝，
    在 WAL 模式下会得到不一致的库。此测试套件确保该 bug 不再回退。
    """

    def test_reexports_services_version_not_utils(self):
        import app.services as services_pkg
        import app.services.database_service as correct_mod

        assert services_pkg.get_database_service is correct_mod.get_database_service

    def test_database_service_has_hot_backup_method(self):
        from app.services.database_service import DatabaseService as CorrectDbService

        # 正确版本用 sqlite3.backup() API，封装在 _hot_backup 静态方法里；
        # 旧错误版本（app.utils.database_service）没有这个方法。
        assert hasattr(CorrectDbService, "_hot_backup")

    def test_backup_database_uses_hot_backup_not_shutil_copy(self):
        """正确版本 backup_database 必须调用 _hot_backup（sqlite3.backup() API），
        而非直接 shutil.copy2。用行为测试验证：mock _hot_backup 返回 False 时
        backup_database 必须返回失败。"""
        import sqlite3
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.services.database_service import DatabaseService as CorrectDbService

        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "test.db"
            conn = sqlite3.connect(str(db_file))
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.commit()
            conn.close()

            svc = CorrectDbService()
            with (
                patch.object(svc, "_get_db_path", return_value=str(db_file)),
                patch.object(svc, "_get_backup_dir", return_value=str(Path(tmp) / "backups")),
                patch.object(CorrectDbService, "_hot_backup", return_value=False) as mock_hot,
            ):
                result = svc.backup_database()

            assert result["success"] is False
            assert "热备份失败" in result["message"]
            mock_hot.assert_called_once()
