"""测试 MOD 索引服务模块。"""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.mods.index_service import (
    ModIndexDatabase,
    ModIndexService,
    get_mod_index_service,
)


@pytest.fixture
def tmp_db(tmp_path):
    """创建临时数据库。"""
    return str(tmp_path / "test_mod_index.db")


@pytest.fixture
def db(tmp_db):
    """创建 ModIndexDatabase 实例。"""
    return ModIndexDatabase(db_path=tmp_db)


@pytest.fixture
def sample_metadata():
    """示例 MOD 元数据。"""
    return {
        "id": "test-mod-001",
        "name": "测试MOD",
        "version": "1.0.0",
        "author": "test_author",
        "description": "一个测试MOD",
        "file_size": 1024,
        "dependencies": {"xcagi": ">=10.0.0", "other-mod": ">=1.0.0"},
    }


@pytest.fixture
def service(tmp_db):
    """创建 ModIndexService 实例，使用隔离的临时数据库。"""
    svc = ModIndexService()
    svc.db = ModIndexDatabase(db_path=tmp_db)
    return svc


class TestModIndexDatabaseInit:
    """测试数据库初始化。"""

    def test_creates_database_file(self, tmp_db):
        db = ModIndexDatabase(db_path=tmp_db)
        assert os.path.exists(tmp_db)

    def test_creates_tables(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row["name"] for row in cursor.fetchall()}
        assert "mod_metadata" in tables
        assert "mod_dependencies" in tables
        assert "mod_ratings" in tables
        assert "mod_statistics" in tables

    def test_creates_indexes(self, db):
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_mod_name" in indexes
        assert "idx_mod_author" in indexes
        assert "idx_mod_installed" in indexes

    def test_default_db_path_when_none(self):
        with patch.dict(os.environ, {"XCAGI_MOD_STORE_DIR": ""}):
            db = ModIndexDatabase(db_path=None)
            assert db.db_path.endswith("mod_index.db")


class TestModIndexDatabaseConnection:
    """测试数据库连接管理。"""

    def test_get_connection_commit_on_success(self, db):
        with db.get_connection() as conn:
            conn.execute("INSERT INTO mod_metadata (id, name, version) VALUES ('x', 'y', 'z')")
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM mod_metadata WHERE id='x'").fetchone()
        assert row is not None

    def test_get_connection_rollback_on_error(self, db):
        try:
            with db.get_connection() as conn:
                conn.execute("INSERT INTO mod_metadata (id, name, version) VALUES ('a', 'b', 'c')")
                raise ValueError("test error")
        except ValueError:
            pass
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM mod_metadata WHERE id='a'").fetchone()
        assert row is None


