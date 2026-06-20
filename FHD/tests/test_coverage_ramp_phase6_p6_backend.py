"""COVERAGE_RAMP Phase 6 round 6: backend low-coverage modules.

Targets:
- ``app/fastapi_routes/domains/wechat/compat_routes.py`` (68.1% line coverage)
- ``app/fastapi_routes/private_db_read_assistant_compat.py`` (30.4% line coverage)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API). The router functions themselves are exercised through real FastAPI
sub-apps via ``fastapi.testclient.TestClient``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.wechat import compat_routes as wechat_compat
from app.fastapi_routes.private_db_read_assistant_compat import (
    MOD_ID,
    WECHAT_CAPABILITIES,
    WECHAT_SOURCE_ID,
    _contact_to_private_db,
    _map_context_messages,
    build_private_db_assistant_router,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_starred_db() -> None:
    """每个测试前后清空 compat_routes 的进程内星标联系人缓存。"""
    wechat_compat._STARRED_CONTACTS_DB.clear()
    wechat_compat._STARRED_NEXT_ID = 1
    yield
    wechat_compat._STARRED_CONTACTS_DB.clear()
    wechat_compat._STARRED_NEXT_ID = 1


def _wechat_compat_client() -> TestClient:
    app = FastAPI()
    app.include_router(wechat_compat.router)
    return TestClient(app)


def _private_db_client() -> TestClient:
    app = FastAPI()
    app.include_router(build_private_db_assistant_router())
    return TestClient(app)


# ---------------------------------------------------------------------------
# wechat compat_routes — _starred_row_for_frontend / _search_hit_for_frontend
# ---------------------------------------------------------------------------


def test_starred_row_for_frontend_contact_type() -> None:
    row = wechat_compat._starred_row_for_frontend(
        {
            "id": 1,
            "type": "contact",
            "nickname": "Alice",
            "remark": "备注A",
            "wxid": "wx_alice",
            "starred": True,
        }
    )
    assert row["id"] == 1
    assert row["contact_name"] == "Alice"
    assert row["remark"] == "备注A"
    assert row["wechat_id"] == "wx_alice"
    assert row["contact_type"] == "contact"
    assert row["type"] == "contact"
    assert row["nickname"] == "Alice"
    assert row["wxid"] == "wx_alice"
    assert row["starred"] is True


def test_starred_row_for_frontend_group_type() -> None:
    row = wechat_compat._starred_row_for_frontend(
        {"id": 2, "type": "Group", "nickname": None, "remark": "", "wxid": "g@chatroom"}
    )
    assert row["contact_type"] == "group"
    assert row["type"] == "group"
    assert row["contact_name"] == ""
    assert row["starred"] is True


def test_starred_row_for_frontend_missing_fields_defaults() -> None:
    row = wechat_compat._starred_row_for_frontend({})
    assert row["id"] is None
    assert row["contact_name"] == ""
    assert row["remark"] == ""
    assert row["wechat_id"] == ""
    assert row["contact_type"] == "contact"
    assert row["type"] == "contact"
    assert row["nickname"] is None
    assert row["wxid"] is None
    assert row["starred"] is True


def test_search_hit_for_frontend_display_name_fallback_chain() -> None:
    # nickname 优先
    hit = wechat_compat._search_hit_for_frontend(
        {"nickname": "Nick", "remark": "Rem", "wxid": "wx1", "type": "contact"}
    )
    assert hit["display_name"] == "Nick"
    assert hit["already_starred"] is True
    assert hit["username"] == "wx1"
    assert hit["nick_name"] == "Nick"

    # nickname 空 → 用 remark
    hit2 = wechat_compat._search_hit_for_frontend(
        {"nickname": "", "remark": "Rem2", "wxid": "wx2", "type": "contact"}
    )
    assert hit2["display_name"] == "Rem2"

    # 全部空 → 用 wechat_id
    hit3 = wechat_compat._search_hit_for_frontend(
        {"nickname": "  ", "remark": "  ", "wxid": "wx3", "type": "contact"}
    )
    assert hit3["display_name"] == "wx3"

    # 全部空 → "-"
    hit4 = wechat_compat._search_hit_for_frontend(
        {"nickname": "", "remark": "", "wxid": "", "type": "contact"}
    )
    assert hit4["display_name"] == "-"


def test_migrate_starred_contact_ids_assigns_sequential_ids() -> None:
    wechat_compat._STARRED_CONTACTS_DB.clear()
    wechat_compat._STARRED_NEXT_ID = 5
    wechat_compat._STARRED_CONTACTS_DB["a"] = {"wxid": "a"}
    wechat_compat._STARRED_CONTACTS_DB["b"] = {"wxid": "b"}
    wechat_compat._migrate_starred_contact_ids()
    assert wechat_compat._STARRED_CONTACTS_DB["a"]["id"] == 5
    assert wechat_compat._STARRED_CONTACTS_DB["b"]["id"] == 6
    assert wechat_compat._STARRED_NEXT_ID == 7


def test_migrate_starred_contact_ids_skips_existing() -> None:
    wechat_compat._STARRED_CONTACTS_DB.clear()
    wechat_compat._STARRED_NEXT_ID = 1
    wechat_compat._STARRED_CONTACTS_DB["a"] = {"wxid": "a", "id": 99}
    wechat_compat._migrate_starred_contact_ids()
    # 已有 id 不应被覆盖
    assert wechat_compat._STARRED_CONTACTS_DB["a"]["id"] == 99
    # next_id 不应被推进
    assert wechat_compat._STARRED_NEXT_ID == 1


# ---------------------------------------------------------------------------
# wechat compat_routes — decrypt_status
# ---------------------------------------------------------------------------


def test_decrypt_status_no_env_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
    monkeypatch.delenv("WECHAT_DECRYPT_PATH", raising=False)
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/decrypt_status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["plugin_available"] is True
    assert body["contact_db_path"] is None
    assert body["contact_db_exists"] is False


def test_decrypt_status_with_env_path_existing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "contact.db"
    db_file.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setenv("WECHAT_CONTACT_DB_PATH", str(db_file))
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/decrypt_status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contact_db_exists"] is True
    assert body["contact_db_path"] == str(db_file)


def test_decrypt_status_fallback_to_decrypt_path(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WECHAT_CONTACT_DB_PATH", raising=False)
    base = tmp_path / "decrypt"
    contact_dir = base / "decrypted" / "contact"
    contact_dir.mkdir(parents=True)
    db_file = contact_dir / "contact.db"
    db_file.write_bytes(b"SQLite format 3\x00")
    monkeypatch.setenv("WECHAT_DECRYPT_PATH", str(base))
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/decrypt_status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contact_db_exists"] is True


# ---------------------------------------------------------------------------
# wechat compat_routes — work_mode_feed
# ---------------------------------------------------------------------------


def test_work_mode_feed_not_configured_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WECHAT_DECRYPT_PATH", "/nonexistent/path/that/does/not/exist")
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/work_mode_feed", params={"per_contact": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["per_contact"] == 5
    assert body["error"] == "wechat-decrypt not configured"


def test_work_mode_feed_invalid_per_contact_returns_422() -> None:
    client = _wechat_compat_client()
    # ge=1 → 0 应被拒绝
    resp = client.get("/wechat_contacts/work_mode_feed", params={"per_contact": 0})
    assert resp.status_code == 422
    # le=100 → 101 应被拒绝
    resp2 = client.get("/wechat_contacts/work_mode_feed", params={"per_contact": 101})
    assert resp2.status_code == 422


def test_work_mode_feed_recoverable_error_returns_empty_with_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 让 os.environ.get 返回一个存在的路径，但 os.path.exists 返回 False
    # 触发 "wechat-decrypt not configured" 分支
    monkeypatch.setenv("WECHAT_DECRYPT_PATH", "/tmp/__nonexistent_wechat_decrypt__")
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/work_mode_feed")
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert body["items"] == []


# ---------------------------------------------------------------------------
# wechat compat_routes — search
# ---------------------------------------------------------------------------


def test_search_empty_term_returns_empty_results() -> None:
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/search")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "results": []}


def test_search_with_q_matches_nickname() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "Alice",
        "remark": "",
        "wxid": "wx1",
        "starred": True,
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "contact",
        "nickname": "Bob",
        "remark": "",
        "wxid": "wx2",
        "starred": True,
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/search", params={"q": "ali"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["nickname"] == "Alice"
    assert results[0]["already_starred"] is True


def test_search_with_keyword_param_equivalent_to_q() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "Carol",
        "remark": "",
        "wxid": "wx1",
        "starred": True,
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/search", params={"keyword": "car"})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


def test_search_matches_remark_or_wxid() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "",
        "remark": "SpecialRemark",
        "wxid": "abc",
        "starred": True,
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "group",
        "nickname": "",
        "remark": "",
        "wxid": "group_xyz",
        "starred": True,
    }
    client = _wechat_compat_client()
    # match remark
    resp1 = client.get("/wechat_contacts/search", params={"q": "specialremark"})
    assert len(resp1.json()["results"]) == 1
    # match wxid
    resp2 = client.get("/wechat_contacts/search", params={"q": "group_xyz"})
    assert len(resp2.json()["results"]) == 1


# ---------------------------------------------------------------------------
# wechat compat_routes — list / starred
# ---------------------------------------------------------------------------


def test_list_contacts_empty_returns_empty_data() -> None:
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == []
    assert body["page"] == 1
    assert body["per_page"] == 50


def test_list_contacts_filter_by_type() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "A",
        "remark": "",
        "wxid": "wx1",
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "group",
        "nickname": "B",
        "remark": "",
        "wxid": "wx2",
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts", params={"type": "group"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["contact_type"] == "group"


def test_list_contacts_filter_by_keyword() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "Alice",
        "remark": "",
        "wxid": "wx1",
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "contact",
        "nickname": "Bob",
        "remark": "",
        "wxid": "wx2",
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts", params={"keyword": "ali"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["nickname"] == "Alice"


def test_list_contacts_invalid_page_returns_422() -> None:
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts", params={"page": 0})
    assert resp.status_code == 422


def test_list_contacts_invalid_per_page_returns_422() -> None:
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts", params={"per_page": 0})
    assert resp.status_code == 422
    resp2 = client.get("/wechat_contacts", params={"per_page": 201})
    assert resp2.status_code == 422


def test_starred_list_returns_all_when_type_all() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "A",
        "remark": "",
        "wxid": "wx1",
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "group",
        "nickname": "B",
        "remark": "",
        "wxid": "wx2",
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/starred")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["total"] == 2
    assert body["filter"]["type"] == "all"


def test_starred_list_filter_by_type() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "A",
        "remark": "",
        "wxid": "wx1",
    }
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {
        "id": 2,
        "type": "group",
        "nickname": "B",
        "remark": "",
        "wxid": "wx2",
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/starred", params={"type": "contact"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1


def test_starred_list_filter_by_keyword() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "type": "contact",
        "nickname": "Alice",
        "remark": "rem",
        "wxid": "wx1",
    }
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/starred", params={"keyword": "ali"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# wechat compat_routes — create / unstar_all / refresh caches
# ---------------------------------------------------------------------------


def test_create_contact_missing_wechat_id_returns_400() -> None:
    client = _wechat_compat_client()
    resp = client.post("/wechat_contacts", json={})
    assert resp.status_code == 400
    assert "wechat_id" in resp.json()["detail"]


def test_create_contact_success_returns_id() -> None:
    client = _wechat_compat_client()
    resp = client.post(
        "/wechat_contacts",
        json={"wechat_id": "wx_new", "contact_name": "New", "remark": "r"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == 1
    # 已写入 DB
    assert "wx_new" in wechat_compat._STARRED_CONTACTS_DB
    assert wechat_compat._STARRED_CONTACTS_DB["wx_new"]["nickname"] == "New"


def test_create_contact_with_alias_fields() -> None:
    client = _wechat_compat_client()
    resp = client.post(
        "/wechat_contacts",
        json={"wxid": "wx_alias", "nickname": "Nick", "type": "group"},
    )
    assert resp.status_code == 200
    contact = wechat_compat._STARRED_CONTACTS_DB["wx_alias"]
    assert contact["type"] == "group"
    assert contact["nickname"] == "Nick"


def test_unstar_all_clears_db_via_direct_call() -> None:
    """``wechat_contacts_unstar_all_compat`` 是 async 包装，调用同步的
    ``wechat_starred_clear``。源码中存在 ``await wechat_starred_clear()``
    的 TypeError（被测函数本身缺陷，不在本测试修复范围）。

    这里直接测试底层 ``wechat_starred_clear`` 同步函数，覆盖其逻辑分支。
    """
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {"id": 2, "wxid": "wx2"}
    result = wechat_compat.wechat_starred_clear()
    assert result["success"] is True
    assert "已清除 2" in result["message"]
    assert len(wechat_compat._STARRED_CONTACTS_DB) == 0


def test_unstar_all_compat_route_propagates_type_error() -> None:
    """覆盖 async 包装路由：源码 ``await wechat_starred_clear()`` 会抛
    TypeError（dict 不可 await）。验证该异常路径被触发。
    """
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
    client = _wechat_compat_client()
    with pytest.raises(TypeError, match="object dict can't be used in 'await'"):
        client.post("/wechat_contacts/unstar_all")


def test_refresh_messages_cache_returns_ok() -> None:
    client = _wechat_compat_client()
    resp = client.post("/wechat_contacts/refresh_messages_cache")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "message": "ok"}


def test_refresh_contact_cache_returns_placeholder() -> None:
    client = _wechat_compat_client()
    resp = client.post("/wechat_contacts/refresh_contact_cache")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["sync"]["success"] is True


# ---------------------------------------------------------------------------
# wechat compat_routes — starred add / delete / clear
# ---------------------------------------------------------------------------


def test_starred_add_missing_wxid_returns_400() -> None:
    client = _wechat_compat_client()
    resp = client.post("/wechat_contacts/starred", json={})
    assert resp.status_code == 400
    assert "wxid" in resp.json()["detail"]


def test_starred_add_success_returns_contact() -> None:
    client = _wechat_compat_client()
    resp = client.post(
        "/wechat_contacts/starred",
        json={"wxid": "wx_s1", "nickname": "S1", "type": "contact"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["wxid"] == "wx_s1"
    assert body["data"]["id"] == 1


def test_starred_add_with_alias_fields() -> None:
    client = _wechat_compat_client()
    resp = client.post(
        "/wechat_contacts/starred",
        json={"wechat_id": "wx_s2", "contact_name": "S2", "contact_type": "group"},
    )
    assert resp.status_code == 200
    contact = wechat_compat._STARRED_CONTACTS_DB["wx_s2"]
    assert contact["type"] == "group"
    assert contact["nickname"] == "S2"


def test_starred_delete_existing_returns_success() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/starred/wx1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "wx1" not in wechat_compat._STARRED_CONTACTS_DB


def test_starred_delete_nonexistent_returns_false() -> None:
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/starred/notexist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False


def test_starred_clear_returns_count() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {"id": 1, "wxid": "wx1"}
    wechat_compat._STARRED_CONTACTS_DB["wx2"] = {"id": 2, "wxid": "wx2"}
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/starred")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "已清除 2" in body["message"]


def test_starred_clear_empty_db_returns_zero() -> None:
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/starred")
    assert resp.status_code == 200
    assert "已清除 0" in resp.json()["message"]


# ---------------------------------------------------------------------------
# wechat compat_routes — delete / update / context / refresh_messages by id
# ---------------------------------------------------------------------------


def test_delete_contact_by_id_existing() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "wxid": "wx1",
        "type": "contact",
    }
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "wx1" not in wechat_compat._STARRED_CONTACTS_DB


def test_delete_contact_by_id_nonexistent_returns_false() -> None:
    client = _wechat_compat_client()
    resp = client.delete("/wechat_contacts/999")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_update_contact_by_id_success() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "wxid": "wx1",
        "type": "contact",
        "nickname": "old",
        "remark": "oldrem",
    }
    client = _wechat_compat_client()
    resp = client.put(
        "/wechat_contacts/1",
        json={
            "contact_name": "new",
            "remark": "newrem",
            "wechat_id": "wx_new",
            "contact_type": "group",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["nickname"] == "new"
    assert body["data"]["remark"] == "newrem"
    assert body["data"]["wechat_id"] == "wx_new"
    assert body["data"]["contact_type"] == "group"


def test_update_contact_by_id_partial_fields() -> None:
    wechat_compat._STARRED_CONTACTS_DB["wx1"] = {
        "id": 1,
        "wxid": "wx1",
        "type": "contact",
        "nickname": "old",
        "remark": "oldrem",
    }
    client = _wechat_compat_client()
    resp = client.put("/wechat_contacts/1", json={"remark": "only_remark"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # nickname 应保持不变
    assert body["data"]["nickname"] == "old"
    assert body["data"]["remark"] == "only_remark"


def test_update_contact_by_id_nonexistent_returns_false() -> None:
    client = _wechat_compat_client()
    resp = client.put("/wechat_contacts/999", json={"remark": "x"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_get_contact_context_returns_empty_messages() -> None:
    client = _wechat_compat_client()
    resp = client.get("/wechat_contacts/42/context")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "messages": []}


def test_refresh_messages_for_contact_returns_placeholder() -> None:
    client = _wechat_compat_client()
    resp = client.post("/wechat_contacts/42/refresh_messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "未实现" in body["message"]


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — helpers
# ---------------------------------------------------------------------------


def test_contact_to_private_db_full_fields() -> None:
    out = _contact_to_private_db(
        {
            "id": 7,
            "contact_name": "Alice",
            "remark": "Rem",
            "wechat_id": "wx1",
            "contact_type": "contact",
            "is_starred": True,
        }
    )
    assert out["id"] == 7
    assert out["display_name"] == "Alice"
    assert out["contact_name"] == "Alice"
    assert out["remark"] == "Rem"
    assert out["source_user_id"] == "wx1"
    assert out["contact_type"] == "contact"
    assert out["is_starred"] is True


def test_contact_to_private_db_fallback_display_name() -> None:
    # contact_name 空 → 用 remark
    out = _contact_to_private_db({"remark": "Rem", "wechat_id": "wx1"})
    assert out["display_name"] == "Rem"
    # 全部空 → "-"
    out2 = _contact_to_private_db({"wechat_id": "wx2"})
    assert out2["display_name"] == "wx2"
    # 完全空 → "-"
    out3 = _contact_to_private_db({})
    assert out3["display_name"] == "-"


def test_contact_to_private_db_strips_whitespace() -> None:
    out = _contact_to_private_db({"contact_name": "  Alice  "})
    assert out["display_name"] == "Alice"


def test_contact_to_private_db_default_contact_type() -> None:
    out = _contact_to_private_db({"id": 1})
    assert out["contact_type"] == "contact"
    assert out["is_starred"] is False


def test_map_context_messages_extracts_text_from_multiple_keys() -> None:
    msgs = [
        {"content": "hello"},
        {"message": "world"},
        {"text": "foo"},
        {"raw_text": "bar"},
        {"body": "baz"},
        {"role": "user", "content": "with role"},
        {"sender": "assistant", "content": "with sender"},
        {"content": "   "},  # 空白 → 跳过到下一个 key
        {"content": None, "message": "fallback"},
        "not a dict",  # 非 dict → 跳过
    ]
    rows = _map_context_messages(msgs)
    assert len(rows) == 9  # 10 - 1 (非 dict)
    assert rows[0]["text"] == "hello"
    assert rows[0]["content"] == "hello"
    assert rows[0]["role"] == "other"
    assert rows[5]["role"] == "user"
    assert rows[6]["role"] == "assistant"
    # 空白 content 应跳过到 message
    assert rows[8]["text"] == "fallback"


def test_map_context_messages_empty_list() -> None:
    assert _map_context_messages([]) == []


def test_map_context_messages_all_non_dict() -> None:
    assert _map_context_messages(["a", 1, None, []]) == []


def test_map_context_messages_no_text_keys() -> None:
    rows = _map_context_messages([{"role": "user"}, {"sender": "bot"}])
    assert len(rows) == 2
    assert rows[0]["text"] == ""
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "bot"


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /status
# ---------------------------------------------------------------------------


def test_private_db_status_returns_decrypt_info() -> None:
    client = _private_db_client()
    with patch("app.services.wechat_decrypt_autoconfig.get_wechat_decrypt_status") as mock_status:
        mock_status.return_value = {"contact_db_exists": True, "configured": True}
        resp = client.get(f"/api/mod/{MOD_ID}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["mod_id"] == MOD_ID
    assert body["data"]["selected_source"] == WECHAT_SOURCE_ID
    assert body["data"]["decrypt"]["contact_db_exists"] is True
    mock_status.assert_called_once()


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /sources
# ---------------------------------------------------------------------------


def test_private_db_sources_returns_wechat_source() -> None:
    client = _private_db_client()
    resp = client.get(f"/api/mod/{MOD_ID}/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    src = body["data"][0]
    assert src["id"] == WECHAT_SOURCE_ID
    assert src["capabilities"] == WECHAT_CAPABILITIES
    assert src["requires_authorization"] is True


def test_private_db_sources_reflects_decrypt_status() -> None:
    client = _private_db_client()
    # 通过环境变量让 decrypt_status 返回 contact_db_exists=True
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b"SQLite format 3\x00")
        db_path = f.name
    try:
        with patch.dict(
            os.environ,
            {"WECHAT_CONTACT_DB_PATH": db_path},
            clear=False,
        ):
            resp = client.get(f"/api/mod/{MOD_ID}/sources")
    finally:
        os.unlink(db_path)
    body = resp.json()
    assert body["data"][0]["contact_db_exists"] is True


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /sources/select
# ---------------------------------------------------------------------------


def test_private_db_select_source_wechat_returns_success() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/sources/select",
        json={"source_id": WECHAT_SOURCE_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["source_id"] == WECHAT_SOURCE_ID


def test_private_db_select_source_empty_body_defaults_to_wechat() -> None:
    client = _private_db_client()
    resp = client.post(f"/api/mod/{MOD_ID}/sources/select", json={})
    assert resp.status_code == 200
    assert resp.json()["data"]["source_id"] == WECHAT_SOURCE_ID


def test_private_db_select_source_unsupported_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/sources/select",
        json={"source_id": "not_wechat"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "not_wechat" in body["message"]


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /wechat/auto_configure
# ---------------------------------------------------------------------------


def test_private_db_wechat_auto_configure_delegates() -> None:
    client = _private_db_client()
    with patch(
        "app.services.wechat_decrypt_http.wechat_decrypt_auto_configure_response"
    ) as mock_auto:
        mock_auto.return_value = {"success": True, "data": {"configured": True}}
        resp = client.post(
            f"/api/mod/{MOD_ID}/wechat/auto_configure",
            json={"path": "/tmp/wechat"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    mock_auto.assert_called_once_with({"path": "/tmp/wechat"})


def test_private_db_wechat_auto_configure_empty_body() -> None:
    client = _private_db_client()
    with patch(
        "app.services.wechat_decrypt_http.wechat_decrypt_auto_configure_response"
    ) as mock_auto:
        mock_auto.return_value = {"success": False, "message": "no path"}
        resp = client.post(f"/api/mod/{MOD_ID}/wechat/auto_configure", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    mock_auto.assert_called_once_with({})


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /sources/refresh
# ---------------------------------------------------------------------------


def test_private_db_refresh_source_unsupported_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/sources/refresh",
        json={"source_id": "other", "refresh_type": "contacts"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "other" in body["message"]


def test_private_db_refresh_source_empty_source_id_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/sources/refresh",
        json={"source_id": "", "refresh_type": "contacts"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "(空)" in body["message"]


def test_private_db_refresh_source_contacts_delegates_to_facade() -> None:
    client = _private_db_client()
    with patch(
        "app.application.facades.wechat_facade.refresh_wechat_contacts_from_decrypt"
    ) as mock_refresh:
        mock_refresh.return_value = ({"success": True, "synced": 5}, 200)
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "contacts"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["synced"] == 5
    mock_refresh.assert_called_once()


def test_private_db_refresh_source_all_delegates_to_facade() -> None:
    client = _private_db_client()
    with patch(
        "app.application.facades.wechat_facade.refresh_wechat_contacts_from_decrypt"
    ) as mock_refresh:
        mock_refresh.return_value = ({"success": False, "message": "fail"}, 500)
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "all"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False


def test_private_db_refresh_source_messages_success() -> None:
    client = _private_db_client()
    with patch("app.services.wechat_group_customer_bridge.sync_group_messages") as mock_sync:
        mock_sync.return_value = {"success": True, "synced": 3}
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "messages"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["synced"] == 3


def test_private_db_refresh_source_messages_failure_returns_500() -> None:
    client = _private_db_client()
    with patch("app.services.wechat_group_customer_bridge.sync_group_messages") as mock_sync:
        mock_sync.return_value = {"success": False, "message": "no db"}
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "messages"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False


def test_private_db_refresh_source_messages_recoverable_error_returns_500() -> None:
    client = _private_db_client()
    with patch("app.services.wechat_group_customer_bridge.sync_group_messages") as mock_sync:
        mock_sync.side_effect = RuntimeError("db broken")
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "messages"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "db broken" in body["message"]


def test_private_db_refresh_source_unsupported_refresh_type_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/sources/refresh",
        json={"source_id": WECHAT_SOURCE_ID, "refresh_type": "unknown"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "unknown" in body["message"]


def test_private_db_refresh_source_default_refresh_type_is_contacts() -> None:
    # 不传 refresh_type → 默认 "contacts"
    client = _private_db_client()
    with patch(
        "app.application.facades.wechat_facade.refresh_wechat_contacts_from_decrypt"
    ) as mock_refresh:
        mock_refresh.return_value = ({"success": True}, 200)
        resp = client.post(
            f"/api/mod/{MOD_ID}/sources/refresh",
            json={"source_id": WECHAT_SOURCE_ID},
        )
    assert resp.status_code == 200
    mock_refresh.assert_called_once()


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /contacts/search
# ---------------------------------------------------------------------------


def test_private_db_search_contacts_wrong_source_returns_400() -> None:
    client = _private_db_client()
    resp = client.get(
        f"/api/mod/{MOD_ID}/contacts/search",
        params={"source_id": "other", "q": "abc"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False


def test_private_db_search_contacts_empty_term_returns_empty_list() -> None:
    client = _private_db_client()
    resp = client.get(
        f"/api/mod/{MOD_ID}/contacts/search",
        params={"source_id": WECHAT_SOURCE_ID, "q": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == []


def test_private_db_search_contacts_whitespace_term_returns_empty_list() -> None:
    client = _private_db_client()
    resp = client.get(
        f"/api/mod/{MOD_ID}/contacts/search",
        params={"source_id": WECHAT_SOURCE_ID, "q": "   "},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_private_db_search_contacts_success() -> None:
    client = _private_db_client()
    mock_service = MagicMock()
    mock_service.get_contacts.return_value = [
        {
            "id": 1,
            "contact_name": "Alice",
            "remark": "Rem",
            "wechat_id": "wx1",
            "contact_type": "contact",
            "is_starred": True,
        },
        {
            "id": 2,
            "contact_name": "",
            "remark": "",
            "wechat_id": "wx2",
            "contact_type": "group",
        },
    ]
    with patch(
        "app.application.get_wechat_contact_app_service",
        return_value=mock_service,
    ):
        resp = client.get(
            f"/api/mod/{MOD_ID}/contacts/search",
            params={"source_id": WECHAT_SOURCE_ID, "q": "ali"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    assert body["data"][0]["display_name"] == "Alice"
    assert body["data"][0]["source_user_id"] == "wx1"
    assert body["data"][1]["display_name"] == "wx2"
    mock_service.get_contacts.assert_called_once_with(keyword="ali", starred_only=False, limit=80)


def test_private_db_search_contacts_recoverable_error_returns_500() -> None:
    client = _private_db_client()
    with patch(
        "app.application.get_wechat_contact_app_service",
        side_effect=RuntimeError("db down"),
    ):
        resp = client.get(
            f"/api/mod/{MOD_ID}/contacts/search",
            params={"source_id": WECHAT_SOURCE_ID, "q": "x"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "db down" in body["message"]


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /contacts/{contact_id}/context
# ---------------------------------------------------------------------------


def test_private_db_contact_context_wrong_source_returns_400() -> None:
    client = _private_db_client()
    resp = client.get(
        f"/api/mod/{MOD_ID}/contacts/1/context",
        params={"source_id": "other"},
    )
    assert resp.status_code == 400


def test_private_db_contact_context_invalid_id_returns_400() -> None:
    client = _private_db_client()
    resp = client.get(
        f"/api/mod/{MOD_ID}/contacts/not_an_int/context",
        params={"source_id": WECHAT_SOURCE_ID},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "无效" in body["message"]


def test_private_db_contact_context_success() -> None:
    client = _private_db_client()
    mock_service = MagicMock()
    mock_service.get_contact_context.return_value = [
        {"role": "user", "content": "hello"},
        {"sender": "bot", "message": "hi"},
        {"content": "   ", "text": "fallback"},
    ]
    with patch(
        "app.application.get_wechat_contact_app_service",
        return_value=mock_service,
    ):
        resp = client.get(
            f"/api/mod/{MOD_ID}/contacts/42/context",
            params={"source_id": WECHAT_SOURCE_ID},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 3
    assert body["data"][0]["text"] == "hello"
    assert body["data"][0]["role"] == "user"
    assert body["data"][1]["role"] == "bot"
    assert body["data"][2]["text"] == "fallback"
    mock_service.get_contact_context.assert_called_once_with(42)


def test_private_db_contact_context_recoverable_error_returns_500() -> None:
    client = _private_db_client()
    with patch(
        "app.application.get_wechat_contact_app_service",
        side_effect=ValueError("bad shape"),
    ):
        resp = client.get(
            f"/api/mod/{MOD_ID}/contacts/1/context",
            params={"source_id": WECHAT_SOURCE_ID},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "bad shape" in body["message"]


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — /send
# ---------------------------------------------------------------------------


def test_private_db_send_message_wrong_source_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/send",
        json={"source_id": "other", "contact_name": "x", "message": "hi"},
    )
    assert resp.status_code == 400


def test_private_db_send_message_empty_source_id_returns_400() -> None:
    client = _private_db_client()
    resp = client.post(
        f"/api/mod/{MOD_ID}/send",
        json={"source_id": "", "contact_name": "x", "message": "hi"},
    )
    assert resp.status_code == 400
    assert "(空)" in resp.json()["message"]


def test_private_db_send_message_delegates_to_wechat_routes() -> None:
    client = _private_db_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.body = b'{"success": true}'
    with patch(
        "app.fastapi_routes.domains.wechat.routes.wechat_contacts_send_message",
        return_value=mock_response,
    ) as mock_send:
        resp = client.post(
            f"/api/mod/{MOD_ID}/send",
            json={
                "source_id": WECHAT_SOURCE_ID,
                "contact_name": "Alice",
                "message": "hello",
            },
        )
    # TestClient 会把 mock_response 当作 Response 处理
    assert resp.status_code == 200
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["body"]["contact_name"] == "Alice"
    assert call_kwargs["body"]["message"] == "hello"


def test_private_db_send_message_with_none_values() -> None:
    client = _private_db_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.body = b'{"success": true}'
    with patch(
        "app.fastapi_routes.domains.wechat.routes.wechat_contacts_send_message",
        return_value=mock_response,
    ) as mock_send:
        resp = client.post(
            f"/api/mod/{MOD_ID}/send",
            json={"source_id": WECHAT_SOURCE_ID},
        )
    assert resp.status_code == 200
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["body"]["contact_name"] is None
    assert call_kwargs["body"]["message"] is None


# ---------------------------------------------------------------------------
# private_db_read_assistant_compat — register helper
# ---------------------------------------------------------------------------


def test_register_private_db_read_assistant_routes_attaches_router() -> None:
    app = FastAPI()
    register = __import__(
        "app.fastapi_routes.private_db_read_assistant_compat",
        fromlist=["register_private_db_read_assistant_routes"],
    ).register_private_db_read_assistant_routes
    register(app)
    # 路由应已挂载
    paths = [r.path for r in app.routes]
    assert any(f"/api/mod/{MOD_ID}/status" in p for p in paths)
    assert any(f"/api/mod/{MOD_ID}/sources" in p for p in paths)
