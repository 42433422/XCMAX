"""COVERAGE_RAMP Phase 4 round 23: wechat_contact_service CRUD + resolve (32%→)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import wechat_contact_service as mod
from app.services.wechat_contact_service import WechatContactService


def _fluent(*, all_=None, first=None, update_=0) -> MagicMock:
    q = MagicMock()
    for attr in ("filter", "filter_by", "order_by", "join", "offset", "limit", "group_by"):
        getattr(q, attr).return_value = q
    q.all.return_value = list(all_ or [])
    q.first.return_value = first
    q.update.return_value = update_
    return q


@contextmanager
def _fake_db(session):
    yield session


def _patch_db(session):
    return patch.object(mod, "get_db", lambda: _fake_db(session))


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
# get_contacts
# ---------------------------------------------------------------------------


def test_get_contacts_keyword_with_results(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(all_=[_contact()])
    with _patch_db(s):
        out = svc.get_contacts(keyword="张")
    assert out[0]["contact_name"] == "张三"


def test_get_contacts_type_all(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(all_=[_contact()])
    with _patch_db(s):
        out = svc.get_contacts(contact_type="all", starred_only=True)
    assert len(out) == 1


def test_get_contacts_type_specific(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(all_=[_contact(contact_type="group")])
    with _patch_db(s):
        out = svc.get_contacts(contact_type="group")
    assert out[0]["contact_type"] == "group"


def test_get_contacts_keyword_fallback(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(all_=[])
    extra = [{"id": 99, "contact_name": "挖到的"}]
    with _patch_db(s), patch.object(svc, "_search_contacts_from_wechat_db", return_value=extra):
        out = svc.get_contacts(keyword="找不到")
    assert out == extra


# ---------------------------------------------------------------------------
# get_contact_by_id
# ---------------------------------------------------------------------------


def test_get_contact_by_id_found(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    with _patch_db(s):
        out = svc.get_contact_by_id(1)
    assert out["id"] == 1


def test_get_contact_by_id_missing(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        assert svc.get_contact_by_id(9) is None


# ---------------------------------------------------------------------------
# add_contact
# ---------------------------------------------------------------------------


def test_add_contact_empty_name(svc) -> None:
    out = svc.add_contact("   ")
    assert out["success"] is False


def test_add_contact_placeholder_name_uses_wechat_id(svc) -> None:
    s = MagicMock()
    with _patch_db(s):
        out = svc.add_contact("%", wechat_id="wxid_123")
    assert out["success"] is True
    s.add.assert_called_once()


def test_add_contact_success(svc) -> None:
    s = MagicMock()
    with _patch_db(s):
        out = svc.add_contact("李四", remark="同事")
    assert out["success"] is True


# ---------------------------------------------------------------------------
# update / delete / star
# ---------------------------------------------------------------------------


def test_update_contact_not_found(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        assert svc.update_contact(1, contact_name="x")["success"] is False


def test_update_contact_success_all_fields(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    with _patch_db(s):
        out = svc.update_contact(
            1,
            contact_name="新名",
            remark="新备注",
            wechat_id="newid",
            contact_type="invalid_type",
            is_starred=False,
        )
    assert out["success"] is True


def test_update_contact_empty_name(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    with _patch_db(s):
        out = svc.update_contact(1, contact_name="   ")
    assert out["success"] is False


def test_delete_contact(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    with _patch_db(s):
        assert svc.delete_contact(1)["success"] is True
    s2 = MagicMock()
    s2.query.return_value = _fluent(first=None)
    with _patch_db(s2):
        assert svc.delete_contact(9)["success"] is False


def test_star_contact_delegates(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=_contact())
    with _patch_db(s):
        assert svc.star_contact(1, starred=True)["success"] is True


def test_unstar_all(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(update_=3)
    with _patch_db(s):
        out = svc.unstar_all()
    assert out["success"] is True
    assert out["count"] == 3


# ---------------------------------------------------------------------------
# contact context
# ---------------------------------------------------------------------------


def test_get_contact_context_empty(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        assert svc.get_contact_context(1) == []


def test_get_contact_context_parsed(svc) -> None:
    ctx = SimpleNamespace(context_json=json.dumps([{"m": "hi"}]))
    s = MagicMock()
    s.query.return_value = _fluent(first=ctx)
    with _patch_db(s):
        out = svc.get_contact_context(1)
    assert out == [{"m": "hi"}]


def test_get_contact_context_invalid_json(svc) -> None:
    ctx = SimpleNamespace(context_json="{not json")
    s = MagicMock()
    s.query.return_value = _fluent(first=ctx)
    with _patch_db(s):
        assert svc.get_contact_context(1) == []


def test_save_contact_context_update_existing(svc) -> None:
    ctx = SimpleNamespace(
        wechat_id="", context_json="", message_count=0, updated_at=None
    )
    s = MagicMock()
    s.query.return_value = _fluent(first=ctx)
    with _patch_db(s):
        assert svc.save_contact_context(1, "wx", [{"m": "a"}]) is True
    assert ctx.message_count == 1


def test_save_contact_context_insert_new(svc) -> None:
    s = MagicMock()
    s.query.return_value = _fluent(first=None)
    with _patch_db(s):
        assert svc.save_contact_context(1, "wx", [{"m": "a"}]) is True
    s.add.assert_called_once()


# ---------------------------------------------------------------------------
# resolve_send_message + matching
# ---------------------------------------------------------------------------


def test_resolve_send_message_too_short(svc) -> None:
    assert svc.resolve_send_message("hi") == (None, None)


def test_resolve_send_message_match(svc) -> None:
    with patch.object(svc, "_find_best_matching_contact", return_value="张三"):
        contact, content = svc.resolve_send_message("给张三发送你好呀")
    assert contact == "张三"
    assert content == "你好呀"


def test_resolve_send_message_no_match(svc) -> None:
    with patch.object(svc, "_find_best_matching_contact", return_value=None):
        assert svc.resolve_send_message("给某人发送内容啊") == (None, None)


def test_find_best_matching_contact(svc) -> None:
    with patch.object(svc, "get_contacts", return_value=[{"contact_name": "张三"}]):
        assert svc._find_best_matching_contact("张三") == "张三"
    with patch.object(svc, "get_contacts", return_value=[]):
        assert svc._find_best_matching_contact("无人") is None


def test_get_service_singleton() -> None:
    assert mod.get_wechat_contact_service() is mod.get_wechat_contact_service()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
