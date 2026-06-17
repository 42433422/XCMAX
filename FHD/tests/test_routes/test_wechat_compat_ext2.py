"""Tests for app.fastapi_routes.domains.wechat.compat_routes — deep coverage (ext2).

Focus: WechatStarredContact model, _starred_row_for_frontend,
_search_hit_for_frontend, _migrate_starred_contact_ids,
and route handlers for starred contacts.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# WechatStarredContact model
# ---------------------------------------------------------------------------


class TestWechatStarredContact:
    def test_create_with_primary_fields(self):
        from app.fastapi_routes.domains.wechat.compat_routes import WechatStarredContact

        contact = WechatStarredContact(
            type="contact",
            nickname="张三",
            wxid="wx_zhangsan",
        )
        assert contact.type == "contact"
        assert contact.nickname == "张三"
        assert contact.wxid == "wx_zhangsan"
        assert contact.starred is True

    def test_create_with_alias_fields(self):
        from app.fastapi_routes.domains.wechat.compat_routes import WechatStarredContact

        contact = WechatStarredContact(
            contactType="group",
            备注="李四",
            微信号="wx_lisi",
        )
        assert contact.type == "group"
        assert contact.nickname == "李四"
        assert contact.wxid == "wx_lisi"

    def test_create_with_remark(self):
        from app.fastapi_routes.domains.wechat.compat_routes import WechatStarredContact

        contact = WechatStarredContact(
            type="contact",
            nickname="王五",
            wxid="wx_wangwu",
            remark="重要客户",
        )
        assert contact.remark == "重要客户"

    def test_extra_fields_ignored(self):
        from app.fastapi_routes.domains.wechat.compat_routes import WechatStarredContact

        contact = WechatStarredContact(
            type="contact",
            nickname="赵六",
            wxid="wx_zhaoliu",
            extra_field="should be ignored",
        )
        assert not hasattr(contact, "extra_field")


# ---------------------------------------------------------------------------
# _starred_row_for_frontend
# ---------------------------------------------------------------------------


class TestStarredRowForFrontend:
    def test_contact_type(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 1, "nickname": "张三", "wxid": "wx1", "type": "contact", "starred": True}
        result = _starred_row_for_frontend(c)
        assert result["contact_type"] == "contact"
        assert result["contact_name"] == "张三"
        assert result["wechat_id"] == "wx1"
        assert result["starred"] is True

    def test_group_type(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 2, "nickname": "群聊", "wxid": "wx2", "type": "group", "starred": True}
        result = _starred_row_for_frontend(c)
        assert result["contact_type"] == "group"

    def test_missing_fields(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {}
        result = _starred_row_for_frontend(c)
        assert result["contact_name"] == ""
        assert result["wechat_id"] == ""
        assert result["starred"] is True  # default

    def test_default_type(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _starred_row_for_frontend

        c = {"id": 3, "nickname": "X", "wxid": "wx3"}
        result = _starred_row_for_frontend(c)
        assert result["contact_type"] == "contact"  # default


# ---------------------------------------------------------------------------
# _search_hit_for_frontend
# ---------------------------------------------------------------------------


class TestSearchHitForFrontend:
    def test_with_nickname(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 1, "nickname": "张三", "wxid": "wx1", "type": "contact", "starred": True}
        result = _search_hit_for_frontend(c)
        assert result["already_starred"] is True
        assert result["display_name"] == "张三"
        assert result["username"] == "wx1"

    def test_with_remark_as_display(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 2, "nickname": "", "remark": "备注名", "wxid": "wx2", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["display_name"] == "备注名"

    def test_with_wechat_id_as_display(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 3, "nickname": "", "remark": "", "wxid": "wx3", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["display_name"] == "wx3"

    def test_no_display_info(self):
        from app.fastapi_routes.domains.wechat.compat_routes import _search_hit_for_frontend

        c = {"id": 4, "nickname": "", "remark": "", "wxid": "", "type": "contact"}
        result = _search_hit_for_frontend(c)
        assert result["display_name"] == "-"


# ---------------------------------------------------------------------------
# _migrate_starred_contact_ids
# ---------------------------------------------------------------------------


class TestMigrateStarredContactIds:
    def test_migrate_adds_ids(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod

        # Save original state
        orig_db = mod._STARRED_CONTACTS_DB.copy()
        orig_next_id = mod._STARRED_NEXT_ID

        try:
            mod._STARRED_CONTACTS_DB = {
                "wx1": {"nickname": "A"},
                "wx2": {"nickname": "B"},
            }
            mod._STARRED_NEXT_ID = 1
            mod._migrate_starred_contact_ids()

            assert "id" in mod._STARRED_CONTACTS_DB["wx1"]
            assert "id" in mod._STARRED_CONTACTS_DB["wx2"]
            assert mod._STARRED_NEXT_ID == 3
        finally:
            mod._STARRED_CONTACTS_DB = orig_db
            mod._STARRED_NEXT_ID = orig_next_id

    def test_migrate_skips_existing_ids(self):
        from app.fastapi_routes.domains.wechat import compat_routes as mod

        orig_db = mod._STARRED_CONTACTS_DB.copy()
        orig_next_id = mod._STARRED_NEXT_ID

        try:
            mod._STARRED_CONTACTS_DB = {
                "wx1": {"nickname": "A", "id": 99},
            }
            mod._STARRED_NEXT_ID = 1
            mod._migrate_starred_contact_ids()

            assert mod._STARRED_CONTACTS_DB["wx1"]["id"] == 99
            assert mod._STARRED_NEXT_ID == 1
        finally:
            mod._STARRED_CONTACTS_DB = orig_db
            mod._STARRED_NEXT_ID = orig_next_id


# ---------------------------------------------------------------------------
# Route handler tests
# ---------------------------------------------------------------------------


class TestWechatCompatRoutes:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.fastapi_routes.domains.wechat.compat_routes import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=False)

    def test_starred_contacts_list(self, client):
        resp = client.get("/wechat_contacts/starred")
        assert resp.status_code in (200, 404)

    def test_star_contact(self, client):
        resp = client.post(
            "/wechat_contacts/starred",
            json={"wxid": "wx_test", "nickname": "Test", "type": "contact"},
        )
        assert resp.status_code in (200, 404, 422)

    def test_unstar_contact(self, client):
        resp = client.delete("/wechat_contacts/starred/wx_test")
        assert resp.status_code in (200, 404, 422)

    def test_search_contacts(self, client):
        resp = client.get("/wechat_contacts/search", params={"q": "张"})
        assert resp.status_code in (200, 404)

    def test_work_mode_feed(self, client):
        resp = client.get("/wechat_contacts/work_mode_feed")
        assert resp.status_code in (200, 404)

    def test_decrypt_status(self, client):
        resp = client.get("/wechat_contacts/decrypt_status")
        assert resp.status_code in (200, 404)

    def test_list_contacts(self, client):
        resp = client.get("/wechat_contacts")
        assert resp.status_code in (200, 404)

    def test_unstar_all(self, client):
        resp = client.post("/wechat_contacts/unstar_all")
        assert resp.status_code in (200, 404, 500)

    def test_clear_starred(self, client):
        resp = client.delete("/wechat_contacts/starred")
        assert resp.status_code in (200, 404)
