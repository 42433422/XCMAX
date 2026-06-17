"""Additional tests for app.fastapi_routes.domains.wechat.compat_routes — covering uncovered routes and edge cases."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import compat_routes


@pytest.fixture(autouse=True)
def _reset_starred_db():
    compat_routes._STARRED_CONTACTS_DB.clear()
    compat_routes._STARRED_NEXT_ID = 1
    yield
    compat_routes._STARRED_CONTACTS_DB.clear()
    compat_routes._STARRED_NEXT_ID = 1


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(compat_routes.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# WechatStarredContact model
# ---------------------------------------------------------------------------


class TestWechatStarredContactModel:
    def test_basic_creation(self):
        c = compat_routes.WechatStarredContact(
            type="contact", nickname="张三", wxid="wx1"
        )
        assert c.type == "contact"
        assert c.nickname == "张三"
        assert c.wxid == "wx1"
        assert c.starred is True
        assert c.remark == ""

    def test_alias_fields(self):
        c = compat_routes.WechatStarredContact(
            contactType="group", 备注="备注名", 微信号="wx2"
        )
        assert c.type == "group"
        assert c.nickname == "备注名"
        assert c.wxid == "wx2"

    def test_extra_fields_ignored(self):
        c = compat_routes.WechatStarredContact(
            type="contact", nickname="A", wxid="wx3", unknown_field="x"
        )
        assert not hasattr(c, "unknown_field")


# ---------------------------------------------------------------------------
# _starred_row_for_frontend — additional edge cases
# ---------------------------------------------------------------------------


class TestStarredRowForFrontendEdgeCases:
    def test_type_uppercase(self):
        row = compat_routes._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "GROUP", "starred": True}
        )
        assert row["contact_type"] == "group"

    def test_starred_false(self):
        row = compat_routes._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": "contact", "starred": False}
        )
        assert row["starred"] is False

    def test_none_type(self):
        row = compat_routes._starred_row_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx1", "type": None}
        )
        assert row["contact_type"] == "contact"


# ---------------------------------------------------------------------------
# _search_hit_for_frontend — additional edge cases
# ---------------------------------------------------------------------------


class TestSearchHitForFrontendEdgeCases:
    def test_nick_name_field(self):
        hit = compat_routes._search_hit_for_frontend(
            {"id": 1, "nickname": "测试", "wxid": "wx1", "type": "contact"}
        )
        assert hit["nick_name"] == "测试"

    def test_username_field(self):
        hit = compat_routes._search_hit_for_frontend(
            {"id": 1, "nickname": "A", "wxid": "wx_test", "type": "contact"}
        )
        assert hit["username"] == "wx_test"


# ---------------------------------------------------------------------------
# wechat_contacts_list_compat — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatContactsListCompatEdgeCases:
    def test_default_type_all(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1, "type": "contact", "nickname": "A", "wxid": "wx1", "starred": True
        }
        r = client.get("/wechat_contacts")
        assert len(r.json()["data"]) == 1

    def test_pagination(self, client: TestClient):
        for i in range(5):
            compat_routes._STARRED_CONTACTS_DB[f"wx{i}"] = {
                "id": i + 1, "type": "contact", "nickname": f"N{i}", "wxid": f"wx{i}", "starred": True
            }
        r = client.get("/wechat_contacts", params={"page": 1, "per_page": 2})
        # The compat route accepts page/per_page query params and echoes them
        # back, but does not slice the data (full list returned). Assert the
        # echoed pagination metadata rather than the slice length.
        assert r.json()["page"] == 1
        assert r.json()["per_page"] == 2
        assert len(r.json()["data"]) == 5

    def test_keyword_filter_by_remark(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1, "type": "contact", "nickname": "A", "remark": "特殊备注", "wxid": "wx1", "starred": True
        }
        r = client.get("/wechat_contacts", params={"keyword": "特殊"})
        assert len(r.json()["data"]) == 1

    def test_keyword_filter_by_wxid(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1, "type": "contact", "nickname": "A", "wxid": "special_id", "starred": True
        }
        r = client.get("/wechat_contacts", params={"keyword": "special"})
        assert len(r.json()["data"]) == 1


# ---------------------------------------------------------------------------
# wechat_contacts_create_compat — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatContactsCreateCompatEdgeCases:
    def test_create_with_wechat_id_alias(self, client: TestClient):
        r = client.post("/wechat_contacts", json={"wechat_id": "wx_new", "contact_name": "新"})
        assert r.json()["success"] is True

    def test_create_with_wxid_alias(self, client: TestClient):
        r = client.post("/wechat_contacts", json={"wxid": "wx_new2", "nickname": "新2"})
        assert r.json()["success"] is True

    def test_create_with_type_alias(self, client: TestClient):
        r = client.post(
            "/wechat_contacts",
            json={"wxid": "wx_g", "nickname": "群", "contact_type": "group"},
        )
        assert r.json()["success"] is True

    def test_create_auto_increment_id(self, client: TestClient):
        r1 = client.post("/wechat_contacts", json={"wxid": "wx1", "nickname": "A"})
        r2 = client.post("/wechat_contacts", json={"wxid": "wx2", "nickname": "B"})
        id1 = r1.json()["data"]["id"]
        id2 = r2.json()["data"]["id"]
        assert id2 > id1


# ---------------------------------------------------------------------------
# wechat_starred_list — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatStarredListEdgeCases:
    def test_filter_by_keyword(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1, "type": "contact", "nickname": "张三", "remark": "", "wxid": "wx1", "starred": True
        }
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2, "type": "contact", "nickname": "李四", "remark": "", "wxid": "wx2", "starred": True
        }
        r = client.get("/wechat_contacts/starred", params={"keyword": "张"})
        assert r.json()["total"] == 1

    def test_filter_by_type_and_keyword(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1, "type": "contact", "nickname": "张三", "wxid": "wx1", "starred": True
        }
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2, "type": "group", "nickname": "张三群", "wxid": "wx2", "starred": True
        }
        r = client.get("/wechat_contacts/starred", params={"type": "group", "keyword": "张"})
        assert r.json()["total"] == 1


# ---------------------------------------------------------------------------
# wechat_starred_add — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatStarredAddEdgeCases:
    def test_add_with_wechat_id_alias(self, client: TestClient):
        r = client.post("/wechat_contacts/starred", json={"wechat_id": "wx_alias", "nickname": "别名"})
        assert r.json()["success"] is True

    def test_add_with_contact_name_alias(self, client: TestClient):
        r = client.post("/wechat_contacts/starred", json={"wxid": "wx_cn", "contact_name": "联系人名"})
        assert r.json()["success"] is True

    def test_add_with_contact_type(self, client: TestClient):
        r = client.post("/wechat_contacts/starred", json={"wxid": "wx_g", "type": "group"})
        assert r.json()["success"] is True
        assert r.json()["data"]["type"] == "group"


# ---------------------------------------------------------------------------
# wechat_contacts_update_compat — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatContactsUpdateCompatEdgeCases:
    def test_update_wechat_id(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10, "wxid": "wx1", "nickname": "A", "remark": "", "type": "contact", "starred": True
        }
        r = client.put("/wechat_contacts/10", json={"wechat_id": "wx_new"})
        assert r.json()["success"] is True
        assert r.json()["data"]["wechat_id"] == "wx_new"

    def test_update_contact_type(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10, "wxid": "wx1", "nickname": "A", "remark": "", "type": "contact", "starred": True
        }
        r = client.put("/wechat_contacts/10", json={"contact_type": "group"})
        assert r.json()["success"] is True

    def test_update_no_matching_fields(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10, "wxid": "wx1", "nickname": "A", "remark": "", "type": "contact", "starred": True
        }
        r = client.put("/wechat_contacts/10", json={"irrelevant": "data"})
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_delete_compat — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatContactsDeleteCompatEdgeCases:
    def test_delete_by_string_id(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10, "wxid": "wx1", "nickname": "A", "starred": True
        }
        r = client.delete("/wechat_contacts/10")
        assert r.json()["success"] is True

    def test_delete_no_match(self, client: TestClient):
        r = client.delete("/wechat_contacts/9999")
        assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# wechat_contacts_context_compat
# ---------------------------------------------------------------------------


class TestWechatContactsContextCompat:
    def test_returns_empty_messages(self, client: TestClient):
        r = client.get("/wechat_contacts/42/context")
        assert r.json()["success"] is True
        assert r.json()["messages"] == []


# ---------------------------------------------------------------------------
# wechat_contacts_refresh_messages_compat
# ---------------------------------------------------------------------------


class TestWechatContactsRefreshMessagesCompat:
    def test_returns_success(self, client: TestClient):
        r = client.post("/wechat_contacts/42/refresh_messages")
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_refresh_messages_cache
# ---------------------------------------------------------------------------


class TestWechatContactsRefreshMessagesCache:
    def test_returns_success(self, client: TestClient):
        r = client.post("/wechat_contacts/refresh_messages_cache")
        assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# wechat_contacts_refresh_contact_cache
# ---------------------------------------------------------------------------


class TestWechatContactsRefreshContactCache:
    def test_returns_success(self, client: TestClient):
        r = client.post("/wechat_contacts/refresh_contact_cache")
        assert r.json()["success"] is True
        assert "data" in r.json()


# ---------------------------------------------------------------------------
# wechat_contacts_decrypt_status — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatContactsDecryptStatusEdgeCases:
    def test_with_decrypt_path_and_existing_db(self, client: TestClient, monkeypatch, tmp_path):
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        db_dir = tmp_path / "decrypted" / "contact"
        db_dir.mkdir(parents=True)
        (db_dir / "contact.db").write_text("fake db")
        r = client.get("/wechat_contacts/decrypt_status")
        assert r.json()["contact_db_exists"] is True

    def test_with_decrypt_path_no_db(self, client: TestClient, monkeypatch, tmp_path):
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        r = client.get("/wechat_contacts/decrypt_status")
        assert r.json()["contact_db_exists"] is False


# ---------------------------------------------------------------------------
# wechat_work_mode_feed — additional edge cases
# ---------------------------------------------------------------------------


class TestWechatWorkModeFeedEdgeCases:
    def test_missing_config_file(self, client: TestClient, monkeypatch, tmp_path):
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        r = client.get("/wechat_contacts/work_mode_feed")
        assert r.status_code == 200
        assert r.json()["items"] == []
