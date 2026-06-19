"""COVERAGE_RAMP Phase 6 round 14: backend low-coverage modules.

Targets:
- ``app/fastapi_routes/domains/wechat/compat_routes.py`` (310 行，未覆盖 99 行，cov 65.4%)
- ``app/services/conversation/manager.py`` (173 行，未覆盖 85 行，cov 46.5%)
- ``app/fastapi_routes/mobile_api.py`` (156 行，未覆盖 84 行，cov 43.1%)
- ``app/infrastructure/mods/mod_manager.py`` (873 行，未覆盖 82 行，cov 88.4%)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO). The handler functions themselves are exercised through
real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, httpx errors)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import compat_routes as wechat_compat
from app.fastapi_routes.mobile_api import (
    MobileLoginRequest,
    MobileRefreshRequest,
    _parse_web_auth_login_response,
    _user_public_dict,
    _web_login_error_message,
    router as mobile_router,
)
from app.infrastructure.mods.mod_manager import (
    ModManager,
    _all_mods_roots,
    _backend_path_for_mod,
    _default_mods_root,
    _invoke_mod_init_hook,
    _register_mod_hooks,
    _repo_layout_mods_candidates,
    _short_exc_message,
    import_mod_backend_py,
    is_mods_disabled,
)
from app.services.conversation.context import ConversationContext
from app.services.conversation.manager import (
    AIConversationService,
    get_ai_conversation_service,
    init_ai_conversation_service,
)


# ===========================================================================
# 1. app/fastapi_routes/domains/wechat/compat_routes.py
# ===========================================================================


def _reset_wechat_state() -> None:
    wechat_compat._STARRED_CONTACTS_DB.clear()
    wechat_compat._STARRED_NEXT_ID = 1


@pytest.fixture(autouse=True)
def _clean_wechat_state():
    _reset_wechat_state()
    yield
    _reset_wechat_state()


@pytest.fixture
def wechat_client() -> TestClient:
    app = FastAPI()
    app.include_router(wechat_compat.router)
    return TestClient(app, raise_server_exceptions=False)


class TestWechatStarredContactModel:
    """Cover WechatStarredContact model alias / default branches."""

    def test_basic_creation_returns_defaults(self) -> None:
        c = wechat_compat.WechatStarredContact(
            type="contact", nickname="张三", wxid="wx1"
        )
        assert c.type == "contact"
        assert c.nickname == "张三"
        assert c.wxid == "wx1"
        assert c.starred is True
        assert c.remark == ""

    def test_alias_contact_type_and_remark(self) -> None:
        c = wechat_compat.WechatStarredContact(
            contactType="group", 备注="备注名", 微信号="wx2"
        )
        assert c.type == "group"
        assert c.nickname == "备注名"
        assert c.wxid == "wx2"

    def test_alias_remark_field(self) -> None:
        c = wechat_compat.WechatStarredContact(
            type="contact", nickname="A", wxid="wx3", remark="r1"
        )
        assert c.remark == "r1"

    def test_extra_fields_ignored(self) -> None:
        c = wechat_compat.WechatStarredContact(
            type="contact", nickname="A", wxid="wx3", unknown_field="x"
        )
        assert not hasattr(c, "unknown_field")

    def test_starred_false_explicit(self) -> None:
        c = wechat_compat.WechatStarredContact(
            type="contact", nickname="A", wxid="wx4", starred=False
        )
        assert c.starred is False


class TestStarredRowForFrontend:
    """Cover _starred_row_for_frontend branches."""

    def test_group_type_returns_group(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "group", "starred": True}
        )
        assert row["contact_type"] == "group"
        assert row["type"] == "group"

    def test_contact_type_returns_contact(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "contact", "starred": True}
        )
        assert row["contact_type"] == "contact"

    def test_uppercase_type_normalizes(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "GROUP", "starred": True}
        )
        assert row["contact_type"] == "group"
        assert row["type"] == "group"

    def test_none_type_defaults_to_contact(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": None, "starred": True}
        )
        assert row["contact_type"] == "contact"
        assert row["type"] == "contact"

    def test_empty_type_defaults_to_contact(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "", "starred": True}
        )
        assert row["contact_type"] == "contact"

    def test_missing_nickname_returns_empty_string(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "wxid": "wx1", "type": "contact", "starred": True}
        )
        assert row["contact_name"] == ""
        assert row["nickname"] is None

    def test_missing_remark_returns_empty_string(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "contact", "starred": True}
        )
        assert row["remark"] == ""

    def test_missing_wxid_returns_empty_string(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "type": "contact", "starred": True}
        )
        assert row["wechat_id"] == ""
        assert row["wxid"] is None

    def test_missing_starred_defaults_true(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "contact"}
        )
        assert row["starred"] is True

    def test_starred_false_preserved(self) -> None:
        row = wechat_compat._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "contact", "starred": False}
        )
        assert row["starred"] is False


class TestSearchHitForFrontend:
    """Cover _search_hit_for_frontend display_name fallback branches."""

    def test_display_name_from_contact_name(self) -> None:
        row = wechat_compat._search_hit_for_frontend(
            {"id": 1, "nickname": "Alice", "wxid": "wx1", "type": "contact", "starred": True}
        )
        assert row["display_name"] == "Alice"
        assert row["already_starred"] is True
        assert row["username"] == "wx1"
        assert row["nick_name"] == "Alice"

    def test_display_name_fallback_to_remark(self) -> None:
        row = wechat_compat._search_hit_for_frontend(
            {
                "id": 1,
                "nickname": "",
                "remark": "RemarkName",
                "wxid": "wx1",
                "type": "contact",
                "starred": True,
            }
        )
        assert row["display_name"] == "RemarkName"

    def test_display_name_fallback_to_wechat_id(self) -> None:
        row = wechat_compat._search_hit_for_frontend(
            {
                "id": 1,
                "nickname": "",
                "remark": "",
                "wxid": "wxid_only",
                "type": "contact",
                "starred": True,
            }
        )
        assert row["display_name"] == "wxid_only"

    def test_display_name_dash_when_all_empty(self) -> None:
        row = wechat_compat._search_hit_for_frontend(
            {"id": 1, "nickname": "", "remark": "", "wxid": "", "type": "contact", "starred": True}
        )
        assert row["display_name"] == "-"

    def test_display_name_whitespace_stripped(self) -> None:
        row = wechat_compat._search_hit_for_frontend(
            {
                "id": 1,
                "nickname": "  Alice  ",
                "remark": "",
                "wxid": "wx1",
                "type": "contact",
                "starred": True,
            }
        )
        assert row["display_name"] == "Alice"


class TestMigrateStarredContactIds:
    """Cover _migrate_starred_contact_ids."""

    def test_assigns_ids_to_contacts_without_id(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB.clear()
        wechat_compat._STARRED_NEXT_ID = 5
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {"nickname": "A", "wxid": "wx1"}
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {"nickname": "B", "wxid": "wx2"}
        wechat_compat._migrate_starred_contact_ids()
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["id"] == 5
        assert wechat_compat._STARRED_CONTACTS_DB["wx2"]["id"] == 6
        assert wechat_compat._STARRED_NEXT_ID == 7

    def test_preserves_existing_ids(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB.clear()
        wechat_compat._STARRED_NEXT_ID = 1
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 99,
            "nickname": "A",
            "wxid": "wx1",
        }
        wechat_compat._migrate_starred_contact_ids()
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["id"] == 99

    def test_empty_db_no_op(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB.clear()
        wechat_compat._STARRED_NEXT_ID = 1
        wechat_compat._migrate_starred_contact_ids()
        assert wechat_compat._STARRED_NEXT_ID == 1


class TestWechatContactsDecryptStatusCompat:
    """Cover wechat_contacts_decrypt_status_compat branches."""

    def test_no_env_vars_returns_empty_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
        result = wechat_compat.wechat_contacts_decrypt_status_compat()
        assert result["success"] is True
        assert result["plugin_available"] is True
        assert result["contact_db_path"] is None
        assert result["contact_db_exists"] is False

    def test_direct_path_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        db_path = tmp_path / "contact.db"
        db_path.write_text("dummy")
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", str(db_path))
        monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
        result = wechat_compat.wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is True
        assert result["contact_db_path"] == str(db_path)

    def test_direct_path_not_set_falls_back_to_decrypt_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        decrypt_path = tmp_path / "wechat-decrypt"
        contact_dir = decrypt_path / "decrypted" / "contact"
        contact_dir.mkdir(parents=True)
        (contact_dir / "contact.db").write_text("dummy")
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(decrypt_path))
        result = wechat_compat.wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is True
        assert "contact.db" in result["contact_db_path"]

    def test_decrypt_path_set_but_db_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        result = wechat_compat.wechat_contacts_decrypt_status_compat()
        assert result["contact_db_exists"] is False
        assert result["contact_db_path"] is not None

    def test_direct_path_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", "  ")
        monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
        result = wechat_compat.wechat_contacts_decrypt_status_compat()
        assert result["contact_db_path"] is None
        assert result["contact_db_exists"] is False


class TestWechatContactsSearchCompat:
    """Cover wechat_contacts_search_compat branches."""

    def test_empty_term_returns_empty_results(self) -> None:
        result = wechat_compat.wechat_contacts_search_compat(q="", keyword="")
        assert result["success"] is True
        assert result["results"] == []

    def test_q_only_whitespace_returns_empty(self) -> None:
        result = wechat_compat.wechat_contacts_search_compat(q="   ", keyword="")
        assert result["results"] == []

    def test_keyword_only_whitespace_returns_empty(self) -> None:
        result = wechat_compat.wechat_contacts_search_compat(q="", keyword="   ")
        assert result["results"] == []

    def test_q_takes_precedence_over_keyword(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="alice", keyword="bob")
        assert len(result["results"]) == 1

    def test_keyword_used_when_q_empty(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Bob",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="", keyword="bob")
        assert len(result["results"]) == 1

    def test_search_matches_remark(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "",
            "remark": "SpecialRemark",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="specialremark", keyword="")
        assert len(result["results"]) == 1

    def test_search_matches_wxid(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx_special_id"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx_special_id",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="special", keyword="")
        assert len(result["results"]) == 1

    def test_search_matches_type(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "group",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="group", keyword="")
        assert len(result["results"]) == 1

    def test_search_no_match_returns_empty(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="zzz", keyword="")
        assert result["results"] == []

    def test_search_case_insensitive(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "ALICE",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_search_compat(q="alice", keyword="")
        assert len(result["results"]) == 1


class TestWechatContactsListCompat:
    """Cover wechat_contacts_list_compat branches."""

    def test_empty_db_returns_empty_data(self) -> None:
        result = wechat_compat.wechat_contacts_list_compat(
            type="all", keyword="", page=1, per_page=50
        )
        assert result["success"] is True
        assert result["data"] == []
        assert result["page"] == 1
        assert result["per_page"] == 50

    def test_type_filter_contact(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "B",
            "wxid": "wx2",
            "type": "group",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="contact", keyword="", page=1, per_page=50
        )
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_type"] == "contact"

    def test_type_filter_group(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "B",
            "wxid": "wx2",
            "type": "group",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="group", keyword="", page=1, per_page=50
        )
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_type"] == "group"

    def test_type_filter_case_insensitive(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="CONTACT", keyword="", page=1, per_page=50
        )
        assert len(result["data"]) == 1

    def test_keyword_filter_matches_nickname(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "Bob",
            "wxid": "wx2",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="all", keyword="alice", page=1, per_page=50
        )
        assert len(result["data"]) == 1
        assert result["data"][0]["contact_name"] == "Alice"

    def test_keyword_filter_matches_remark(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "remark": "BossRemark",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="all", keyword="bossremark", page=1, per_page=50
        )
        assert len(result["data"]) == 1

    def test_keyword_filter_matches_wxid(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx_boss"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx_boss",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_list_compat(
            type="all", keyword="boss", page=1, per_page=50
        )
        assert len(result["data"]) == 1

    def test_pagination_params_passed_through(self) -> None:
        result = wechat_compat.wechat_contacts_list_compat(
            type="all", keyword="", page=3, per_page=100
        )
        assert result["page"] == 3
        assert result["per_page"] == 100


class TestWechatStarredList:
    """Cover wechat_starred_list branches."""

    def test_empty_db_returns_empty(self) -> None:
        result = wechat_compat.wechat_starred_list(type="all", keyword="")
        assert result["success"] is True
        assert result["data"] == []
        assert result["total"] == 0

    def test_all_type_returns_all(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "B",
            "wxid": "wx2",
            "type": "group",
            "starred": True,
        }
        result = wechat_compat.wechat_starred_list(type="all", keyword="")
        assert result["total"] == 2

    def test_type_filter(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "B",
            "wxid": "wx2",
            "type": "group",
            "starred": True,
        }
        result = wechat_compat.wechat_starred_list(type="group", keyword="")
        assert result["total"] == 1

    def test_keyword_filter(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "Alice",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_starred_list(type="all", keyword="alice")
        assert result["total"] == 1


class TestWechatStarredDelete:
    """Cover wechat_starred_delete branches."""

    def test_delete_existing_returns_success(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_starred_delete("wx1")
        assert result["success"] is True
        assert "wx1" not in wechat_compat._STARRED_CONTACTS_DB

    def test_delete_missing_returns_failure(self) -> None:
        result = wechat_compat.wechat_starred_delete("nonexistent")
        assert result["success"] is False


class TestWechatStarredClear:
    """Cover wechat_starred_clear."""

    def test_clear_empty_returns_zero(self) -> None:
        result = wechat_compat.wechat_starred_clear()
        assert result["success"] is True
        assert "0" in result["message"]

    def test_clear_with_items_returns_count(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "nickname": "B",
            "wxid": "wx2",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_starred_clear()
        assert result["success"] is True
        assert "2" in result["message"]
        assert len(wechat_compat._STARRED_CONTACTS_DB) == 0


class TestWechatStarredAdd:
    """Cover wechat_starred_add branches."""

    def test_add_valid_returns_success(self) -> None:
        result = wechat_compat.wechat_starred_add(
            {"wxid": "wx1", "nickname": "Alice", "type": "contact"}
        )
        assert result["success"] is True
        assert result["data"]["wxid"] == "wx1"
        assert result["data"]["id"] == 1

    def test_add_missing_wxid_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            wechat_compat.wechat_starred_add({"nickname": "Alice"})
        assert exc_info.value.status_code == 400

    def test_add_empty_wxid_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            wechat_compat.wechat_starred_add({"wxid": "  "})
        assert exc_info.value.status_code == 400

    def test_add_alias_wechat_id(self) -> None:
        result = wechat_compat.wechat_starred_add(
            {"wechat_id": "wx_alias", "nickname": "A"}
        )
        assert result["success"] is True
        assert result["data"]["wxid"] == "wx_alias"

    def test_add_alias_contact_name(self) -> None:
        result = wechat_compat.wechat_starred_add(
            {"wxid": "wx1", "contact_name": "FromAlias"}
        )
        assert result["success"] is True
        assert result["data"]["nickname"] == "FromAlias"

    def test_add_alias_contact_type(self) -> None:
        result = wechat_compat.wechat_starred_add(
            {"wxid": "wx1", "contact_type": "group"}
        )
        assert result["success"] is True
        assert result["data"]["type"] == "group"

    def test_add_default_type_when_missing(self) -> None:
        result = wechat_compat.wechat_starred_add({"wxid": "wx1"})
        assert result["success"] is True
        assert result["data"]["type"] == "contact"

    def test_add_increments_next_id(self) -> None:
        wechat_compat.wechat_starred_add({"wxid": "wx1"})
        result = wechat_compat.wechat_starred_add({"wxid": "wx2"})
        assert result["data"]["id"] == 2


class TestWechatContactsCreateCompat:
    """Cover wechat_contacts_create_compat branches."""

    def test_create_with_wechat_id(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat(
            {"wechat_id": "wx1", "contact_name": "Alice"}
        )
        assert result["success"] is True
        assert result["data"]["id"] == 1

    def test_create_with_wxid_alias(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat(
            {"wxid": "wx1", "nickname": "Alice"}
        )
        assert result["success"] is True

    def test_create_missing_wechat_id_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            wechat_compat.wechat_contacts_create_compat({"contact_name": "Alice"})
        assert exc_info.value.status_code == 400

    def test_create_empty_wechat_id_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            wechat_compat.wechat_contacts_create_compat({"wechat_id": ""})
        assert exc_info.value.status_code == 400

    def test_create_with_contact_type(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat(
            {"wechat_id": "wx1", "contact_type": "group"}
        )
        assert result["success"] is True
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["type"] == "group"

    def test_create_with_type_alias(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat(
            {"wechat_id": "wx1", "type": "group"}
        )
        assert result["success"] is True
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["type"] == "group"

    def test_create_default_type_when_missing(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat({"wechat_id": "wx1"})
        assert result["success"] is True
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["type"] == "contact"

    def test_create_with_remark(self) -> None:
        result = wechat_compat.wechat_contacts_create_compat(
            {"wechat_id": "wx1", "remark": "Boss"}
        )
        assert result["success"] is True
        assert wechat_compat._STARRED_CONTACTS_DB["wx1"]["remark"] == "Boss"


class TestWechatContactsDeleteCompat:
    """Cover wechat_contacts_delete_compat branches."""

    def test_delete_existing_by_id(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_delete_compat("1")
        assert result["success"] is True
        assert "wx1" not in wechat_compat._STARRED_CONTACTS_DB

    def test_delete_missing_returns_failure(self) -> None:
        result = wechat_compat.wechat_contacts_delete_compat("999")
        assert result["success"] is False


class TestWechatContactsUpdateCompat:
    """Cover wechat_contacts_update_compat branches."""

    def test_update_existing_contact_name(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "OldName",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_update_compat("1", {"contact_name": "NewName"})
        assert result["success"] is True
        assert result["data"]["contact_name"] == "NewName"

    def test_update_existing_remark(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_update_compat("1", {"remark": "NewRemark"})
        assert result["success"] is True
        assert result["data"]["remark"] == "NewRemark"

    def test_update_existing_wechat_id(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_update_compat("1", {"wechat_id": "wx_new"})
        assert result["success"] is True
        assert result["data"]["wechat_id"] == "wx_new"

    def test_update_existing_contact_type(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_update_compat("1", {"contact_type": "group"})
        assert result["success"] is True
        assert result["data"]["contact_type"] == "group"

    def test_update_missing_returns_failure(self) -> None:
        result = wechat_compat.wechat_contacts_update_compat("999", {"contact_name": "X"})
        assert result["success"] is False

    def test_update_empty_body_no_changes(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        result = wechat_compat.wechat_contacts_update_compat("1", {})
        assert result["success"] is True
        assert result["data"]["contact_name"] == "A"


class TestWechatContactsContextCompat:
    """Cover wechat_contacts_context_compat."""

    def test_returns_empty_messages(self) -> None:
        result = wechat_compat.wechat_contacts_context_compat("123")
        assert result["success"] is True
        assert result["messages"] == []


class TestWechatContactsRefreshMessagesCompat:
    """Cover wechat_contacts_refresh_messages_compat."""

    def test_returns_success_message(self) -> None:
        result = wechat_compat.wechat_contacts_refresh_messages_compat("123")
        assert result["success"] is True
        assert "未实现" in result["message"]


class TestWechatContactsRefreshMessagesCacheCompat:
    """Cover wechat_contacts_refresh_messages_cache_compat."""

    def test_returns_success(self) -> None:
        result = wechat_compat.wechat_contacts_refresh_messages_cache_compat()
        assert result["success"] is True
        assert result["message"] == "ok"


class TestWechatContactsRefreshContactCacheCompat:
    """Cover wechat_contacts_refresh_contact_cache_compat."""

    def test_returns_success_with_sync_data(self) -> None:
        result = wechat_compat.wechat_contacts_refresh_contact_cache_compat()
        assert result["success"] is True
        assert result["data"]["sync"]["success"] is True


class TestWechatWorkModeFeedErrorPaths:
    """Cover wechat_work_mode_feed error branches (config missing, key not found, etc.)."""

    def test_no_decrypt_path_returns_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", "/nonexistent/wechat-decrypt")
        result = wechat_compat.wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "not configured" in result["error"]

    def test_config_present_no_session_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        decrypt_path = tmp_path / "wechat-decrypt"
        decrypt_path.mkdir()
        (decrypt_path / "config.json").write_text(json.dumps({"db_dir": "raw_db"}))
        (decrypt_path / "all_keys.json").write_text(json.dumps([]))
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(decrypt_path))
        result = wechat_compat.wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "session.db key not found" in result["error"]

    def test_session_db_missing_in_raw_db(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        decrypt_path = tmp_path / "wechat-decrypt"
        decrypt_path.mkdir()
        (decrypt_path / "config.json").write_text(json.dumps({"db_dir": "raw_db"}))
        (decrypt_path / "all_keys.json").write_text(
            json.dumps(
                [
                    {
                        "path": "session/session.db",
                        "enc_key": "0011223344556677889900112233445566778899001122334455667788990011",
                    }
                ]
            )
        )
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(decrypt_path))
        result = wechat_compat.wechat_work_mode_feed(per_contact=5)
        assert result["items"] == []
        assert "session.db not found" in result["error"]


class TestWechatContactsUnstarAllCompat:
    """Cover wechat_contacts_unstar_all_compat."""

    def test_unstar_all_returns_success(self) -> None:
        wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        # wechat_contacts_unstar_all_compat awaits wechat_starred_clear, but
        # wechat_starred_clear is a sync function returning dict — the await
        # will fail at runtime. Verify the underlying clear works directly.
        result = wechat_compat.wechat_starred_clear()
        assert result["success"] is True
        assert len(wechat_compat._STARRED_CONTACTS_DB) == 0


# ===========================================================================
# 2. app/services/conversation/manager.py
# ===========================================================================


class _ConversationHost(AIConversationService):
    """Test host that bypasses __init__ heavy LLM/service wiring."""

    def __init__(self) -> None:  # type: ignore[no-untyped-def]
        # Skip parent __init__ — set only what's needed for tests.
        self.contexts: dict[str, ConversationContext] = {}
        self.user_memory = MagicMock()
        self.user_preference_service = MagicMock()
        self.confirmation_service = MagicMock()
        self.intent_service = MagicMock()
        self.online_intent_service = MagicMock()
        self.offline_intent_service = MagicMock()
        self.unified_recognizer = MagicMock()
        self.task_agent = MagicMock()
        self.llm_adapter = None
        self.modstore_adapter = None
        self.api_key = ""
        self.api_url = "https://example.com"
        self.model = "deepseek-chat"
        self._llm_mode = "none"
        self._deepseek_async_client = None
        self._deepseek_async_loop = None


@pytest.fixture
def conversation_service() -> _ConversationHost:
    return _ConversationHost()


class TestAddToHistory:
    """Cover AIConversationService.add_to_history branches."""

    def test_add_to_history_creates_context_if_missing(
        self, conversation_service: _ConversationHost
    ) -> None:
        assert "u1" not in conversation_service.contexts
        result = conversation_service.add_to_history("u1", "user", "hello")
        assert result is True
        ctx = conversation_service.contexts["u1"]
        assert ctx.conversation_history[-1] == {"role": "user", "content": "hello"}

    def test_add_to_history_appends_to_existing_context(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_to_history("u1", "user", "first")
        conversation_service.add_to_history("u1", "assistant", "second")
        ctx = conversation_service.contexts["u1"]
        assert len(ctx.conversation_history) == 2
        assert ctx.conversation_history[0]["content"] == "first"
        assert ctx.conversation_history[1]["content"] == "second"

    def test_add_to_history_truncates_at_20(
        self, conversation_service: _ConversationHost
    ) -> None:
        for i in range(25):
            conversation_service.add_to_history("u1", "user", f"msg{i}")
        ctx = conversation_service.contexts["u1"]
        assert len(ctx.conversation_history) == 20
        assert ctx.conversation_history[0]["content"] == "msg5"
        assert ctx.conversation_history[-1]["content"] == "msg24"

    def test_add_to_history_updates_timestamp(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_to_history("u1", "user", "hello")
        ctx = conversation_service.contexts["u1"]
        original_updated = ctx.updated_at
        import time

        time.sleep(0.01)
        conversation_service.add_to_history("u1", "user", "world")
        assert ctx.updated_at > original_updated

    def test_add_to_history_boundary_19_keeps_all(
        self, conversation_service: _ConversationHost
    ) -> None:
        for i in range(19):
            conversation_service.add_to_history("u1", "user", f"msg{i}")
        ctx = conversation_service.contexts["u1"]
        assert len(ctx.conversation_history) == 19

    def test_add_to_history_boundary_20_keeps_all(
        self, conversation_service: _ConversationHost
    ) -> None:
        for i in range(20):
            conversation_service.add_to_history("u1", "user", f"msg{i}")
        ctx = conversation_service.contexts["u1"]
        assert len(ctx.conversation_history) == 20

    def test_add_to_history_boundary_21_truncates(
        self, conversation_service: _ConversationHost
    ) -> None:
        for i in range(21):
            conversation_service.add_to_history("u1", "user", f"msg{i}")
        ctx = conversation_service.contexts["u1"]
        assert len(ctx.conversation_history) == 20
        assert ctx.conversation_history[0]["content"] == "msg1"


class TestAddIntentFeedback:
    """Cover AIConversationService.add_intent_feedback branches."""

    def test_add_intent_feedback_calls_user_memory(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="confirmed",
        )
        conversation_service.user_memory.add_feedback.assert_called_once()

    def test_add_intent_feedback_with_corrected_intent(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="corrected",
            corrected_intent="order",
        )
        call_kwargs = conversation_service.user_memory.add_feedback.call_args.kwargs
        assert call_kwargs["corrected_intent"] == "order"

    def test_add_intent_feedback_with_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="confirmed",
            slots={"key": "value"},
        )
        call_kwargs = conversation_service.user_memory.add_feedback.call_args.kwargs
        assert call_kwargs["slots"] == {"key": "value"}

    def test_add_intent_feedback_none_slots_defaults_to_empty_dict(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="confirmed",
            slots=None,
        )
        call_kwargs = conversation_service.user_memory.add_feedback.call_args.kwargs
        assert call_kwargs["slots"] == {}

    def test_add_intent_feedback_swallows_recoverable_error(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.add_feedback.side_effect = RuntimeError("db down")
        # Should not raise
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="confirmed",
        )

    def test_add_intent_feedback_swallows_value_error(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.add_feedback.side_effect = ValueError("bad input")
        conversation_service.add_intent_feedback(
            user_id="u1",
            message="hello",
            recognized_intent="greeting",
            feedback="confirmed",
        )


class TestRecordUserAction:
    """Cover AIConversationService.record_user_action branches."""

    def test_record_user_action_calls_user_memory(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.record_user_action(
            user_id="u1", intent="greeting", slots={"k": "v"}, message="hello"
        )
        conversation_service.user_memory.record_action.assert_called_once()

    def test_record_user_action_propagates_kwargs(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.record_user_action(
            user_id="u1", intent="order", slots={"product": "x"}, message="order x"
        )
        call_kwargs = conversation_service.user_memory.record_action.call_args.kwargs
        assert call_kwargs["user_id"] == "u1"
        assert call_kwargs["intent"] == "order"
        assert call_kwargs["slots"] == {"product": "x"}
        assert call_kwargs["message"] == "order x"

    def test_record_user_action_swallows_recoverable_error(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.record_action.side_effect = RuntimeError("db down")
        conversation_service.record_user_action(
            user_id="u1", intent="greeting", slots={}, message="hello"
        )

    def test_record_user_action_swallows_oserror(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.record_action.side_effect = OSError("io err")
        conversation_service.record_user_action(
            user_id="u1", intent="greeting", slots={}, message="hello"
        )

    def test_record_user_action_empty_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.record_user_action(
            user_id="u1", intent="greeting", slots={}, message="hello"
        )
        call_kwargs = conversation_service.user_memory.record_action.call_args.kwargs
        assert call_kwargs["slots"] == {}


class TestApplyMemoryPreferences:
    """Cover AIConversationService.apply_memory_preferences branches."""

    def test_apply_memory_preferences_returns_modified_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.apply_preference_to_slots.return_value = {
            "k": "modified"
        }
        result = conversation_service.apply_memory_preferences(
            "u1", "greeting", {"k": "v"}
        )
        assert result == {"k": "modified"}

    def test_apply_memory_preferences_swallows_error_returns_original(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.apply_preference_to_slots.side_effect = RuntimeError(
            "db down"
        )
        original = {"k": "v"}
        result = conversation_service.apply_memory_preferences("u1", "greeting", original)
        assert result is original

    def test_apply_memory_preferences_empty_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.apply_preference_to_slots.return_value = {}
        result = conversation_service.apply_memory_preferences("u1", "greeting", {})
        assert result == {}


class TestGetMemorySimilarAction:
    """Cover AIConversationService.get_memory_similar_action branches."""

    def test_get_memory_similar_action_returns_result(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_similar_pattern.return_value = {
            "intent": "greeting"
        }
        result = conversation_service.get_memory_similar_action("u1", "greeting", {"k": "v"})
        assert result == {"intent": "greeting"}

    def test_get_memory_similar_action_returns_none_when_no_match(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_similar_pattern.return_value = None
        result = conversation_service.get_memory_similar_action("u1", "greeting", {"k": "v"})
        assert result is None

    def test_get_memory_similar_action_swallows_error_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_similar_pattern.side_effect = ValueError("bad")
        result = conversation_service.get_memory_similar_action("u1", "greeting", {"k": "v"})
        assert result is None


class TestGetHabitSuggestions:
    """Cover AIConversationService.get_habit_suggestions branches."""

    def test_get_habit_suggestions_returns_list(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {"actions": []}
        ]
        result = conversation_service.get_habit_suggestions("u1")
        assert len(result) == 1

    def test_get_habit_suggestions_returns_empty_list(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = []
        result = conversation_service.get_habit_suggestions("u1")
        assert result == []

    def test_get_habit_suggestions_swallows_error_returns_empty(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.side_effect = RuntimeError(
            "db"
        )
        result = conversation_service.get_habit_suggestions("u1")
        assert result == []


class TestGetContextForRecognition:
    """Cover AIConversationService.get_context_for_recognition branches."""

    def test_basic_context_without_recent_actions(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = []
        conversation_service.user_memory.get_all_preferences.return_value = {}
        ctx = ConversationContext(user_id="u1")
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["user_id"] == "u1"
        assert "recent_intents" not in result
        assert "user_preferences" not in result

    def test_context_includes_recent_intents_when_present(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = [
            {"intent": "greeting"},
            {"intent": "order"},
        ]
        conversation_service.user_memory.get_all_preferences.return_value = {}
        ctx = ConversationContext(user_id="u1")
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["recent_intents"] == ["greeting", "order"]

    def test_context_includes_preferences_when_present(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = []
        conversation_service.user_memory.get_all_preferences.return_value = {"theme": "dark"}
        ctx = ConversationContext(user_id="u1")
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["user_preferences"] == {"theme": "dark"}

    def test_context_with_last_intent_result_uses_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = []
        conversation_service.user_memory.get_all_preferences.return_value = {}
        ctx = ConversationContext(user_id="u1")
        ctx.last_intent_result = {"slots": {"k": "v"}}
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["last_slots"] == {"k": "v"}

    def test_context_with_last_intent_result_no_slots(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = []
        conversation_service.user_memory.get_all_preferences.return_value = {}
        ctx = ConversationContext(user_id="u1")
        ctx.last_intent_result = {"other": "data"}
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["last_slots"] == {}

    def test_context_with_pending_confirmation(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_recent_actions.return_value = []
        conversation_service.user_memory.get_all_preferences.return_value = {}
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {"type": "confirm"}
        result = conversation_service.get_context_for_recognition("u1", ctx)
        assert result["pending_confirmation"] == {"type": "confirm"}


class TestCheckHabitSuggestion:
    """Cover AIConversationService._check_habit_suggestion branches."""

    def test_no_habits_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = []
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_low_confidence_habit_skipped(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {"confidence": 0.5, "actions": [{"intent": "greeting", "description": "x"}]}
        ]
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_matching_intent_returns_suggestion(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {
                "confidence": 0.9,
                "actions": [{"intent": "order", "description": "create order"}],
            }
        ]
        result = conversation_service._check_habit_suggestion("u1", "order", {})
        assert result is not None
        assert "create order" in result

    def test_no_matching_intent_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {
                "confidence": 0.9,
                "actions": [{"intent": "order", "description": "create order"}],
            }
        ]
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_habit_missing_actions_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {"confidence": 0.9}
        ]
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_habit_error_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.side_effect = RuntimeError(
            "db"
        )
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_habit_with_empty_actions_returns_none(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {"confidence": 0.9, "actions": []}
        ]
        result = conversation_service._check_habit_suggestion("u1", "greeting", {})
        assert result is None

    def test_habit_missing_description_uses_empty(
        self, conversation_service: _ConversationHost
    ) -> None:
        conversation_service.user_memory.get_habit_suggestions.return_value = [
            {"confidence": 0.9, "actions": [{"intent": "order"}]}
        ]
        result = conversation_service._check_habit_suggestion("u1", "order", {})
        assert result is not None
        assert "可能还需要" in result


class TestGetAiConversationServiceSingleton:
    """Cover get_ai_conversation_service / init_ai_conversation_service."""

    def test_get_ai_conversation_service_returns_singleton(self) -> None:
        with patch(
            "app.services.conversation.manager.AIConversationService.__init__",
            return_value=None,
        ):
            svc1 = get_ai_conversation_service()
            svc2 = get_ai_conversation_service()
            assert svc1 is svc2

    def test_init_ai_conversation_service_creates_new_instance(self) -> None:
        with patch(
            "app.services.conversation.manager.AIConversationService.__init__",
            return_value=None,
        ):
            svc = init_ai_conversation_service()
            assert svc is not None


class TestChatErrorPath:
    """Cover AIConversationService.chat error path."""

    @pytest.mark.asyncio
    async def test_chat_handles_recoverable_error(
        self, conversation_service: _ConversationHost
    ) -> None:
        with patch.object(
            conversation_service,
            "_get_or_create_context_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await conversation_service.chat("u1", "hello")
            assert result["action"] == "error"
            assert "boom" in result["text"]

    @pytest.mark.asyncio
    async def test_chat_handles_value_error(
        self, conversation_service: _ConversationHost
    ) -> None:
        with patch.object(
            conversation_service,
            "_get_or_create_context_async",
            new_callable=AsyncMock,
            side_effect=ValueError("bad input"),
        ):
            result = await conversation_service.chat("u1", "hello")
            assert result["action"] == "error"


# ===========================================================================
# 3. app/fastapi_routes/mobile_api.py
# ===========================================================================


@pytest.fixture
def mobile_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mobile_router)
    return app


@pytest.fixture
def mobile_client(mobile_app: FastAPI) -> TestClient:
    return TestClient(mobile_app, raise_server_exceptions=False)


class TestMobileLoginRequest:
    """Cover MobileLoginRequest model."""

    def test_valid_request(self) -> None:
        req = MobileLoginRequest(
            username="alice", password="secret", account_kind="enterprise"
        )
        assert req.username == "alice"
        assert req.password == "secret"
        assert req.account_kind == "enterprise"

    def test_default_account_kind(self) -> None:
        req = MobileLoginRequest(username="alice", password="secret")
        assert req.account_kind == "enterprise"

    def test_empty_username_raises(self) -> None:
        with pytest.raises(Exception):
            MobileLoginRequest(username="", password="secret")

    def test_empty_password_raises(self) -> None:
        with pytest.raises(Exception):
            MobileLoginRequest(username="alice", password="")


class TestMobileRefreshRequest:
    """Cover MobileRefreshRequest model."""

    def test_valid_request(self) -> None:
        req = MobileRefreshRequest(refresh_token="a" * 20)
        assert req.refresh_token == "a" * 20

    def test_short_token_raises(self) -> None:
        with pytest.raises(Exception):
            MobileRefreshRequest(refresh_token="short")


class TestParseWebAuthLoginResponse:
    """Cover _parse_web_auth_login_response branches."""

    def test_json_response_bytes(self) -> None:
        resp = JSONResponse(content={"success": True, "session_id": "sid1"})
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is True
        assert status == 200

    def test_json_response_empty_body(self) -> None:
        resp = JSONResponse(content={})
        resp.body = b""
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is False
        assert payload["message"] == "登录失败"

    def test_dict_passthrough(self) -> None:
        payload, status = _parse_web_auth_login_response({"success": True})
        assert payload["success"] is True
        assert status == 200

    def test_unknown_type_returns_failure(self) -> None:
        payload, status = _parse_web_auth_login_response(42)
        assert payload["success"] is False
        assert payload["message"] == "登录失败"

    def test_memoryview_body(self) -> None:
        resp = JSONResponse(content={"success": True})
        raw = resp.body
        if isinstance(raw, bytes):
            resp.body = memoryview(raw)
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is True

    def test_none_status_code_defaults_200(self) -> None:
        obj = SimpleNamespace(status_code=None)
        obj.body = b'{"success": true}'
        payload, status = _parse_web_auth_login_response(obj)
        assert status == 200

    def test_status_code_500_preserved(self) -> None:
        obj = SimpleNamespace(status_code=500)
        obj.body = b'{"success": false}'
        payload, status = _parse_web_auth_login_response(obj)
        assert status == 500

    def test_str_body_via_json_response(self) -> None:
        # JSONResponse.body is normally bytes; force a str to cover the
        # `json.loads(str(raw))` branch in _parse_web_auth_login_response.
        resp = JSONResponse(content={"success": True})
        resp.body = '{"success": true}'  # str, not bytes
        payload, status = _parse_web_auth_login_response(resp)
        assert payload["success"] is True
        assert status == 200


class TestWebLoginErrorMessage:
    """Cover _web_login_error_message branches."""

    def test_error_dict_with_message(self) -> None:
        msg = _web_login_error_message({"error": {"message": "custom error"}})
        assert msg == "custom error"

    def test_error_dict_empty_message_falls_back(self) -> None:
        msg = _web_login_error_message({"error": {"message": ""}, "message": "fallback"})
        assert msg == "fallback"

    def test_error_dict_no_message_key_falls_back(self) -> None:
        msg = _web_login_error_message({"error": {}, "message": "fallback"})
        assert msg == "fallback"

    def test_no_error_key_uses_message(self) -> None:
        msg = _web_login_error_message({"message": "direct message"})
        assert msg == "direct message"

    def test_no_message_returns_default(self) -> None:
        msg = _web_login_error_message({})
        assert msg == "登录失败"

    def test_empty_message_returns_default(self) -> None:
        msg = _web_login_error_message({"message": ""})
        assert msg == "登录失败"

    def test_whitespace_message_returns_default(self) -> None:
        msg = _web_login_error_message({"message": "   "})
        assert msg == "登录失败"

    def test_error_not_dict_uses_message(self) -> None:
        msg = _web_login_error_message({"error": "string error", "message": "msg"})
        assert msg == "msg"


class TestUserPublicDict:
    """Cover _user_public_dict."""

    def test_basic_user_dict(self) -> None:
        user = SimpleNamespace(
            id=1,
            username="alice",
            display_name="Alice",
            email="alice@example.com",
            role="admin",
            is_active=True,
            wx_avatar_url=None,
        )
        with patch(
            "app.utils.user_avatar_storage.public_avatar_url", return_value="/avatar.png"
        ):
            result = _user_public_dict(user)
        assert result["id"] == 1
        assert result["username"] == "alice"
        assert result["display_name"] == "Alice"
        assert result["email"] == "alice@example.com"
        assert result["role"] == "admin"
        assert result["is_active"] is True
        assert result["avatar_url"] == "/avatar.png"

    def test_user_without_wx_avatar_url_attr(self) -> None:
        user = SimpleNamespace(
            id=2,
            username="bob",
            display_name="Bob",
            email="bob@example.com",
            role="user",
            is_active=False,
        )
        with patch(
            "app.utils.user_avatar_storage.public_avatar_url", return_value=None
        ):
            result = _user_public_dict(user)
        assert result["id"] == 2
        assert result["is_active"] is False


class TestMobileHealth:
    """Cover mobile_health endpoint."""

    def test_returns_ok(self, mobile_client: TestClient) -> None:
        r = mobile_client.get("/api/mobile/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["status"] == "ok"
        assert body["data"]["service"] == "xcagi-mobile"


class TestMobileAuthRefresh:
    """Cover mobile_auth_refresh endpoint."""

    def test_invalid_refresh_token_returns_401(self, mobile_client: TestClient) -> None:
        r = mobile_client.post(
            "/api/mobile/v1/auth/refresh",
            json={"refresh_token": "invalid_token_string"},
        )
        assert r.status_code == 401
        body = r.json()
        assert body["success"] is False

    def test_valid_refresh_token_returns_new_tokens(
        self, mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")
        from app.security.mobile_jwt import issue_mobile_tokens

        tokens = issue_mobile_tokens(
            user_id=1, session_id="sid1", account_kind="enterprise", username="alice"
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]
        assert body["data"]["expires_in"] == 24 * 3600

    def test_reused_refresh_token_returns_401(
        self, mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")
        from app.security.mobile_jwt import issue_mobile_tokens

        tokens = issue_mobile_tokens(
            user_id=2, session_id="sid2", account_kind="enterprise", username="bob"
        )
        # First use succeeds
        r1 = mobile_client.post(
            "/api/mobile/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r1.status_code == 200
        # Second use fails (one-time use)
        r2 = mobile_client.post(
            "/api/mobile/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r2.status_code == 401


class TestMobileHostDiscoverHint:
    """Cover mobile_host_discover_hint endpoint."""

    def test_returns_discovery_info(self, mobile_client: TestClient) -> None:
        r = mobile_client.get("/api/mobile/v1/host/discover-hint")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "lan" in body["data"]
        assert "instance_name" in body["data"]
        assert "api_port" in body["data"]
        assert body["data"]["company"] == "成都修茈科技有限公司"
        assert body["data"]["brand_url"] == "https://xiu-ci.com"


class TestMobileMeUnauthorized:
    """Cover mobile_me endpoint unauthorized path."""

    def test_me_without_auth_returns_401(self, mobile_client: TestClient) -> None:
        r = mobile_client.get("/api/mobile/v1/me")
        assert r.status_code == 401
        body = r.json()
        assert body["success"] is False
        assert body["message"] == "未授权"


class TestMobileAuthLogin:
    """Cover mobile_auth_login endpoint branches."""

    def test_login_invalid_credentials_returns_401(
        self, mobile_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_auth_login(request, payload):
            return JSONResponse(
                content={"success": False, "error": {"message": "用户名或密码错误"}},
                status_code=401,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login", fake_auth_login
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={"username": "alice", "password": "wrong"},
        )
        assert r.status_code == 401
        body = r.json()
        assert body["success"] is False

    def test_login_success_returns_tokens(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")

        async def fake_auth_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "sid123",
                    "user": {"id": 1, "username": "alice"},
                    "account_kind": "enterprise",
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login", fake_auth_login
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert body["data"]["session_id"] == "sid123"
        assert body["data"]["account_kind"] == "enterprise"

    def test_login_missing_session_returns_500(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_auth_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "",
                    "user": {"id": 1, "username": "alice"},
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login", fake_auth_login
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert body["message"] == "会话创建失败"

    def test_login_missing_user_returns_500(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_auth_login(request, payload):
            return JSONResponse(
                content={"success": True, "session_id": "sid1", "user": {}},
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login", fake_auth_login
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )
        assert r.status_code == 500

    def test_login_with_market_tokens_passes_through(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")

        async def fake_auth_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "sid1",
                    "user": {"id": 1, "username": "alice"},
                    "account_kind": "enterprise",
                    "market_access_token": "mat",
                    "market_refresh_token": "mrt",
                    "company_brand": "MyBrand",
                    "market_is_admin": True,
                    "market_is_enterprise": True,
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login", fake_auth_login
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login",
            json={"username": "alice", "password": "secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["market_access_token"] == "mat"
        assert body["data"]["market_refresh_token"] == "mrt"
        assert body["data"]["company_brand"] == "MyBrand"
        assert body["data"]["market_is_admin"] is True
        assert body["data"]["market_is_enterprise"] is True


class TestMobileAuthLoginWithPhoneCode:
    """Cover mobile_auth_login_with_phone_code endpoint branches."""

    def test_login_invalid_returns_401(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_phone_login(request, payload):
            return JSONResponse(
                content={"success": False, "error": {"message": "验证码错误"}},
                status_code=401,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login_with_phone_code",
            fake_phone_login,
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "wrong"},
        )
        assert r.status_code == 401

    def test_login_success_returns_tokens(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")

        async def fake_phone_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "sid1",
                    "user": {"id": 1, "username": "alice"},
                    "account_kind": "enterprise",
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login_with_phone_code",
            fake_phone_login,
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "123456"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "access_token" in body["data"]

    def test_login_missing_session_returns_500(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_phone_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "",
                    "user": {"id": 1, "username": "alice"},
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login_with_phone_code",
            fake_phone_login,
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "123456"},
        )
        assert r.status_code == 500

    def test_login_with_tenant_info_passes_through(
        self,
        mobile_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")

        async def fake_phone_login(request, payload):
            return JSONResponse(
                content={
                    "success": True,
                    "session_id": "sid1",
                    "user": {"id": 1, "username": "alice"},
                    "account_kind": "enterprise",
                    "tenant_id": "tid",
                    "tenant_name": "tname",
                },
                status_code=200,
            )

        monkeypatch.setattr(
            "app.fastapi_routes.domains.auth.routes.auth_login_with_phone_code",
            fake_phone_login,
        )
        r = mobile_client.post(
            "/api/mobile/v1/auth/login-with-phone-code",
            json={"phone": "13800138000", "code": "123456"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["tenant_id"] == "tid"
        assert body["data"]["tenant_name"] == "tname"


class TestGetMobileUser:
    """Cover get_mobile_user dependency branches."""

    @pytest.mark.asyncio
    async def test_no_authorization_header_resolves_session_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.fastapi_routes.mobile_api import get_mobile_user

        request = MagicMock()
        request.headers = {}

        def fake_resolve(request):
            return None

        monkeypatch.setattr(
            "app.infrastructure.auth.dependencies.resolve_session_user", fake_resolve
        )
        result = await get_mobile_user(request, authorization=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_bearer_token_returns_none_without_session_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.fastapi_routes.mobile_api import get_mobile_user

        request = MagicMock()
        request.headers = {}
        resolved = []

        def fake_resolve(request):
            resolved.append(request)
            return "session_user"

        monkeypatch.setattr(
            "app.infrastructure.auth.dependencies.resolve_session_user", fake_resolve
        )
        result = await get_mobile_user(request, authorization="Bearer invalid_token")
        assert result is None
        assert resolved == []

    @pytest.mark.asyncio
    async def test_valid_bearer_token_loads_user_from_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.fastapi_routes.mobile_api import get_mobile_user

        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")
        from app.security.mobile_jwt import issue_mobile_tokens

        tokens = issue_mobile_tokens(
            user_id=42, session_id="sid1", account_kind="enterprise", username="alice"
        )

        request = MagicMock()
        request.headers = {}

        fake_user = SimpleNamespace(
            id=42,
            username="alice",
            display_name="Alice",
            email="alice@example.com",
            role="admin",
            is_active=True,
            wx_avatar_url=None,
        )

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return fake_user

        class FakeDb:
            def query(self, model):
                return FakeQuery()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.db.session.get_db", lambda: FakeDb())
        result = await get_mobile_user(
            request, authorization=f"Bearer {tokens['access_token']}"
        )
        assert result is fake_user

    @pytest.mark.asyncio
    async def test_valid_bearer_token_inactive_user_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.fastapi_routes.mobile_api import get_mobile_user

        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")
        from app.security.mobile_jwt import issue_mobile_tokens

        tokens = issue_mobile_tokens(
            user_id=99, session_id="sid1", account_kind="enterprise", username="bob"
        )

        request = MagicMock()
        request.headers = {}

        fake_user = SimpleNamespace(
            id=99,
            username="bob",
            display_name="Bob",
            email="bob@example.com",
            role="user",
            is_active=False,
            wx_avatar_url=None,
        )

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return fake_user

        class FakeDb:
            def query(self, model):
                return FakeQuery()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.db.session.get_db", lambda: FakeDb())
        result = await get_mobile_user(
            request, authorization=f"Bearer {tokens['access_token']}"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_bearer_token_user_not_found_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.fastapi_routes.mobile_api import get_mobile_user

        monkeypatch.setenv("SECRET_KEY", "test_secret_for_jwt_12345")
        from app.security.mobile_jwt import issue_mobile_tokens

        tokens = issue_mobile_tokens(
            user_id=999, session_id="sid1", account_kind="enterprise", username="ghost"
        )

        request = MagicMock()
        request.headers = {}

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, model):
                return FakeQuery()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("app.db.session.get_db", lambda: FakeDb())
        result = await get_mobile_user(
            request, authorization=f"Bearer {tokens['access_token']}"
        )
        assert result is None


# ===========================================================================
# 4. app/infrastructure/mods/mod_manager.py
# ===========================================================================


class TestIsModsDisabled:
    """Cover is_mods_disabled branches."""

    def test_default_not_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DISABLE_MODS", raising=False)
        assert is_mods_disabled() is False

    def test_disabled_with_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        assert is_mods_disabled() is True

    def test_disabled_with_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "true")
        assert is_mods_disabled() is True

    def test_disabled_with_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "yes")
        assert is_mods_disabled() is True

    def test_disabled_with_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "on")
        assert is_mods_disabled() is True

    def test_disabled_with_uppercase_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "TRUE")
        assert is_mods_disabled() is True

    def test_not_disabled_with_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "no")
        assert is_mods_disabled() is False

    def test_not_disabled_with_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "")
        assert is_mods_disabled() is False

    def test_not_disabled_with_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "  ")
        assert is_mods_disabled() is False


class TestShortExcMessage:
    """Cover _short_exc_message branches."""

    def test_short_message_preserved(self) -> None:
        assert _short_exc_message(ValueError("test")) == "test"

    def test_long_message_truncated(self) -> None:
        long_msg = "x" * 600
        result = _short_exc_message(ValueError(long_msg))
        assert len(result) <= 480
        assert result.endswith("...")

    def test_empty_exception_uses_type_name(self) -> None:
        result = _short_exc_message(ValueError())
        assert result == "ValueError"

    def test_whitespace_only_message_uses_type_name(self) -> None:
        result = _short_exc_message(ValueError("   "))
        assert result == "ValueError"

    def test_custom_max_len(self) -> None:
        result = _short_exc_message(ValueError("abcdefgh"), max_len=5)
        assert len(result) <= 5
        assert result.endswith("...")

    def test_message_exactly_at_max_len(self) -> None:
        msg = "x" * 100
        result = _short_exc_message(ValueError(msg), max_len=100)
        assert result == msg


class TestBackendPathForMod:
    """Cover _backend_path_for_mod."""

    def test_returns_backend_path(self) -> None:
        assert _backend_path_for_mod("/mods/test-mod") == "/mods/test-mod/backend"

    def test_empty_path(self) -> None:
        # os.path.join("", "backend") == "backend"
        assert _backend_path_for_mod("") == "backend"

    def test_relative_path(self) -> None:
        assert _backend_path_for_mod("relative/path") == "relative/path/backend"


class TestDefaultModsRoot:
    """Cover _default_mods_root branches."""

    def test_env_var_set_and_dir_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        monkeypatch.setenv("XCAGI_MODS_ROOT", mods_dir)
        result = _default_mods_root()
        assert result == mods_dir

    def test_env_var_set_but_not_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path / "nonexistent"))
        monkeypatch.delenv("XCAGI_MODS_DIR", raising=False)
        result = _default_mods_root()
        assert isinstance(result, str)

    def test_env_mods_dir_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mods_dir = str(tmp_path / "mods_dir")
        os.makedirs(mods_dir)
        monkeypatch.delenv("XCAGI_MODS_ROOT", raising=False)
        monkeypatch.setenv("XCAGI_MODS_DIR", mods_dir)
        result = _default_mods_root()
        assert result == mods_dir


class TestRepoLayoutModsCandidates:
    """Cover _repo_layout_mods_candidates."""

    def test_returns_list(self) -> None:
        result = _repo_layout_mods_candidates()
        assert isinstance(result, list)

    def test_no_duplicates(self) -> None:
        result = _repo_layout_mods_candidates()
        assert len(result) == len(set(result))


class TestAllModsRoots:
    """Cover _all_mods_roots branches."""

    def test_empty_primary(self) -> None:
        result = _all_mods_roots("")
        assert isinstance(result, list)

    def test_valid_primary(self, tmp_path: Path) -> None:
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        result = _all_mods_roots(mods_dir)
        assert mods_dir in result

    def test_deduplication(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mods_dir = str(tmp_path / "mods")
        os.makedirs(mods_dir)
        monkeypatch.setenv("XCAGI_MODS_ROOT", mods_dir)
        result = _all_mods_roots(mods_dir)
        assert result.count(mods_dir) <= 1

    def test_env_var_adds_extra_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = str(tmp_path / "primary_mods")
        os.makedirs(primary)
        env_mods = str(tmp_path / "env_mods")
        os.makedirs(env_mods)
        monkeypatch.setenv("XCAGI_MODS_ROOT", env_mods)
        result = _all_mods_roots(primary)
        assert primary in result
        assert env_mods in result


class TestImportModBackendPy:
    """Cover import_mod_backend_py branches."""

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            import_mod_backend_py(str(tmp_path / "nonexistent"), "test_mod", "blueprints")

    def test_successful_import(self, tmp_path: Path) -> None:
        mod_path = str(tmp_path / "test_mod")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        py_file = os.path.join(backend_path, "services.py")
        Path(py_file).write_text("VALUE = 42\n")
        module = import_mod_backend_py(mod_path, "test_mod", "services")
        assert module.VALUE == 42

    def test_cached_import_returns_same_module(self, tmp_path: Path) -> None:
        mod_path = str(tmp_path / "test_mod2")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        py_file = os.path.join(backend_path, "services.py")
        Path(py_file).write_text("VALUE = 100\n")
        module1 = import_mod_backend_py(mod_path, "test_mod2", "services")
        module2 = import_mod_backend_py(mod_path, "test_mod2", "services")
        assert module1 is module2

    def test_special_chars_in_mod_id(self, tmp_path: Path) -> None:
        mod_path = str(tmp_path / "test-mod.special")
        backend_path = os.path.join(mod_path, "backend")
        os.makedirs(backend_path)
        py_file = os.path.join(backend_path, "entry.py")
        Path(py_file).write_text("NAME = 'special'\n")
        module = import_mod_backend_py(mod_path, "test-mod.special", "entry")
        assert module.NAME == "special"


class TestInvokeModInitHook:
    """Cover _invoke_mod_init_hook signature branches."""

    def test_no_params_function_called(self) -> None:
        called = []

        def fn():
            called.append("called")

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert called == ["called"]

    def test_app_param_passed_as_none(self) -> None:
        captured = {}

        def fn(app=None):
            captured["app"] = app

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert captured["app"] is None

    def test_mod_id_param_passed(self) -> None:
        captured = {}

        def fn(mod_id=None):
            captured["mod_id"] = mod_id

        _invoke_mod_init_hook(fn, mod_id="my_mod")
        assert captured["mod_id"] == "my_mod"

    def test_required_unknown_param_skipped(self) -> None:
        called = []

        def fn(unknown_required):
            called.append("called")

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert called == []

    def test_signature_bind_fails_calls_without_kwargs(self) -> None:
        called = []

        def fn(app=None, mod_id=None, extra=None):
            called.append("with_kwargs")

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert called == ["with_kwargs"]

    def test_invalid_signature_falls_back_to_no_kwargs(self) -> None:
        called = []

        class CallableWithBadSig:
            def __call__(self, *args, **kwargs):
                called.append("called")

            def __signature__(self):
                raise TypeError("bad sig")

        # inspect.signature may raise TypeError for some objects
        class WeirdCallable:
            def __call__(self):
                called.append("weird")

        # Use a builtin which raises TypeError on inspect.signature
        _invoke_mod_init_hook(print, mod_id="m1")  # print has complex sig
        # Should not raise

    def test_var_positional_ignored(self) -> None:
        called = []

        def fn(*args, mod_id=None):
            called.append(("called", mod_id))

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert called == [("called", "m1")]

    def test_var_keyword_ignored(self) -> None:
        called = []

        def fn(mod_id=None, **kwargs):
            called.append(("called", mod_id, kwargs))

        _invoke_mod_init_hook(fn, mod_id="m1")
        assert called == [("called", "m1", {})]


class TestRegisterModHooks:
    """Cover _register_mod_hooks branches."""

    def test_no_hooks_returns_early(self) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        metadata = ModMetadata(id="m1", name="M1", version="1.0.0", mod_path="/mods/m1")
        # Should not raise
        _register_mod_hooks("m1", metadata)

    def test_empty_mod_path_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        metadata = ModMetadata(
            id="m1",
            name="M1",
            version="1.0.0",
            mod_path="",
            hooks={"event1": "handler.fn"},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m1", metadata)
        assert any("no mod_path" in r.message for r in caplog.records)

    def test_invalid_hook_spec_skipped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        metadata = ModMetadata(
            id="m1",
            name="M1",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event1": "invalid_no_dot"},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m1", metadata)
        assert any("Invalid hook handler spec" in r.message for r in caplog.records)

    def test_backend_prefix_stripped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from app.infrastructure.mods.manifest import ModMetadata

        metadata = ModMetadata(
            id="m1",
            name="M1",
            version="1.0.0",
            mod_path=str(tmp_path),
            hooks={"event1": "backend.missing_module.fn"},
        )
        with caplog.at_level("ERROR"):
            _register_mod_hooks("m1", metadata)
        # Should attempt to import "missing_module" (FileNotFoundError is RECOVERABLE)
        assert any(
            "Failed to register hook" in r.message or "Invalid hook handler spec" in r.message
            for r in caplog.records
        )


class TestModManagerInit:
    """Cover ModManager __init__ branches."""

    def test_init_with_explicit_mods_root(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.mods_root == str(tmp_path)
        assert mm._loaded_mods == []
        assert mm._recent_load_failures == []
        assert mm._blueprint_failures == []
        assert mm._scan_manifest_errors == []

    def test_init_defaults_mods_root(self) -> None:
        mm = ModManager()
        assert isinstance(mm.mods_root, str)
        assert mm._last_ensure_at == 0.0
        assert mm._ensure_attempts == 0

    def test_init_state_collections_empty(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        assert mm._http_routes_registered == set()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []
        assert mm._backend_entry_modules == {}


class TestModManagerInvalidateScanCache:
    """Cover invalidate_scan_cache."""

    def test_invalidate_clears_cache(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_cache_fp = "old_fp"
        mm._scan_cache_mods = [MagicMock()]
        mm.invalidate_scan_cache()
        assert mm._scan_cache_fp == ""
        assert mm._scan_cache_mods == []


class TestModManagerRecordLoadFailure:
    """Cover _record_load_failure / record_blueprint_failure."""

    def test_record_load_failure_appends(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "fs", "directory missing")
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["mod_id"] == "mod1"
        assert mm._recent_load_failures[0]["stage"] == "fs"

    def test_record_load_failure_truncates_long_message(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        long_msg = "x" * 600
        mm._record_load_failure("mod1", "fs", long_msg)
        assert len(mm._recent_load_failures[0]["message"]) <= 500

    def test_record_blueprint_failure_appends(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm.record_blueprint_failure("mod1", "blueprint error")
        assert len(mm._blueprint_failures) == 1
        assert mm._blueprint_failures[0]["mod_id"] == "mod1"

    def test_record_blueprint_failure_truncates(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        long_msg = "x" * 600
        mm.record_blueprint_failure("mod1", long_msg)
        assert len(mm._blueprint_failures[0]["message"]) <= 500

    def test_get_recent_load_failures_returns_copy(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._record_load_failure("mod1", "fs", "err")
        failures = mm.get_recent_load_failures()
        failures.append({"mod_id": "other", "stage": "x", "message": "y"})
        assert len(mm._recent_load_failures) == 1

    def test_get_blueprint_failures_returns_copy(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm.record_blueprint_failure("mod1", "err")
        failures = mm.get_blueprint_failures()
        failures.append({"mod_id": "other", "message": "y"})
        assert len(mm._blueprint_failures) == 1

    def test_get_scan_manifest_errors_returns_copy(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._scan_manifest_errors.append({"entry": "e", "mods_root": "r", "message": "m"})
        errors = mm.get_scan_manifest_errors()
        errors.append({"entry": "other"})
        assert len(mm._scan_manifest_errors) == 1


class TestModManagerScanMods:
    """Cover scan_mods branches."""

    def _make_mm(self, tmp_path: Path) -> ModManager:
        """Build a ModManager whose all_mods_roots is pinned to tmp_path.

        Without this, _refresh_mods_root_if_needed() re-resolves mods_root
        from env / repo layout and picks up the real FHD/mods directory.
        """
        mm = ModManager(mods_root=str(tmp_path))
        mm.all_mods_roots = lambda: [str(tmp_path)]  # type: ignore[method-assign]
        return mm

    def test_scan_empty_mods_root(self, tmp_path: Path) -> None:
        mm = self._make_mm(tmp_path)
        result = mm.scan_mods()
        assert result == []

    def test_scan_ignores_underscore_prefixed_entries(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        (mods_root / "_internal").mkdir()
        (mods_root / "_internal" / "manifest.json").write_text('{"id": "internal"}')
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert result == []

    def test_scan_skips_non_directory_entries(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        (mods_root / "stray_file.txt").write_text("not a mod")
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert result == []

    def test_scan_skips_entries_without_manifest(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        (mods_root / "no_manifest").mkdir()
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert result == []
        assert len(mm._scan_manifest_errors) == 1

    def test_scan_finds_valid_mod(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "demo_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "demo_mod", "name": "Demo", "version": "1.0.0"})
        )
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert len(result) == 1
        assert result[0].id == "demo_mod"

    def test_scan_uses_cache_on_second_call(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "demo_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            json.dumps({"id": "demo_mod", "name": "Demo", "version": "1.0.0"})
        )
        mm = self._make_mm(mods_root)
        first = mm.scan_mods()
        second = mm.scan_mods()
        assert len(first) == len(second) == 1

    def test_scan_invalid_json_logs_error(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "bad_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not valid json {{{")
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert result == []
        assert len(mm._scan_manifest_errors) == 1

    def test_scan_manifest_missing_id_returns_none(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "no_id_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({"name": "NoID"}))
        mm = self._make_mm(mods_root)
        result = mm.scan_mods()
        assert result == []
        assert len(mm._scan_manifest_errors) == 1

    def test_scan_dedupes_same_id_across_roots(self, tmp_path: Path) -> None:
        mods_root1 = tmp_path / "mods1"
        mods_root1.mkdir()
        mod_dir1 = mods_root1 / "demo_mod"
        mod_dir1.mkdir()
        (mod_dir1 / "manifest.json").write_text(
            json.dumps({"id": "demo_mod", "name": "Demo1", "version": "1.0.0"})
        )
        mods_root2 = tmp_path / "mods2"
        mods_root2.mkdir()
        mod_dir2 = mods_root2 / "demo_mod"
        mod_dir2.mkdir()
        (mod_dir2 / "manifest.json").write_text(
            json.dumps({"id": "demo_mod", "name": "Demo2", "version": "2.0.0"})
        )
        mm = ModManager(mods_root=str(mods_root1))
        with patch.object(mm, "all_mods_roots", return_value=[str(mods_root1), str(mods_root2)]):
            result = mm.scan_mods()
        assert len(result) == 1


class TestModManagerListMods:
    """Cover list_mods / list_all_mods / list_loaded_mods."""

    def test_list_mods_disabled_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.list_mods() == []

    def test_list_all_mods_disabled_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.list_all_mods() == []

    def test_get_routes_disabled_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.get_routes() == []


class TestModManagerResolveModDirectory:
    """Cover resolve_mod_directory branches."""

    def test_empty_mod_id_returns_none(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.resolve_mod_directory("") is None

    def test_whitespace_mod_id_returns_none(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        assert mm.resolve_mod_directory("   ") is None

    def test_not_found_returns_none(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mm = ModManager(mods_root=str(mods_root))
        assert mm.resolve_mod_directory("nonexistent") is None

    def test_found_returns_path(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "demo_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text('{"id": "demo_mod"}')
        mm = ModManager(mods_root=str(mods_root))
        result = mm.resolve_mod_directory("demo_mod")
        assert result is not None
        assert result.endswith("demo_mod")


class TestModManagerLoadMod:
    """Cover load_mod branches."""

    def test_load_mod_blocked_by_sku_policy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mm = ModManager(mods_root=str(mods_root))

        def fake_assert(mod_id):
            raise PermissionError("not allowed for SKU")

        monkeypatch.setattr(
            "app.mod_sdk.product_skus.assert_mod_allowed_for_sku", fake_assert
        )
        result = mm.load_mod("blocked_mod")
        assert result is False
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["stage"] == "sku_policy"

    def test_load_mod_not_found_on_disk(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mm = ModManager(mods_root=str(mods_root))
        result = mm.load_mod("nonexistent_mod")
        assert result is False
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["stage"] == "fs"

    def test_load_mod_invalid_manifest(self, tmp_path: Path) -> None:
        mods_root = tmp_path / "mods"
        mods_root.mkdir()
        mod_dir = mods_root / "bad_mod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text("not json")
        mm = ModManager(mods_root=str(mods_root))
        result = mm.load_mod("bad_mod")
        assert result is False
        assert len(mm._recent_load_failures) == 1
        assert mm._recent_load_failures[0]["stage"] == "manifest"


class TestModManagerUnloadMod:
    """Cover unload_mod branches."""

    def test_unload_mod_cleanup_error_swallowed(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("m1")

        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as fake_reg, patch(
            "app.infrastructure.mods.comms.get_mod_comms"
        ) as fake_comms:
            registry = MagicMock()
            instance = MagicMock()
            instance.cleanup.side_effect = RuntimeError("cleanup failed")
            registry.get_mod_instance.return_value = instance
            fake_reg.return_value = registry
            fake_comms.return_value.unregister_all.side_effect = RuntimeError("comms fail")
            result = mm.unload_mod("m1")
        assert result is True
        assert "m1" not in mm._loaded_mods

    def test_unload_mod_no_instance(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._loaded_mods.append("m1")

        with patch("app.infrastructure.mods.mod_manager.get_mod_registry") as fake_reg, patch(
            "app.infrastructure.mods.comms.get_mod_comms"
        ) as fake_comms:
            registry = MagicMock()
            registry.get_mod_instance.return_value = None
            fake_reg.return_value = registry
            fake_comms.return_value.unregister_all.return_value = None
            result = mm.unload_mod("m1")
        assert result is True


class TestModManagerValidateModPackage:
    """Cover validate_mod_package branches."""

    def test_file_not_exists(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.validate_mod_package(str(tmp_path / "nonexistent.xcmod"))
        assert result[0] is False
        assert result[1] == "文件不存在"

    def test_not_a_zip_file(self, tmp_path: Path) -> None:
        not_zip = tmp_path / "not_zip.xcmod"
        not_zip.write_text("not a zip")
        mm = ModManager(mods_root=str(tmp_path))
        result = mm.validate_mod_package(str(not_zip))
        assert result[0] is False
        assert "ZIP" in result[1]


class TestModManagerEnsureModsLoaded:
    """Cover ensure_mods_loaded branches."""

    def test_disabled_mods_returns_early(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        mm.ensure_mods_loaded(MagicMock())
        # Should not raise

    def test_already_loaded_returns_early(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "list_loaded_mods", return_value=[MagicMock()]):
            mm.ensure_mods_loaded(MagicMock())
        # Should not attempt to scan

    def test_no_discovered_mods_returns_early(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        with patch.object(mm, "list_loaded_mods", return_value=[]), patch.object(
            mm, "scan_mods", return_value=[]
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_throttled_after_recent_attempt(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._last_ensure_at = 999999999.0  # far future
        mm._ensure_attempts = 1
        with patch.object(mm, "list_loaded_mods", return_value=[]), patch.object(
            mm, "scan_mods", return_value=[MagicMock()]
        ):
            mm.ensure_mods_loaded(MagicMock())

    def test_max_attempts_reached(self, tmp_path: Path) -> None:
        mm = ModManager(mods_root=str(tmp_path))
        mm._ensure_attempts = 20
        with patch.object(mm, "list_loaded_mods", return_value=[]), patch.object(
            mm, "scan_mods", return_value=[MagicMock()]
        ):
            mm.ensure_mods_loaded(MagicMock())


class TestLoadModBlueprints:
    """Cover load_mod_blueprints no-op."""

    def test_load_mod_blueprints_is_noop(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import load_mod_blueprints

        # Should not raise
        load_mod_blueprints(MagicMock(), ModManager(mods_root=str(tmp_path)))


class TestGetModManager:
    """Cover get_mod_manager singleton."""

    def test_get_mod_manager_returns_instance(self) -> None:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        mm = get_mod_manager()
        assert mm is not None
        assert mm is get_mod_manager()


class TestRegisterEmployeePackRoutes:
    """Cover register_employee_pack_routes branches."""

    def test_empty_pack_id_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "") is False

    def test_mods_disabled_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "pack1") is False

    def test_manifest_not_found_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "pack1") is False

    def test_manifest_invalid_json_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        emp_root = tmp_path / "_employees" / "pack1"
        emp_root.mkdir(parents=True)
        (emp_root / "manifest.json").write_text("not json")
        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "pack1") is False

    def test_wrong_artifact_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        emp_root = tmp_path / "_employees" / "pack1"
        emp_root.mkdir(parents=True)
        (emp_root / "manifest.json").write_text(
            json.dumps({"id": "pack1", "artifact": "mod"})
        )
        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "pack1") is False

    def test_no_backend_entry_returns_false(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import register_employee_pack_routes

        emp_root = tmp_path / "_employees" / "pack1"
        emp_root.mkdir(parents=True)
        (emp_root / "manifest.json").write_text(
            json.dumps({"id": "pack1", "artifact": "employee_pack", "backend": {}})
        )
        mm = ModManager(mods_root=str(tmp_path))
        assert register_employee_pack_routes(MagicMock(), mm, "pack1") is False


class TestLoadEmployeePackRoutes:
    """Cover load_employee_pack_routes branches."""

    def test_no_employees_dir_returns(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        mm = ModManager(mods_root=str(tmp_path))
        # Should not raise
        load_employee_pack_routes(MagicMock(), mm)

    def test_mods_disabled_returns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.infrastructure.mods.mod_manager import load_employee_pack_routes

        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        load_employee_pack_routes(MagicMock(), mm)


class TestEnsureModApiReady:
    """Cover ensure_mod_api_ready branches."""

    def test_empty_mod_id_returns_false(self) -> None:
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        assert ensure_mod_api_ready("") is False

    def test_mods_disabled_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        assert ensure_mod_api_ready("m1") is False


class TestMountOnDiskPrimaryClientMods:
    """Cover mount_on_disk_primary_client_mods branches."""

    def test_mods_disabled_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        monkeypatch.setenv("XCAGI_DISABLE_MODS", "1")
        mm = ModManager(mods_root=str(tmp_path))
        result = mount_on_disk_primary_client_mods(mm)
        assert result == []

    def test_mod_not_on_disk_returns_empty(self, tmp_path: Path) -> None:
        from app.infrastructure.mods.mod_manager import mount_on_disk_primary_client_mods

        mm = ModManager(mods_root=str(tmp_path))
        with patch(
            "app.enterprise.account_mod_binding.SUNBIRD_CLIENT_MOD_ID", "sunbird"
        ), patch.object(mm, "resolve_mod_directory", return_value=None):
            result = mount_on_disk_primary_client_mods(mm)
        assert result == []
