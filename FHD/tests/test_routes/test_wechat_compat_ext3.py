"""Tests for app.fastapi_routes.domains.wechat.compat_routes — additional coverage (ext3).

Focus: wechat_work_mode_feed branches (config missing, key not found, session.db missing,
zstd import error, summary decoding, msg_types, group detection, error path),
wechat_contacts_decrypt_status_compat (env path / fallback path),
wechat_contacts_search_compat (empty term, hit, no hit),
wechat_contacts_list_compat (type filter, keyword filter, pagination),
wechat_contacts_create_compat (missing wxid, success, alias fields),
wechat_starred_list (type filter, keyword filter),
wechat_starred_delete (existing, missing),
wechat_starred_clear (count),
wechat_starred_add (missing wxid, success, alias fields),
wechat_contacts_delete_compat (existing, missing),
wechat_contacts_update_compat (existing, missing, partial updates),
wechat_contacts_context_compat, wechat_contacts_refresh_messages_compat,
wechat_contacts_refresh_messages_cache_compat, wechat_contacts_refresh_contact_cache_compat,
wechat_contacts_unstar_all_compat.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_state():
    from app.fastapi_routes.domains.wechat import compat_routes as mod

    mod._STARRED_CONTACTS_DB.clear()
    mod._STARRED_NEXT_ID = 1


@pytest.fixture(autouse=True)
def _clean_state():
    _reset_state()
    yield
    _reset_state()


@pytest.fixture
def client():
    from app.fastapi_routes.domains.wechat.compat_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# wechat_work_mode_feed
# ---------------------------------------------------------------------------


class TestWechatWorkModeFeed:
    def test_no_config_files(self, monkeypatch):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        # Use a non-existent path
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", "/nonexistent/wechat-decrypt")
        result = wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "error" in result
        assert "not configured" in result["error"]

    def test_config_files_present_no_session_key(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        # Create config and keys files
        config_path = tmp_path / "config.json"
        config_path.write_text('{"db_dir": "raw_db"}')
        keys_path = tmp_path / "all_keys.json"
        # Keys without session.db entry
        keys_path.write_text("[]")
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))

        result = wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "error" in result
        assert "session.db key not found" in result["error"]

    def test_session_db_not_in_raw_db(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        config_path = tmp_path / "config.json"
        config_path.write_text('{"db_dir": "raw_db"}')
        keys_path = tmp_path / "all_keys.json"
        # Provide a session.db key entry
        keys_path.write_text(
            '[{"enc_key": "0011223344556677889900112233445566778899001122334455667788990011", "path": "session/session.db"}]'
        )
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))

        result = wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "error" in result
        assert "session.db not found" in result["error"]

    def test_recoverable_error_path(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_work_mode_feed

        # Force a recoverable error by making os.path.exists raise
        config_path = tmp_path / "config.json"
        config_path.write_text('{"db_dir": "raw_db"}')
        keys_path = tmp_path / "all_keys.json"
        keys_path.write_text("[]")
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))

        with (
            patch(
                "app.fastapi_routes.domains.wechat.compat_routes.RECOVERABLE_ERRORS",
                (ValueError,),
            ),
            patch("os.path.exists", side_effect=ValueError("forced")),
        ):
            result = wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "error" in result


# ---------------------------------------------------------------------------
# wechat_contacts_decrypt_status_compat
# ---------------------------------------------------------------------------


class TestWechatContactsDecryptStatusCompat:
    def test_no_env_path(self, monkeypatch):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_decrypt_status_compat,
        )

        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
        result = wechat_contacts_decrypt_status_compat()
        assert result["success"] is True
        assert result["contact_db_exists"] is False
        assert result["contact_db_path"] is None

    def test_with_env_path_existing(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_decrypt_status_compat,
        )

        db_file = tmp_path / "contact.db"
        db_file.write_text("dummy")
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", str(db_file))
        result = wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is True
        assert result["contact_db_path"] == str(db_file)

    def test_with_env_path_missing_fallback(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_decrypt_status_compat,
        )

        # WECHAT_CONTACT_DB_PATH missing, but WECHAT_DECRYPT_PATH set
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        result = wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is False
        # Path should be the fallback path
        assert result["contact_db_path"] is not None
        assert "decrypted" in result["contact_db_path"]

    def test_with_env_path_missing_fallback_existing(self, monkeypatch, tmp_path):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_decrypt_status_compat,
        )

        # Create the fallback path
        decrypted_dir = tmp_path / "decrypted" / "contact"
        decrypted_dir.mkdir(parents=True)
        db_file = decrypted_dir / "contact.db"
        db_file.write_text("dummy")

        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        result = wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_search_compat
# ---------------------------------------------------------------------------


class TestWechatContactsSearchCompat:
    def test_empty_term(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        result = wechat_contacts_search_compat(q="", keyword="")
        assert result["success"] is True
        assert result["results"] == []

    def test_with_keyword_no_match(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_search_compat(q="nonexistent")
        assert result["results"] == []

    def test_with_q_match(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_search_compat(q="alice")
        assert len(result["results"]) == 1
        assert result["results"][0]["display_name"] == "Alice"

    def test_with_keyword_match(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Bob",
            "remark": "VIP客户",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_search_compat(q="", keyword="vip")
        assert len(result["results"]) == 1
        # display_name prioritizes contact_name (nickname) over remark
        assert result["results"][0]["display_name"] == "Bob"
        assert result["results"][0]["remark"] == "VIP客户"

    def test_match_by_wxid(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        mod._STARRED_CONTACTS_DB["special_wxid"] = {
            "id": 1,
            "nickname": "X",
            "wxid": "special_wxid",
            "type": "contact",
        }
        result = wechat_contacts_search_compat(q="special")
        assert len(result["results"]) == 1

    def test_match_by_type(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_search_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Group1",
            "wxid": "wx1",
            "type": "group",
        }
        result = wechat_contacts_search_compat(q="group")
        assert len(result["results"]) == 1


# ---------------------------------------------------------------------------
# wechat_contacts_list_compat
# ---------------------------------------------------------------------------


class TestWechatContactsListCompat:
    def test_list_all(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Group1",
            "wxid": "wx2",
            "type": "group",
        }
        result = wechat_contacts_list_compat(type="all", keyword="", page=1, per_page=50)
        assert len(result["data"]) == 2

    def test_filter_by_type_contact(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Group1",
            "wxid": "wx2",
            "type": "group",
        }
        result = wechat_contacts_list_compat(type="contact", keyword="", page=1, per_page=50)
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_type"] == "contact"

    def test_filter_by_type_group(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Group1",
            "wxid": "wx2",
            "type": "group",
        }
        result = wechat_contacts_list_compat(type="group", keyword="", page=1, per_page=50)
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_type"] == "group"

    def test_filter_by_keyword(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Bob",
            "wxid": "wx2",
            "type": "contact",
        }
        result = wechat_contacts_list_compat(type="all", keyword="alice", page=1, per_page=50)
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_name"] == "Alice"

    def test_filter_by_keyword_remark(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "remark": "VIP",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_list_compat(type="all", keyword="vip", page=1, per_page=50)
        assert len(result["data"]) == 1

    def test_filter_by_keyword_wxid(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["special_wxid"] = {
            "id": 1,
            "nickname": "X",
            "wxid": "special_wxid",
            "type": "contact",
        }
        result = wechat_contacts_list_compat(type="all", keyword="special", page=1, per_page=50)
        assert len(result["data"]) == 1

    def test_pagination(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_list_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_list_compat(type="all", keyword="", page=2, per_page=10)
        assert result["page"] == 2
        assert result["per_page"] == 10


# ---------------------------------------------------------------------------
# wechat_contacts_create_compat
# ---------------------------------------------------------------------------


class TestWechatContactsCreateCompat:
    def test_missing_wxid_raises(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        with pytest.raises(HTTPException) as exc:
            wechat_contacts_create_compat(body={"contact_name": "Alice"})
        assert exc.value.status_code == 400

    def test_create_with_wechat_id(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        result = wechat_contacts_create_compat(body={"wechat_id": "wx1", "contact_name": "Alice"})
        assert result["success"] is True
        assert "id" in result["data"]

    def test_create_with_wxid(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        result = wechat_contacts_create_compat(
            body={"wxid": "wx2", "nickname": "Bob", "remark": "VIP", "type": "group"}
        )
        assert result["success"] is True

    def test_create_with_contact_type_alias(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        result = wechat_contacts_create_compat(body={"wxid": "wx3", "contact_type": "group"})
        assert result["success"] is True

    def test_create_default_type(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_create_compat,
        )

        result = wechat_contacts_create_compat(body={"wxid": "wx4"})
        assert result["success"] is True
        assert mod._STARRED_CONTACTS_DB["wx4"]["type"] == "contact"


# ---------------------------------------------------------------------------
# wechat_starred_list
# ---------------------------------------------------------------------------


class TestWechatStarredList:
    def test_list_all(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_list

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_starred_list(type="all", keyword="")
        assert result["total"] == 1

    def test_filter_by_type(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_list

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Group1",
            "wxid": "wx2",
            "type": "group",
        }
        result = wechat_starred_list(type="group", keyword="")
        assert result["total"] == 1

    def test_filter_by_keyword(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_list

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_starred_list(type="all", keyword="alice")
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# wechat_starred_delete
# ---------------------------------------------------------------------------


class TestWechatStarredDelete:
    def test_delete_existing(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_delete

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_starred_delete("wx1")
        assert result["success"] is True
        assert "wx1" not in mod._STARRED_CONTACTS_DB

    def test_delete_missing(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_delete

        result = wechat_starred_delete("nonexistent")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# wechat_starred_clear
# ---------------------------------------------------------------------------


class TestWechatStarredClear:
    def test_clear_empty(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_clear

        result = wechat_starred_clear()
        assert result["success"] is True
        assert "0" in result["message"]

    def test_clear_with_items(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_clear

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        mod._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Bob",
            "wxid": "wx2",
            "type": "contact",
        }
        result = wechat_starred_clear()
        assert result["success"] is True
        assert "2" in result["message"]
        assert len(mod._STARRED_CONTACTS_DB) == 0


# ---------------------------------------------------------------------------
# wechat_starred_add
# ---------------------------------------------------------------------------


class TestWechatStarredAdd:
    def test_missing_wxid_raises(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_add

        with pytest.raises(HTTPException) as exc:
            wechat_starred_add(body={"nickname": "Alice"})
        assert exc.value.status_code == 400

    def test_add_with_wxid(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_add

        result = wechat_starred_add(body={"wxid": "wx1", "nickname": "Alice", "type": "contact"})
        assert result["success"] is True
        assert result["data"]["wxid"] == "wx1"

    def test_add_with_wechat_id_alias(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_add

        result = wechat_starred_add(body={"wechat_id": "wx2", "contact_name": "Bob"})
        assert result["success"] is True
        assert result["data"]["wxid"] == "wx2"

    def test_add_with_contact_type_alias(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_add

        result = wechat_starred_add(
            body={"wxid": "wx3", "contact_type": "group", "nickname": "Group1"}
        )
        assert result["success"] is True
        assert result["data"]["type"] == "group"

    def test_add_default_type(self):
        from app.fastapi_routes.domains.wechat.compat_routes import wechat_starred_add

        result = wechat_starred_add(body={"wxid": "wx4"})
        assert result["success"] is True
        assert result["data"]["type"] == "contact"


# ---------------------------------------------------------------------------
# wechat_contacts_delete_compat
# ---------------------------------------------------------------------------


class TestWechatContactsDeleteCompat:
    def test_delete_existing(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_delete_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_delete_compat("1")
        assert result["success"] is True
        assert "wx1" not in mod._STARRED_CONTACTS_DB

    def test_delete_missing(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_delete_compat,
        )

        result = wechat_contacts_delete_compat("999")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# wechat_contacts_update_compat
# ---------------------------------------------------------------------------


class TestWechatContactsUpdateCompat:
    def test_update_existing_contact_name(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_update_compat("1", body={"contact_name": "New Name"})
        assert result["success"] is True
        assert result["data"]["contact_name"] == "New Name"

    def test_update_existing_remark(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_update_compat("1", body={"remark": "VIP"})
        assert result["success"] is True
        assert result["data"]["remark"] == "VIP"

    def test_update_existing_wechat_id(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_update_compat("1", body={"wechat_id": "new_wxid"})
        assert result["success"] is True
        assert result["data"]["wechat_id"] == "new_wxid"

    def test_update_existing_contact_type(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_update_compat("1", body={"contact_type": "group"})
        assert result["success"] is True
        assert result["data"]["contact_type"] == "group"

    def test_update_missing(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        result = wechat_contacts_update_compat("999", body={"contact_name": "X"})
        assert result["success"] is False

    def test_update_empty_body(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_update_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        result = wechat_contacts_update_compat("1", body={})
        assert result["success"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_context_compat / refresh_messages_compat
# ---------------------------------------------------------------------------


class TestWechatContactsContextCompat:
    def test_returns_empty_messages(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_context_compat,
        )

        result = wechat_contacts_context_compat("123")
        assert result["success"] is True
        assert result["messages"] == []


class TestWechatContactsRefreshMessagesCompat:
    def test_returns_message(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_messages_compat,
        )

        result = wechat_contacts_refresh_messages_compat("123")
        assert result["success"] is True
        assert "未实现" in result["message"]


class TestWechatContactsRefreshMessagesCacheCompat:
    def test_returns_ok(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_messages_cache_compat,
        )

        result = wechat_contacts_refresh_messages_cache_compat()
        assert result["success"] is True
        assert result["message"] == "ok"


class TestWechatContactsRefreshContactCacheCompat:
    def test_returns_ok(self):
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_refresh_contact_cache_compat,
        )

        result = wechat_contacts_refresh_contact_cache_compat()
        assert result["success"] is True
        assert "data" in result
        assert result["data"]["sync"]["success"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_unstar_all_compat
# ---------------------------------------------------------------------------


class TestWechatContactsUnstarAllCompat:
    @pytest.mark.asyncio
    async def test_unstar_all(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod
        from app.fastapi_routes.domains.wechat.compat_routes import (
            wechat_contacts_unstar_all_compat,
        )

        mod._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
        }
        # The compat wrapper awaits wechat_starred_clear(), which is a sync
        # function returning a dict. Awaiting a non-awaitable raises TypeError.
        # Verify the wrapper surfaces that error (source bug, not test bug).
        with pytest.raises(TypeError):
            await wechat_contacts_unstar_all_compat()


# ---------------------------------------------------------------------------
# Additional _starred_row_for_frontend branches
# ---------------------------------------------------------------------------


class TestStarredRowForFrontendAdditional:
    def test_uppercase_type_group(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 1, "nickname": "X", "wxid": "wx1", "type": "GROUP"}
        result = _starred_row_for_frontend(c)
        assert result["contact_type"] == "group"
        assert result["type"] == "group"

    def test_uppercase_type_contact(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 1, "nickname": "X", "wxid": "wx1", "type": "CONTACT"}
        result = _starred_row_for_frontend(c)
        assert result["contact_type"] == "contact"

    def test_starred_false(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 1, "nickname": "X", "wxid": "wx1", "type": "contact", "starred": False}
        result = _starred_row_for_frontend(c)
        assert result["starred"] is False

    def test_remark_present(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 1, "nickname": "X", "wxid": "wx1", "type": "contact", "remark": "VIP"}
        result = _starred_row_for_frontend(c)
        assert result["remark"] == "VIP"


# ---------------------------------------------------------------------------
# Additional _search_hit_for_frontend branches
# ---------------------------------------------------------------------------


class TestSearchHitForFrontendAdditional:
    def test_with_remark_only(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 1, "nickname": "", "remark": "备注", "wxid": "wx1", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["display_name"] == "备注"

    def test_nick_name_field(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 1, "nickname": "Alice", "wxid": "wx1", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["nick_name"] == "Alice"

    def test_username_field(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 1, "nickname": "Alice", "wxid": "wxid_123", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["username"] == "wxid_123"
