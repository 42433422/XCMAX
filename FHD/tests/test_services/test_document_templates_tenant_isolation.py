"""模板库多租户隔离：DB 列表/创建打标 + 文件系统发现目录。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore
from app.infrastructure.templates.tenant_scope import (
    templates_tenant_id_for_insert,
    templates_tenant_where_sql,
)
from app.infrastructure.tenant_scope import TenantScopeError, tenant_scope


@pytest.fixture()
def templates_db(monkeypatch):
    """内存 sqlite templates 表，含跨租户与 NULL 存量。"""
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_key TEXT,
                    template_name TEXT NOT NULL,
                    template_type TEXT,
                    original_file_path TEXT,
                    analyzed_data TEXT,
                    editable_config TEXT,
                    zone_config TEXT,
                    merged_cells_config TEXT,
                    style_config TEXT,
                    business_rules TEXT,
                    is_active INTEGER DEFAULT 1,
                    tenant_id INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO templates (template_key, template_name, template_type, is_active, tenant_id)
                VALUES
                    ('T1', 'tenant1-tpl', 'Excel', 1, 1),
                    ('T2', 'tenant2-tpl', 'Excel', 1, 2),
                    ('T0', 'legacy-null', 'Excel', 1, NULL)
                """
            )
        )

    class _Ctx:
        def __enter__(self):
            self.session = Session(eng)
            return self.session

        def __exit__(self, *args):
            self.session.close()

    # store 模块级 import 了 get_db，必须 patch 使用处
    monkeypatch.setattr(
        "app.infrastructure.templates.template_store_impl.get_db",
        lambda: _Ctx(),
    )
    monkeypatch.setattr(
        "app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column",
        lambda: None,
    )
    return eng


class TestTemplatesTenantWhereSql:
    def test_no_tenant_fail_closed(self):
        sql, bind = templates_tenant_where_sql()
        assert sql == "1 = 0"
        assert bind == {}

    def test_strict_equals_current(self):
        with tenant_scope(7):
            sql, bind = templates_tenant_where_sql()
        assert "tenant_id = :tenant_id" in sql
        assert "IS NULL" not in sql
        assert bind == {"tenant_id": 7}

    def test_legacy_null_visible(self, monkeypatch):
        monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
        with tenant_scope(7):
            sql, bind = templates_tenant_where_sql()
        assert "IS NULL" in sql
        assert bind == {"tenant_id": 7}


class TestTemplatesTenantIdForInsert:
    def test_requires_tenant(self):
        with (
            patch("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column"),
            pytest.raises(TenantScopeError),
        ):
            templates_tenant_id_for_insert()

    def test_returns_current(self):
        with (
            patch("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column"),
            tenant_scope(3),
        ):
            assert templates_tenant_id_for_insert() == 3


class TestDbTemplatesIsolation:
    def test_tenant_sees_only_own(self, templates_db, tmp_path):
        store = FileSystemTemplateStore(str(tmp_path))
        with tenant_scope(1):
            names = {t["name"] for t in store._db_templates()}
        assert names == {"tenant1-tpl"}

        with tenant_scope(2):
            names = {t["name"] for t in store._db_templates()}
        assert names == {"tenant2-tpl"}

    def test_no_tenant_sees_none(self, templates_db, tmp_path):
        store = FileSystemTemplateStore(str(tmp_path))
        assert store._db_templates() == []

    def test_legacy_null_opt_in(self, templates_db, tmp_path, monkeypatch):
        monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
        store = FileSystemTemplateStore(str(tmp_path))
        with tenant_scope(1):
            names = {t["name"] for t in store._db_templates()}
        assert names == {"tenant1-tpl", "legacy-null"}


class TestDiscoveryDirectoriesTenantPrivate:
    def test_includes_tenant_dirs_only_when_scoped(self, tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        monkeypatch.setattr(
            "app.infrastructure.templates.template_store_impl.get_app_data_dir",
            lambda: str(runtime),
        )
        store = FileSystemTemplateStore(str(tmp_path / "base"))

        dirs_none = store._discovery_directories()
        assert not any("/tenants/" in d.replace("\\", "/") for d in dirs_none)

        with tenant_scope(99):
            dirs = store._discovery_directories()
        joined = "\n".join(d.replace("\\", "/") for d in dirs)
        assert "tenants/99/templates" in joined
        assert "tenants/99/document_templates" in joined
        assert "tenants/1/" not in joined

    def test_does_not_scan_shared_runtime_templates(self, tmp_path, monkeypatch):
        runtime = tmp_path / "runtime"
        (runtime / "templates").mkdir(parents=True)
        monkeypatch.setattr(
            "app.infrastructure.templates.template_store_impl.get_app_data_dir",
            lambda: str(runtime),
        )
        store = FileSystemTemplateStore(str(tmp_path / "base"))
        with tenant_scope(1):
            dirs = [d.replace("\\", "/") for d in store._discovery_directories()]
        shared = str((runtime / "templates").resolve()).replace("\\", "/")
        assert shared not in dirs


class TestCreateTagsTenant:
    def test_insert_binds_tenant_id(self):
        from app.services.document_templates.crud import create_template_with_payload

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.lastrowid = 9
        mock_db.execute.return_value = mock_result

        with (
            tenant_scope(42),
            patch("app.db.session.get_db") as mock_get_db,
            patch("app.db.init_db.init_template_tables"),
            patch("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column"),
            patch(
                "app.services.document_templates.crud._validate_required_terms",
                return_value=(True, []),
            ),
        ):
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            result = create_template_with_payload({"name": "隔离创建"})

        assert result.get_json()["success"] is True
        params = mock_db.execute.call_args_list[0][0][1]
        assert params["tenant_id"] == 42

    def test_create_without_tenant_forbidden(self):
        from app.services.document_templates.crud import create_template_with_payload

        with (
            patch("app.db.init_db.init_template_tables"),
            patch("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column"),
            patch(
                "app.services.document_templates.crud._validate_required_terms",
                return_value=(True, []),
            ),
        ):
            result = create_template_with_payload({"name": "无租户"})
        data = result.get_json()
        assert result.status_code == 403
        assert data["success"] is False
