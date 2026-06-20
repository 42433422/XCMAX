"""测试 wechat_contact_store_impl 模块的微信联系人存储。"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.persistence.wechat_contact_store_impl import (
    SQLAlchemyWechatContactStore,
    _read_rows_from_contact_db,
    resolve_decrypt_contact_db_path,
)

# ---------------------------------------------------------------------------
# resolve_decrypt_contact_db_path
# ---------------------------------------------------------------------------


class TestResolveDecryptContactDbPath:
    @patch("app.utils.path_utils.get_base_dir", return_value="/tmp/nonexistent_base")
    @patch("app.infrastructure.plugins.wechat_plugin.get_wechat_plugin")
    def test_no_db_returns_none(self, mock_plugin, mock_dir):
        mock_p = MagicMock()
        mock_p.is_available.return_value = False
        mock_p.get_decrypted_db_path.return_value = None
        mock_plugin.return_value = mock_p
        with (
            patch(
                "app.infrastructure.persistence.wechat_contact_store_impl.os.path.isfile",
                return_value=False,
            ),
            patch.dict("os.environ", {}, clear=False),
        ):
            os.environ.pop("WECHAT_CONTACT_DB_PATH", None)
            result = resolve_decrypt_contact_db_path()
            assert result is None

    @patch("app.infrastructure.plugins.wechat_plugin.get_wechat_plugin")
    def test_plugin_provides_path(self, mock_plugin):
        mock_p = MagicMock()
        mock_p.is_available.return_value = True
        mock_p.get_decrypted_db_path.return_value = "/path/to/contact.db"
        mock_plugin.return_value = mock_p
        with patch(
            "app.infrastructure.persistence.wechat_contact_store_impl.os.path.isfile",
            return_value=True,
        ):
            result = resolve_decrypt_contact_db_path()
            assert result == "/path/to/contact.db"

    @patch("app.utils.path_utils.get_base_dir", return_value="/tmp/nonexistent_base_xyz")
    @patch("app.infrastructure.plugins.wechat_plugin.get_wechat_plugin")
    def test_env_var_path(self, mock_plugin, mock_dir):
        mock_p = MagicMock()
        mock_p.is_available.return_value = False
        mock_p.get_decrypted_db_path.return_value = None
        mock_plugin.return_value = mock_p
        # Need to ensure the legacy path also doesn't exist
        with patch.dict("os.environ", {"WECHAT_CONTACT_DB_PATH": "/env/contact.db"}):
            # The function checks os.path.isfile for both legacy and env paths
            # We need isfile to return True only for the env path
            def isfile_side_effect(p):
                return p == "/env/contact.db"

            with patch("os.path.isfile", side_effect=isfile_side_effect):
                result = resolve_decrypt_contact_db_path()
                assert result == "/env/contact.db"


# ---------------------------------------------------------------------------
# _read_rows_from_contact_db
# ---------------------------------------------------------------------------


class TestReadRowsFromContactDb:
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.sqlite_conn")
    def test_reads_rows(self, mock_sqlite):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("user1", "Nick", "Remark", 0)]
        mock_conn.execute.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_sqlite.return_value = mock_conn

        result = _read_rows_from_contact_db("/path/to/db", 100)
        assert len(result) == 1
        assert result[0] == ("user1", "Nick", "Remark", 0)

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.sqlite_conn")
    def test_first_query_fails_tries_second(self, mock_sqlite):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("user2", "Name2", "Rem2", 1)]
        mock_conn.execute.side_effect = [RuntimeError("no column"), mock_cursor]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_sqlite.return_value = mock_conn

        result = _read_rows_from_contact_db("/path/to/db", 100)
        assert len(result) == 1

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.sqlite_conn")
    def test_all_queries_fail(self, mock_sqlite):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [RuntimeError("fail1"), RuntimeError("fail2")]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_sqlite.return_value = mock_conn

        result = _read_rows_from_contact_db("/path/to/db", 100)
        assert result == []


# ---------------------------------------------------------------------------
# SQLAlchemyWechatContactStore
# ---------------------------------------------------------------------------


class TestSqlAlchemyWechatContactStore:
    @pytest.fixture
    def store(self):
        return SQLAlchemyWechatContactStore()

    # add_contact
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_add_contact_empty_name(self, mock_get_db, store):
        result = store.add_contact(contact_name="")
        assert result["success"] is False
        assert "不能为空" in result["message"]

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_add_contact_whitespace_name(self, mock_get_db, store):
        result = store.add_contact(contact_name="   ")
        assert result["success"] is False

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_add_contact_invalid_type_defaults(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.add_contact(contact_name="测试", contact_type="invalid_type")
        assert result["success"] is True

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_add_contact_new(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_contact = MagicMock()
        mock_contact.id = 1
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.add_contact(contact_name="新联系人", wechat_id="wx123")
        assert result["success"] is True
        assert "添加成功" in result["message"]

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_add_contact_existing_updates(self, mock_get_db, store):
        mock_existing = MagicMock()
        mock_existing.id = 5
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_existing
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.add_contact(contact_name="更新名", wechat_id="wx123", is_starred=True)
        assert result["success"] is True
        assert "星标" in result["message"]

    # update_contact
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_update_contact_not_found(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.update_contact(999, {"contact_name": "新名"})
        assert result["success"] is False
        assert "不存在" in result["message"]

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_update_contact_empty_name(self, mock_get_db, store):
        mock_contact = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_contact
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.update_contact(1, {"contact_name": ""})
        assert result["success"] is False
        assert "不能为空" in result["message"]

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_update_contact_success(self, mock_get_db, store):
        mock_contact = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_contact
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.update_contact(1, {"contact_name": "新名", "remark": "备注"})
        assert result["success"] is True

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_update_contact_invalid_type(self, mock_get_db, store):
        mock_contact = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_contact
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.update_contact(1, {"contact_type": "invalid"})
        assert result["success"] is True
        assert mock_contact.contact_type == "contact"

    # delete_contact
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_delete_contact_not_found(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.delete_contact(999)
        assert result["success"] is False

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_delete_contact_success(self, mock_get_db, store):
        mock_contact = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_contact
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.delete_contact(1)
        assert result["success"] is True
        assert mock_contact.is_active == 0

    # unstar_all
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_unstar_all(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.update.return_value = 5
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.unstar_all()
        assert result["success"] is True
        assert result["count"] == 5

    # get_contact
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_get_contact_not_found(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.get_contact(999)
        assert result is None

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_get_contact_found(self, mock_get_db, store):
        mock_c = MagicMock()
        mock_c.id = 1
        mock_c.contact_name = "测试"
        mock_c.remark = ""
        mock_c.wechat_id = "wx123"
        mock_c.contact_type = "contact"
        mock_c.is_active = 1
        mock_c.is_starred = 0
        mock_c.created_at = None
        mock_c.updated_at = None
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_c
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.get_contact(1)
        assert result is not None
        assert result["contact_name"] == "测试"

    # get_context / save_context
    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_get_context_no_data(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.get_context(1)
        assert result == []

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_get_context_with_data(self, mock_get_db, store):
        mock_ctx = MagicMock()
        mock_ctx.context_json = json.dumps([{"role": "user", "content": "hello"}])
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_ctx
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.get_context(1)
        assert len(result) == 1
        assert result[0]["content"] == "hello"

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_save_context_new(self, mock_get_db, store):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.save_context(1, "wx123", [{"role": "user", "content": "hi"}])
        assert result is True

    @patch("app.infrastructure.persistence.wechat_contact_store_impl.get_db")
    def test_save_context_update(self, mock_get_db, store):
        mock_ctx = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_ctx
        mock_db.commit = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_get_db.return_value = mock_db

        result = store.save_context(1, "wx123", [{"role": "user", "content": "hi"}])
        assert result is True
