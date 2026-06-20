"""wechat/compat_routes 路由测试 — 覆盖星标联系人 CRUD、搜索、解密状态等。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import compat_routes


@pytest.fixture(autouse=True)
def _reset_starred_db():
    """每个测试前后清空全局星标联系人 DB，避免测试间干扰。"""
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
# 纯函数
# ---------------------------------------------------------------------------


class TestStarredRowForFrontend:
    def test_basic_contact(self):
        row = compat_routes._starred_row_for_frontend(
            {
                "id": 1,
                "nickname": "张三",
                "remark": "备注",
                "wxid": "wx_zhang",
                "type": "contact",
                "starred": True,
            }
        )
        assert row["id"] == 1
        assert row["contact_name"] == "张三"
        assert row["remark"] == "备注"
        assert row["wechat_id"] == "wx_zhang"
        assert row["contact_type"] == "contact"
        assert row["starred"] is True

    def test_group_type(self):
        row = compat_routes._starred_row_for_frontend(
            {"id": 2, "nickname": "群聊", "wxid": "wx_group", "type": "group"}
        )
        assert row["contact_type"] == "group"

    def test_missing_fields_default(self):
        row = compat_routes._starred_row_for_frontend({"id": 3})
        assert row["contact_name"] == ""
        assert row["remark"] == ""
        assert row["wechat_id"] == ""
        assert row["contact_type"] == "contact"
        assert row["starred"] is True


class TestSearchHitForFrontend:
    def test_display_name_from_nickname(self):
        hit = compat_routes._search_hit_for_frontend(
            {"id": 1, "nickname": "李四", "wxid": "wx_lisi", "type": "contact"}
        )
        assert hit["display_name"] == "李四"
        assert hit["already_starred"] is True

    def test_display_name_fallback_to_remark(self):
        hit = compat_routes._search_hit_for_frontend(
            {"id": 2, "remark": "备注名", "wxid": "wx_r", "type": "contact"}
        )
        assert hit["display_name"] == "备注名"

    def test_display_name_fallback_to_wechat_id(self):
        hit = compat_routes._search_hit_for_frontend(
            {"id": 3, "wxid": "wx_only", "type": "contact"}
        )
        assert hit["display_name"] == "wx_only"

    def test_display_name_empty_fallback(self):
        hit = compat_routes._search_hit_for_frontend({"id": 4})
        assert hit["display_name"] == "-"


class TestMigrateStarredContactIds:
    def test_assigns_ids(self):
        compat_routes._STARRED_CONTACTS_DB["wx_a"] = {"nickname": "A", "wxid": "wx_a"}
        compat_routes._STARRED_CONTACTS_DB["wx_b"] = {"nickname": "B", "wxid": "wx_b"}
        compat_routes._migrate_starred_contact_ids()
        assert "id" in compat_routes._STARRED_CONTACTS_DB["wx_a"]
        assert "id" in compat_routes._STARRED_CONTACTS_DB["wx_b"]

    def test_no_overwrite_existing_id(self):
        compat_routes._STARRED_CONTACTS_DB["wx_a"] = {"id": 99, "nickname": "A", "wxid": "wx_a"}
        compat_routes._migrate_starred_contact_ids()
        assert compat_routes._STARRED_CONTACTS_DB["wx_a"]["id"] == 99


# ---------------------------------------------------------------------------
# 路由测试
# ---------------------------------------------------------------------------


class TestWechatContactsListCompat:
    def test_empty_list(self, client: TestClient):
        r = client.get("/wechat_contacts")
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["data"] == []

    def test_filter_by_type(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "type": "contact",
            "nickname": "A",
            "wxid": "wx1",
            "starred": True,
        }
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "type": "group",
            "nickname": "G",
            "wxid": "wx2",
            "starred": True,
        }
        r = client.get("/wechat_contacts", params={"type": "group"})
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["contact_type"] == "group"

    def test_filter_by_keyword(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "type": "contact",
            "nickname": "张三",
            "wxid": "wx1",
            "starred": True,
        }
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "type": "contact",
            "nickname": "李四",
            "wxid": "wx2",
            "starred": True,
        }
        r = client.get("/wechat_contacts", params={"keyword": "张"})
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["contact_name"] == "张三"


class TestWechatContactsSearchCompat:
    def test_empty_query(self, client: TestClient):
        r = client.get("/wechat_contacts/search")
        assert r.json()["results"] == []

    def test_search_by_nickname(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "王五",
            "wxid": "wx_wang",
            "type": "contact",
            "starred": True,
        }
        r = client.get("/wechat_contacts/search", params={"q": "王"})
        assert len(r.json()["results"]) == 1

    def test_search_by_keyword_param(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "赵六",
            "wxid": "wx_zhao",
            "type": "contact",
            "starred": True,
        }
        r = client.get("/wechat_contacts/search", params={"keyword": "赵"})
        assert len(r.json()["results"]) == 1

    def test_search_no_match(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "nickname": "A",
            "wxid": "wx1",
            "type": "contact",
            "starred": True,
        }
        r = client.get("/wechat_contacts/search", params={"q": "zzz"})
        assert r.json()["results"] == []


class TestWechatContactsCreateCompat:
    def test_create_success(self, client: TestClient):
        r = client.post(
            "/wechat_contacts", json={"wechat_id": "wx_new", "contact_name": "新联系人"}
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert "id" in r.json()["data"]

    def test_create_empty_wechat_id(self, client: TestClient):
        r = client.post("/wechat_contacts", json={"wechat_id": "", "contact_name": "空"})
        assert r.status_code == 400

    def test_create_with_alias_fields(self, client: TestClient):
        r = client.post(
            "/wechat_contacts",
            json={
                "wxid": "wx_alias",
                "nickname": "别名",
                "remark": "备注",
                "contact_type": "group",
            },
        )
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestWechatStarredList:
    def test_empty(self, client: TestClient):
        r = client.get("/wechat_contacts/starred")
        assert r.json()["total"] == 0

    def test_with_data(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "type": "contact",
            "nickname": "A",
            "wxid": "wx1",
            "starred": True,
        }
        r = client.get("/wechat_contacts/starred")
        assert r.json()["total"] == 1

    def test_filter_type(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 1,
            "type": "contact",
            "nickname": "A",
            "wxid": "wx1",
            "starred": True,
        }
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {
            "id": 2,
            "type": "group",
            "nickname": "G",
            "wxid": "wx2",
            "starred": True,
        }
        r = client.get("/wechat_contacts/starred", params={"type": "group"})
        assert r.json()["total"] == 1


class TestWechatStarredAdd:
    def test_add_success(self, client: TestClient):
        r = client.post("/wechat_contacts/starred", json={"wxid": "wx_star", "nickname": "星标"})
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert r.json()["data"]["wxid"] == "wx_star"

    def test_add_empty_wxid(self, client: TestClient):
        r = client.post("/wechat_contacts/starred", json={"wxid": ""})
        assert r.status_code == 400


class TestWechatStarredDelete:
    def test_delete_existing(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx_del"] = {
            "id": 1,
            "wxid": "wx_del",
            "nickname": "Del",
            "starred": True,
        }
        r = client.delete("/wechat_contacts/starred/wx_del")
        assert r.json()["success"] is True
        assert "wx_del" not in compat_routes._STARRED_CONTACTS_DB

    def test_delete_nonexistent(self, client: TestClient):
        r = client.delete("/wechat_contacts/starred/wx_none")
        assert r.json()["success"] is False


class TestWechatStarredClear:
    def test_clear(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
        compat_routes._STARRED_CONTACTS_DB["wx2"] = {"id": 2, "wxid": "wx2"}
        r = client.delete("/wechat_contacts/starred")
        assert r.json()["success"] is True
        assert len(compat_routes._STARRED_CONTACTS_DB) == 0


class TestWechatContactsUnstarAll:
    def test_unstar_all(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
        # 路由是 async def 调用 await wechat_starred_clear()，
        # 需要用 AsyncMock 使 await 正常工作
        async_mock = AsyncMock(return_value={"success": True, "message": "已清除 1 个星标"})
        with patch.object(compat_routes, "wechat_starred_clear", async_mock):
            r = client.post("/wechat_contacts/unstar_all")
            assert r.json()["success"] is True

    def test_unstar_all_empty(self, client: TestClient):
        async_mock = AsyncMock(return_value={"success": True, "message": "已清除 0 个星标"})
        with patch.object(compat_routes, "wechat_starred_clear", async_mock):
            r = client.post("/wechat_contacts/unstar_all")
            assert r.json()["success"] is True


class TestWechatContactsDeleteCompat:
    def test_delete_by_id(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10,
            "wxid": "wx1",
            "nickname": "A",
            "starred": True,
        }
        r = client.delete("/wechat_contacts/10")
        assert r.json()["success"] is True

    def test_delete_nonexistent(self, client: TestClient):
        r = client.delete("/wechat_contacts/999")
        assert r.json()["success"] is False


class TestWechatContactsUpdateCompat:
    def test_update_success(self, client: TestClient):
        compat_routes._STARRED_CONTACTS_DB["wx1"] = {
            "id": 10,
            "wxid": "wx1",
            "nickname": "旧名",
            "remark": "",
            "type": "contact",
            "starred": True,
        }
        r = client.put("/wechat_contacts/10", json={"contact_name": "新名", "remark": "新备注"})
        assert r.json()["success"] is True
        assert r.json()["data"]["contact_name"] == "新名"

    def test_update_nonexistent(self, client: TestClient):
        r = client.put("/wechat_contacts/999", json={"contact_name": "X"})
        assert r.json()["success"] is False


class TestWechatContactsContextCompat:
    def test_context(self, client: TestClient):
        r = client.get("/wechat_contacts/1/context")
        assert r.json()["success"] is True
        assert r.json()["messages"] == []


class TestWechatContactsRefreshMessagesCompat:
    def test_refresh(self, client: TestClient):
        r = client.post("/wechat_contacts/1/refresh_messages")
        assert r.json()["success"] is True


class TestWechatContactsRefreshMessagesCache:
    def test_refresh(self, client: TestClient):
        r = client.post("/wechat_contacts/refresh_messages_cache")
        assert r.json()["success"] is True


class TestWechatContactsRefreshContactCache:
    def test_refresh(self, client: TestClient):
        r = client.post("/wechat_contacts/refresh_contact_cache")
        assert r.json()["success"] is True


class TestWechatWorkModeFeed:
    def test_no_decrypt_config(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", "/nonexistent/path")
        r = client.get("/wechat_contacts/work_mode_feed")
        assert r.status_code == 200
        assert "error" in r.json() or r.json()["items"] == []


class TestWechatContactsDecryptStatus:
    def test_no_path(self, client: TestClient, monkeypatch):
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
        r = client.get("/wechat_contacts/decrypt_status")
        assert r.json()["success"] is True
        assert r.json()["contact_db_exists"] is False

    def test_with_env_path_not_exists(self, client: TestClient, monkeypatch):
        monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", "/nonexistent/db.sqlite")
        r = client.get("/wechat_contacts/decrypt_status")
        assert r.json()["contact_db_exists"] is False

    def test_with_decrypt_path_fallback(self, client: TestClient, monkeypatch, tmp_path):
        monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
        monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(tmp_path))
        r = client.get("/wechat_contacts/decrypt_status")
        assert r.json()["success"] is True
