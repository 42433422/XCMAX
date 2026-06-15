"""COVERAGE_RAMP Phase 4 round 25: wechat DB fallback + refresh_messages + tools legacy."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import wechat_contact_service as mod
from app.services.tools_payload_legacy import dispatch_legacy_tool_payload
from app.services.wechat_contact_service import WechatContactService


def _j(data, status=200):
    return {"body": data, "status": status}


def _hdr(_k, default=""):
    return default


def _dispatch(tool_id, action, params=None):
    return dispatch_legacy_tool_payload(
        tool_id,
        action,
        params or {},
        json_response_fn=_j,
        hdr_getter=_hdr,
        parse_order_text_fn=lambda _t: {},
    )


@contextmanager
def _fake_db(session):
    yield session


def _patch_db(session):
    return patch.object(mod, "get_db", lambda: _fake_db(session))


def _fluent(*, all_=None, first=None, update_=0) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.all.return_value = list(all_ or [])
    q.first.return_value = first
    q.update.return_value = update_
    return q


def _contact(**kw) -> SimpleNamespace:
    base = {
        "id": 1,
        "contact_name": "张三",
        "remark": "朋友",
        "wechat_id": "zs001",
        "contact_type": "contact",
        "is_active": 1,
        "is_starred": 1,
        "created_at": datetime(2024, 1, 1),
        "updated_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def svc() -> WechatContactService:
    return WechatContactService()


# ---------------------------------------------------------------------------
# wechat_contact_service — DB 回退与异常
# ---------------------------------------------------------------------------


def test_search_contacts_from_wechat_db_empty_keyword(svc) -> None:
    assert svc._search_contacts_from_wechat_db("") == []
    assert svc._search_contacts_from_wechat_db("   ") == []


def test_search_contacts_from_wechat_db_via_contact_sqlite(svc, tmp_path) -> None:
    """contact.db 命中路径：临时 SQLite，不依赖真实微信解密库。"""
    decrypted = tmp_path / "decrypted" / "message"
    decrypted.mkdir(parents=True)
    msg_db = decrypted / "message_0.db"
    msg_db.write_bytes(b"x")  # 占位，优先走 contact.db

    contact_dir = tmp_path / "decrypted" / "contact"
    contact_dir.mkdir(parents=True)
    contact_db = contact_dir / "contact.db"
    with sqlite3.connect(contact_db) as conn:
        conn.execute(
            "CREATE TABLE contact (username TEXT, nick_name TEXT, remark TEXT, "
            "is_in_chat_room INTEGER, delete_flag INTEGER)"
        )
        conn.execute(
            "INSERT INTO contact VALUES (?, ?, ?, ?, ?)",
            ("wxid_demo", "七彩乐园", "备注", 0, 0),
        )
        conn.commit()

    with patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(msg_db)}, clear=False):
        out = svc._search_contacts_from_wechat_db("七彩", limit=5)
    assert len(out) == 1
    assert out[0]["contact_name"] == "七彩乐园"
    assert out[0]["wechat_id"] == "wxid_demo"


def test_search_contacts_from_wechat_db_message_rows_old_format(svc, tmp_path) -> None:
    """message 表旧版 talker/displayName 字段解析。"""
    db_path = tmp_path / "message_0.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE MSG (talker TEXT, displayName TEXT)")
        conn.execute("INSERT INTO MSG VALUES (?, ?)", ("wxid_abc", "李四"))
        conn.commit()

    plugin = MagicMock()
    plugin.is_available.return_value = True
    plugin.add_to_sys_path.return_value = None
    plugin.get_decrypted_db_path.return_value = None
    fake_wdr = MagicMock(get_recent_messages=MagicMock(return_value={"rows": []}))
    with (
        patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_path)}, clear=False),
        patch("app.infrastructure.plugins.wechat_plugin.get_wechat_plugin", return_value=plugin),
        patch("app.utils.path_utils.get_base_dir", return_value=str(tmp_path)),
        patch.dict("sys.modules", {"wechat_db_read": fake_wdr}),
    ):
        out = svc._search_contacts_from_wechat_db("李四", limit=3)
    assert len(out) == 1
    assert out[0]["contact_name"] == "李四"


def test_get_contacts_db_error_returns_empty(svc) -> None:
    with patch.object(mod, "get_db", side_effect=RuntimeError("db down")):
        assert svc.get_contacts() == []


def test_refresh_messages_contact_missing(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        out = svc.refresh_messages(99)
    assert out["success"] is False
    assert "不存在" in out["message"]


def test_refresh_messages_empty_wechat_id(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact(wechat_id="", contact_name=""))
    with _patch_db(s):
        out = svc.refresh_messages(1)
    assert out["success"] is False


def test_refresh_messages_no_db_file(svc, tmp_path) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    missing = str(tmp_path / "no_message.db")
    with (
        _patch_db(s),
        patch("app.utils.path_utils.get_resource_path", return_value=str(tmp_path / "missing")),
        patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": missing}, clear=False),
    ):
        out = svc.refresh_messages(1)
    assert out["success"] is False
    assert "数据库不存在" in out["message"]


def test_refresh_messages_success(svc, tmp_path) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    db_file = tmp_path / "message_0.db"
    db_file.write_bytes(b"")
    fake_read = MagicMock(
        return_value={"success": True, "rows": [{"role": "other", "text": "你好"}]}
    )
    with (
        _patch_db(s),
        patch.dict(os.environ, {"WECHAT_MSG_DB_PATH": str(db_file)}, clear=False),
        patch("app.utils.path_utils.get_resource_path", return_value=str(tmp_path)),
        patch.dict(
            "sys.modules",
            {
                "wechat_db_read": MagicMock(
                    get_messages_for_contact=fake_read,
                    get_wechat_contact_db_path=MagicMock(),
                )
            },
        ),
        patch.object(svc, "save_contact_context", return_value=True),
    ):
        out = svc.refresh_messages(1, limit=10)
    assert out["success"] is True
    assert out.get("count", 0) >= 0


def test_resolve_send_message_pattern_without_colon(svc) -> None:
    with patch.object(svc, "_find_best_matching_contact", return_value=None):
        assert svc.resolve_send_message("发给张三") == (None, None)


def test_find_best_matching_contact_fuzzy(svc) -> None:
    with patch.object(
        svc,
        "get_contacts",
        return_value=[{"contact_name": "七彩乐园有限公司"}],
    ):
        hit = svc._find_best_matching_contact("七彩乐园")
    assert hit == "七彩乐园有限公司"


# ---------------------------------------------------------------------------
# tools_payload_legacy — 剩余分支
# ---------------------------------------------------------------------------


def test_legacy_products_view_no_keyword() -> None:
    resp = _dispatch("products", "view", {})
    assert resp["body"]["redirect"] == "/console?view=products"


def test_legacy_products_default_message() -> None:
    resp = _dispatch("products", "other_action", {})
    assert resp["body"]["message"] == "产品管理"


def test_legacy_ocr_view() -> None:
    resp = _dispatch("ocr", "view", {})
    assert resp["body"]["redirect"] == "/console?view=ocr"


@patch("app.application.get_wechat_contact_app_service")
def test_legacy_wechat_list(mock_get: MagicMock) -> None:
    mock_get.return_value.get_contacts.return_value = [{"contact_name": "甲"}]
    resp = _dispatch("wechat", "list", {"type": "all"})
    assert resp["body"]["success"] is True
    assert resp["body"]["total"] == 1


def test_legacy_wechat_view_redirect() -> None:
    resp = _dispatch("wechat", "view", {})
    assert "wechat-contacts" in resp["body"]["redirect"]


def test_legacy_upload_file_redirect() -> None:
    resp = _dispatch("upload_file", "view", {})
    assert resp["body"]["success"] is True


@patch("app.services.get_system_service")
def test_legacy_system_get_info(mock_get: MagicMock) -> None:
    mock_get.return_value.get_system_info.return_value = {"os": "test"}
    resp = _dispatch("system", "get_system_info", {})
    assert resp["body"]["success"] is True
    assert resp["body"]["data"]["os"] == "test"


def test_legacy_tools_table_list() -> None:
    resp = _dispatch("tools_table", "list", {})
    assert resp["body"]["success"] is True


def test_legacy_settings_view() -> None:
    resp = _dispatch("settings", "view", {})
    assert "settings" in resp["body"]["redirect"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