class TestModIndexDatabaseUpsert:
    """测试 MOD 元数据插入/更新。"""

    def test_upsert_mod_inserts_new(self, db, sample_metadata):
        result = db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        assert result is True

        mod = db.get_mod("test-mod-001")
        assert mod is not None
        assert mod["name"] == "测试MOD"
        assert mod["version"] == "1.0.0"

    def test_upsert_mod_updates_existing(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        sample_metadata["name"] = "更新后的MOD"
        sample_metadata["version"] = "2.0.0"
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")

        mod = db.get_mod("test-mod-001")
        assert mod["name"] == "更新后的MOD"
        assert mod["version"] == "2.0.0"

    def test_upsert_mod_stores_dependencies(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mod_dependencies WHERE mod_id='test-mod-001'"
            ).fetchall()
        deps = {row["dependency_id"]: row["dep_type"] for row in rows}
        assert "xcagi" in deps
        assert deps["xcagi"] == "core"
        assert "other-mod" in deps
        assert deps["other-mod"] == "mod"

    def test_upsert_mod_replaces_dependencies(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        sample_metadata["dependencies"] = {"xcagi": ">=10.0.0"}
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM mod_dependencies WHERE mod_id='test-mod-001'"
            ).fetchall()
        assert len(rows) == 1

    def test_upsert_mod_stores_manifest_json(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        mod = db.get_mod("test-mod-001")
        manifest = json.loads(mod["manifest_json"])
        assert manifest["id"] == "test-mod-001"

    def test_upsert_mod_with_empty_metadata(self, db):
        result = db.upsert_mod({}, "empty.xcmod")
        assert result is True
        mod = db.get_mod("")
        assert mod is not None

    def test_upsert_mod_with_no_dependencies(self, db):
        metadata = {"id": "no-deps", "name": "NoDeps", "version": "1.0.0"}
        result = db.upsert_mod(metadata, "no-deps.xcmod")
        assert result is True


class TestModIndexDatabaseGet:
    """测试 MOD 查询功能。"""

    def test_get_mod_returns_none_for_nonexistent(self, db):
        result = db.get_mod("nonexistent")
        assert result is None

    def test_get_mod_returns_dict(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        result = db.get_mod("test-mod-001")
        assert isinstance(result, dict)
        assert result["id"] == "test-mod-001"

    def test_get_all_mods_empty(self, db):
        result = db.get_all_mods()
        assert result == []

    def test_get_all_mods_returns_all(self, db):
        for i in range(3):
            db.upsert_mod(
                {"id": f"mod-{i}", "name": f"MOD {i}", "version": "1.0.0"},
                f"mod-{i}.xcmod",
            )
        result = db.get_all_mods()
        assert len(result) == 3

    def test_get_all_mods_ordered_by_name(self, db):
        for name, mid in [("Charlie", "c"), ("Alice", "a"), ("Bob", "b")]:
            db.upsert_mod(
                {"id": mid, "name": name, "version": "1.0.0"},
                f"{mid}.xcmod",
            )
        result = db.get_all_mods()
        names = [r["name"] for r in result]
        assert names == ["Alice", "Bob", "Charlie"]


class TestModIndexDatabaseSearch:
    """测试 MOD 搜索功能。"""

    def test_search_no_filters_returns_all(self, db):
        for i in range(3):
            db.upsert_mod(
                {"id": f"mod-{i}", "name": f"MOD {i}", "version": "1.0.0"},
                f"mod-{i}.xcmod",
            )
        result = db.search_mods()
        assert len(result) == 3

    def test_search_by_query_matches_name(self, db):
        db.upsert_mod({"id": "1", "name": "Excel工具", "version": "1.0.0"}, "1.xcmod")
        db.upsert_mod({"id": "2", "name": "PDF工具", "version": "1.0.0"}, "2.xcmod")
        result = db.search_mods(query="Excel")
        assert len(result) == 1
        assert result[0]["name"] == "Excel工具"

    def test_search_by_query_matches_description(self, db):
        db.upsert_mod(
            {"id": "1", "name": "工具", "version": "1.0.0", "description": "Excel处理"},
            "1.xcmod",
        )
        result = db.search_mods(query="Excel")
        assert len(result) == 1

    def test_search_by_author(self, db):
        db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0", "author": "张三"},
            "1.xcmod",
        )
        db.upsert_mod(
            {"id": "2", "name": "MOD2", "version": "1.0.0", "author": "李四"},
            "2.xcmod",
        )
        result = db.search_mods(author="张")
        assert len(result) == 1

    def test_search_installed_only(self, db):
        db.upsert_mod({"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod")
        db.upsert_mod({"id": "2", "name": "MOD2", "version": "1.0.0"}, "2.xcmod")
        db.update_install_status("1", True)
        result = db.search_mods(installed_only=True)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_search_with_limit(self, db):
        for i in range(10):
            db.upsert_mod(
                {"id": f"mod-{i}", "name": f"MOD {i}", "version": "1.0.0"},
                f"mod-{i}.xcmod",
            )
        result = db.search_mods(limit=3)
        assert len(result) == 3

    def test_search_combined_filters(self, db):
        db.upsert_mod(
            {"id": "1", "name": "Excel工具", "version": "1.0.0", "author": "张三"},
            "1.xcmod",
        )
        db.update_install_status("1", True)
        db.upsert_mod(
            {"id": "2", "name": "PDF工具", "version": "1.0.0", "author": "张三"},
            "2.xcmod",
        )
        result = db.search_mods(query="Excel", author="张", installed_only=True)
        assert len(result) == 1


class TestModIndexDatabaseInstallStatus:
    """测试安装状态更新。"""

    def test_update_install_status_to_installed(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        db.update_install_status("test-mod-001", True)
        mod = db.get_mod("test-mod-001")
        assert mod["is_installed"] == 1

    def test_update_install_status_to_uninstalled(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        db.update_install_status("test-mod-001", True)
        db.update_install_status("test-mod-001", False)
        mod = db.get_mod("test-mod-001")
        assert mod["is_installed"] == 0


class TestModIndexDatabaseDownloadCount:
    """测试下载计数。"""

    def test_increment_download_count(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        db.increment_download_count("test-mod-001")
        db.increment_download_count("test-mod-001")
        mod = db.get_mod("test-mod-001")
        assert mod["download_count"] == 2


class TestModIndexDatabaseRatings:
    """测试评分功能。"""

    def test_add_rating(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        result = db.add_rating("test-mod-001", "user1", 5, "很好")
        assert result is True

    def test_get_ratings(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        db.add_rating("test-mod-001", "user1", 5, "很好")
        db.add_rating("test-mod-001", "user2", 3, "一般")
        ratings = db.get_ratings("test-mod-001")
        assert len(ratings) == 2

    def test_get_ratings_empty(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        ratings = db.get_ratings("test-mod-001")
        assert ratings == []

    def test_add_rating_updates_statistics(self, db, sample_metadata):
        db.upsert_mod(sample_metadata, "test-mod-001.xcmod")
        db.add_rating("test-mod-001", "user1", 4)
        db.add_rating("test-mod-001", "user2", 2)
        stats = db.get_statistics("test-mod-001")
        assert stats is not None
        assert stats["rating_count"] == 2
        assert abs(stats["avg_rating"] - 3.0) < 0.01

    def test_get_statistics_returns_none_for_nonexistent(self, db):
        result = db.get_statistics("nonexistent")
        assert result is None


class TestModIndexDatabasePopularAndRecent:
    """测试热门和最新 MOD 查询。"""

    def test_get_popular_mods(self, db):
        for i in range(3):
            db.upsert_mod(
                {"id": f"mod-{i}", "name": f"MOD {i}", "version": "1.0.0"},
                f"mod-{i}.xcmod",
            )
        result = db.get_popular_mods(limit=2)
        assert len(result) <= 2

    def test_get_recent_mods(self, db):
        for i in range(3):
            db.upsert_mod(
                {"id": f"mod-{i}", "name": f"MOD {i}", "version": "1.0.0"},
                f"mod-{i}.xcmod",
            )
        result = db.get_recent_mods(limit=2)
        assert len(result) <= 2


class TestModIndexService:
    """测试 ModIndexService 层。"""

    def test_get_instance_singleton(self):
        ModIndexService._instance = None
        s1 = ModIndexService.get_instance()
        s2 = ModIndexService.get_instance()
        assert s1 is s2
        ModIndexService._instance = None

    def test_search_delegates_to_db(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "TestMOD", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.search(query="Test")
        assert len(result) == 1

    def test_get_mod_delegates_to_db(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "TestMOD", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.get_mod("1")
        assert result is not None
        assert result["name"] == "TestMOD"

    def test_get_mod_returns_none_for_nonexistent(self, service):
        result = service.get_mod("nonexistent")
        assert result is None

    def test_get_all_mods_delegates(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.get_all_mods()
        assert len(result) == 1

    def test_add_rating_valid(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.add_rating("1", "user1", 4, "不错")
        assert result is True

    def test_add_rating_invalid_too_low(self, service):
        result = service.add_rating("1", "user1", 0)
        assert result is False

    def test_add_rating_invalid_too_high(self, service):
        result = service.add_rating("1", "user1", 6)
        assert result is False

    def test_add_rating_boundary_values(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        assert service.add_rating("1", "u1", 1) is True
        assert service.add_rating("1", "u2", 5) is True

    def test_get_ratings_delegates(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        service.add_rating("1", "user1", 5)
        result = service.get_ratings("1")
        assert len(result) == 1

    def test_get_statistics_delegates(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        service.add_rating("1", "user1", 4)
        result = service.get_statistics("1")
        assert result is not None

    def test_get_popular_mods_delegates(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.get_popular_mods(limit=5)
        assert isinstance(result, list)

    def test_get_recent_mods_delegates(self, service):
        service.db.upsert_mod(
            {"id": "1", "name": "MOD1", "version": "1.0.0"}, "1.xcmod"
        )
        result = service.get_recent_mods(limit=5)
        assert isinstance(result, list)

    def test_index_mod_package_invalid(self, service):
        mock_manager = MagicMock()
        mock_manager.validate_mod_package.return_value = (False, "invalid", {})
        mock_mod_manager_module = MagicMock()
        mock_mod_manager_module.get_mod_manager.return_value = mock_manager

        with patch.dict("sys.modules", {
            "app.infrastructure.mods": mock_mod_manager_module,
            "app.infrastructure.mods.mod_manager": mock_mod_manager_module,
        }):
            result = service.index_mod_package("/fake/path.xcmod", "fake.xcmod")
            assert result is False

    def test_rebuild_index_nonexistent_dir(self, service):
        success, fail = service.rebuild_index(store_dir="/nonexistent/dir")
        assert success == 0
        assert fail == 0

    def test_rebuild_index_empty_dir(self, service, tmp_path):
        success, fail = service.rebuild_index(store_dir=str(tmp_path))
        assert success == 0
        assert fail == 0


class TestGetModIndexService:
    """测试工厂函数。"""

    def test_returns_mod_index_service(self):
        ModIndexService._instance = None
        result = get_mod_index_service()
        assert isinstance(result, ModIndexService)
        ModIndexService._instance = None
