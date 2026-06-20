"""COVERAGE_RAMP Phase 6 round 11: backend low-coverage modules.

Targets:
- ``app/enterprise/mod_entitlements.py`` (71.5% line coverage, 75 uncovered lines)
- ``app/fastapi_routes/mods_routes.py`` (49.3% line coverage, 72 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / mod manager / market proxy). The handler functions themselves are
exercised through real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, etc.)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.enterprise import mod_entitlements
from app.enterprise.mod_entitlements import (
    _parse_mod_ids_from_market_payload,
    clear_session_entitlements,
    enterprise_mod_filter_active,
    fetch_entitled_client_mod_ids_for_market_user,
    fetch_entitled_client_mod_ids_from_market,
    filter_mod_id_list_for_enterprise,
    filter_mod_rows_for_enterprise,
    get_cached_entitled_client_mod_ids,
    get_cached_market_identity,
    host_mod_ids_for_enterprise,
    is_admin_account_session,
    is_client_mod_id,
    is_mod_visible_for_enterprise,
    persist_entitlements_to_session_row,
    refresh_session_entitlements_from_market,
    reload_enterprise_mods_after_login,
    restore_entitlements_from_session_row,
    set_session_entitlements,
    sync_entitlements_for_session,
    sync_entitlements_from_request,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_entitlements_cache() -> None:
    """每个测试前后清空进程内权益缓存，避免相互污染。"""
    clear_session_entitlements()
    yield
    clear_session_entitlements()


@pytest.fixture
def enterprise_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 enterprise_mod_filter_active() 返回 True。"""
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )


@pytest.fixture
def enterprise_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 enterprise_mod_filter_active() 返回 False。"""
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )


# ---------------------------------------------------------------------------
# is_client_mod_id / host_mod_ids_for_enterprise / enterprise_mod_filter_active
# ---------------------------------------------------------------------------


def test_is_client_mod_id_truthy_for_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.PROTECTED_CLIENT_MOD_IDS",
        ("taiyangniao-pro", "sz-qsm-pro"),
    )
    assert is_client_mod_id("taiyangniao-pro") is True
    assert is_client_mod_id("  sz-qsm-pro  ") is True


def test_is_client_mod_id_falsy_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.PROTECTED_CLIENT_MOD_IDS",
        ("taiyangniao-pro",),
    )
    assert is_client_mod_id("other-mod") is False


def test_is_client_mod_id_none_or_empty_returns_false() -> None:
    assert is_client_mod_id("") is False
    assert is_client_mod_id(None) is False  # type: ignore[arg-type]
    assert is_client_mod_id("   ") is False


def test_host_mod_ids_for_enterprise_returns_frozenset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.bundled_mod_ids_for_sku",
        lambda sku: ("m1", "m2"),
    )
    out = host_mod_ids_for_enterprise()
    assert isinstance(out, frozenset)
    assert out == frozenset({"m1", "m2"})


def test_enterprise_mod_filter_active_uses_resolve_product_sku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.resolve_product_sku",
        lambda: "enterprise",
    )
    assert enterprise_mod_filter_active() is True

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.resolve_product_sku",
        lambda: "personal",
    )
    assert enterprise_mod_filter_active() is False

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.resolve_product_sku",
        lambda: None,
    )
    assert enterprise_mod_filter_active() is False


# ---------------------------------------------------------------------------
# get_cached_entitled_client_mod_ids / get_cached_market_identity
# ---------------------------------------------------------------------------


def test_get_cached_entitled_client_mod_ids_inactive(enterprise_inactive: None) -> None:
    assert get_cached_entitled_client_mod_ids() is None


def test_get_cached_entitled_client_mod_ids_active_empty(enterprise_active: None) -> None:
    # 未 set → 返回空 set（非 None）
    out = get_cached_entitled_client_mod_ids()
    assert out is not None
    assert out == set()


def test_get_cached_entitled_client_mod_ids_active_with_cache(
    enterprise_active: None,
) -> None:
    set_session_entitlements(
        market_user_id=1,
        market_username="u",
        entitled_client_mod_ids={"taiyangniao-pro"},
    )
    assert get_cached_entitled_client_mod_ids() == {"taiyangniao-pro"}


def test_get_cached_market_identity_default() -> None:
    assert get_cached_market_identity() == (None, "")


def test_get_cached_market_identity_after_set() -> None:
    set_session_entitlements(
        market_user_id=42,
        market_username="alice",
        entitled_client_mod_ids=set(),
    )
    assert get_cached_market_identity() == (42, "alice")


# ---------------------------------------------------------------------------
# set_session_entitlements / clear_session_entitlements / is_admin_account_session
# ---------------------------------------------------------------------------


def test_set_session_entitlements_strips_username_and_normalizes_account_kind() -> None:
    set_session_entitlements(
        market_user_id=7,
        market_username="  Bob  ",
        entitled_client_mod_ids={"a", "b"},
        account_kind="  ",
        market_is_admin=1,  # truthy non-bool
    )
    uid, uname = get_cached_market_identity()
    assert uid == 7
    assert uname == "Bob"
    # 空 account_kind 应回退到 enterprise
    assert is_admin_account_session() is False


def test_set_session_entitlements_admin_account_session() -> None:
    set_session_entitlements(
        market_user_id=1,
        market_username="admin",
        entitled_client_mod_ids=set(),
        account_kind="admin",
        market_is_admin=True,
    )
    assert is_admin_account_session() is True


def test_set_session_entitlements_admin_kind_but_not_admin_flag() -> None:
    set_session_entitlements(
        market_user_id=1,
        market_username="admin",
        entitled_client_mod_ids=set(),
        account_kind="admin",
        market_is_admin=False,
    )
    assert is_admin_account_session() is False


def test_clear_session_entitlements_resets_all() -> None:
    set_session_entitlements(
        market_user_id=99,
        market_username="zoe",
        entitled_client_mod_ids={"x"},
        account_kind="admin",
        market_is_admin=True,
    )
    clear_session_entitlements()
    assert get_cached_market_identity() == (None, "")
    assert get_cached_entitled_client_mod_ids() is None
    assert is_admin_account_session() is False


# ---------------------------------------------------------------------------
# is_mod_visible_for_enterprise
# ---------------------------------------------------------------------------


def test_is_mod_visible_empty_mod_id_returns_false(enterprise_active: None) -> None:
    assert is_mod_visible_for_enterprise("") is False
    assert is_mod_visible_for_enterprise("   ") is False


def test_is_mod_visible_inactive_returns_true(enterprise_inactive: None) -> None:
    assert is_mod_visible_for_enterprise("any-mod") is True


def test_is_mod_visible_non_client_mod_returns_true(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: False,
    )
    assert is_mod_visible_for_enterprise("host-mod-1") is True


def test_is_mod_visible_admin_session_bypass(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    set_session_entitlements(
        market_user_id=1,
        market_username="admin",
        entitled_client_mod_ids=set(),
        account_kind="admin",
        market_is_admin=True,
    )
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is True


def test_is_mod_visible_sunbird_local_username(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "taiyangniao-pro",
    )
    # 让 client_primary_mod_on_disk_visible 返回 False
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.client_primary_mod_on_disk_visible",
        lambda mid: False,
    )
    set_session_entitlements(
        market_user_id=1,
        market_username="sunbird",
        entitled_client_mod_ids=set(),
    )
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is True


def test_is_mod_visible_client_primary_mod_on_disk_visible(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.client_primary_mod_on_disk_visible",
        lambda mid: True,
    )
    set_session_entitlements(
        market_user_id=1,
        market_username="other",
        entitled_client_mod_ids=set(),
    )
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is True


def test_is_mod_visible_client_primary_mod_on_disk_visible_raises_recoverable(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )

    def _raise(mid: str) -> bool:
        raise RuntimeError("disk check boom")

    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.client_primary_mod_on_disk_visible",
        _raise,
    )
    set_session_entitlements(
        market_user_id=1,
        market_username="other",
        entitled_client_mod_ids={"taiyangniao-pro"},
    )
    # 异常被吞 → 走 entitled 集合判断
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is True


def test_is_mod_visible_entitled_is_none_returns_false(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.client_primary_mod_on_disk_visible",
        lambda mid: False,
    )
    # 不 set → _cached_entitled_client_mod_ids 为 None
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is False


def test_is_mod_visible_in_entitled_set(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    monkeypatch.setattr(
        "app.mod_sdk.client_primary_erp.client_primary_mod_on_disk_visible",
        lambda mid: False,
    )
    set_session_entitlements(
        market_user_id=1,
        market_username="other",
        entitled_client_mod_ids={"sz-qsm-pro"},
    )
    assert is_mod_visible_for_enterprise("sz-qsm-pro") is True
    assert is_mod_visible_for_enterprise("taiyangniao-pro") is False


# ---------------------------------------------------------------------------
# filter_mod_rows_for_enterprise / filter_mod_id_list_for_enterprise
# ---------------------------------------------------------------------------


def test_filter_mod_rows_inactive_returns_original(enterprise_inactive: None) -> None:
    rows = [{"id": "a"}, {"id": "b"}]
    assert filter_mod_rows_for_enterprise(rows) is rows


def test_filter_mod_rows_active_filters(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mid: mid in {"a", "c"},
    )
    rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": ""}, {"name": "no-id"}]
    out = filter_mod_rows_for_enterprise(rows)
    assert [r["id"] for r in out] == ["a", "c"]


def test_filter_mod_id_list_inactive_returns_original(enterprise_inactive: None) -> None:
    ids = ["a", "b"]
    assert filter_mod_id_list_for_enterprise(ids) is ids


def test_filter_mod_id_list_active_filters(
    enterprise_active: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mid: mid == "keep",
    )
    out = filter_mod_id_list_for_enterprise(["keep", "drop", ""])
    assert out == ["keep"]


# ---------------------------------------------------------------------------
# _parse_mod_ids_from_market_payload
# ---------------------------------------------------------------------------


def test_parse_mod_ids_non_dict_returns_empty() -> None:
    assert _parse_mod_ids_from_market_payload(None) == set()
    assert _parse_mod_ids_from_market_payload("string") == set()
    assert _parse_mod_ids_from_market_payload([1, 2]) == set()


def test_parse_mod_ids_mod_ids_list_with_client_mods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid in {"taiyangniao-pro", "sz-qsm-pro"},
    )
    payload = {"mod_ids": ["taiyangniao-pro", "sz-qsm-pro", "other", "", "  "]}
    out = _parse_mod_ids_from_market_payload(payload)
    assert out == {"taiyangniao-pro", "sz-qsm-pro"}


def test_parse_mod_ids_mod_ids_list_empty_falls_to_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    payload = {
        "mod_ids": [],  # 空列表 → 不 return，继续解析 data
        "data": [{"id": "a"}, {"id": "b"}, {"id": ""}, "not-dict"],
    }
    out = _parse_mod_ids_from_market_payload(payload)
    assert out == {"a", "b"}


def test_parse_mod_ids_data_dict_with_mods_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    payload = {"data": {"mods": [{"id": "x"}, {"id": "y"}]}}
    out = _parse_mod_ids_from_market_payload(payload)
    assert out == {"x", "y"}


def test_parse_mod_ids_data_other_shape_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    payload = {"data": "not-list-not-dict"}
    assert _parse_mod_ids_from_market_payload(payload) == set()


def test_parse_mod_ids_rows_with_non_dict_items_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: True,
    )
    payload = {"data": ["str-item", {"id": "ok"}, 123, {"id": ""}]}
    out = _parse_mod_ids_from_market_payload(payload)
    assert out == {"ok"}


# ---------------------------------------------------------------------------
# fetch_entitled_client_mod_ids_from_market
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_entitled_empty_token_returns_empty() -> None:
    assert await fetch_entitled_client_mod_ids_from_market("") == set()
    assert await fetch_entitled_client_mod_ids_from_market("   ") == set()


@pytest.mark.asyncio
async def test_fetch_entitled_proxy_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_proxy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"__proxy_error__": True, "message": "down"}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    out = await fetch_entitled_client_mod_ids_from_market("tok")
    assert out == set()


@pytest.mark.asyncio
async def test_fetch_entitled_dict_with_mod_ids_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy(
        method: str,
        path: str,
        *,
        authorization: str = "",
        return_error_payload: bool = False,
    ) -> dict[str, Any]:
        captured["method"] = method
        captured["path"] = path
        captured["authorization"] = authorization
        return {"mod_ids": ["taiyangniao-pro", "other", ""]}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "taiyangniao-pro",
    )
    out = await fetch_entitled_client_mod_ids_from_market("tok")
    assert out == {"taiyangniao-pro"}
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/enterprise/entitled-mod-ids"
    # 应自动补 Bearer 前缀
    assert captured["authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_fetch_entitled_bearer_prefix_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy(
        method: str,
        path: str,
        *,
        authorization: str = "",
        return_error_payload: bool = False,
    ) -> dict[str, Any]:
        captured["authorization"] = authorization
        return {"data": {"mod_ids": ["sz-qsm-pro"]}}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "sz-qsm-pro",
    )
    out = await fetch_entitled_client_mod_ids_from_market("Bearer abc")
    assert out == {"sz-qsm-pro"}
    assert captured["authorization"] == "Bearer abc"


@pytest.mark.asyncio
async def test_fetch_entitled_dict_with_data_mod_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_proxy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"data": {"mod_ids": ["taiyangniao-pro"]}}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "taiyangniao-pro",
    )
    out = await fetch_entitled_client_mod_ids_from_market("tok")
    assert out == {"taiyangniao-pro"}


@pytest.mark.asyncio
async def test_fetch_entitled_falls_back_to_parse_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_proxy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # 既无 mod_ids 也无 data.mod_ids → 走 _parse_mod_ids_from_market_payload
        # data 必须是 dict（含 mods 键）才能进入 fallback；list 会触发 AttributeError
        return {"data": {"mods": [{"id": "taiyangniao-pro"}, {"id": "other"}]}}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "taiyangniao-pro",
    )
    out = await fetch_entitled_client_mod_ids_from_market("tok")
    # fallback 路径（_parse_mod_ids_from_market_payload）不过滤 is_client_mod_id，
    # 收集所有 id
    assert out == {"taiyangniao-pro", "other"}


@pytest.mark.asyncio
async def test_fetch_entitled_non_dict_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_proxy(*args: Any, **kwargs: Any) -> Any:
        return ["not", "a", "dict"]

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    out = await fetch_entitled_client_mod_ids_from_market("tok")
    assert out == set()


# ---------------------------------------------------------------------------
# fetch_entitled_client_mod_ids_for_market_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_for_market_user_empty_token_returns_empty() -> None:
    assert await fetch_entitled_client_mod_ids_for_market_user("", 1) == set()


@pytest.mark.asyncio
async def test_fetch_for_market_user_proxy_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_proxy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"__proxy_error__": True}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    out = await fetch_entitled_client_mod_ids_for_market_user("tok", 42)
    assert out == set()


@pytest.mark.asyncio
async def test_fetch_for_market_user_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy(
        method: str,
        path: str,
        *,
        authorization: str = "",
        return_error_payload: bool = False,
    ) -> dict[str, Any]:
        captured["method"] = method
        captured["path"] = path
        captured["authorization"] = authorization
        return {"mod_ids": ["taiyangniao-pro"]}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account._proxy_json",
        _fake_proxy,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_client_mod_id",
        lambda mid: mid == "taiyangniao-pro",
    )
    out = await fetch_entitled_client_mod_ids_for_market_user("tok", 42)
    assert out == {"taiyangniao-pro"}
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/admin/users/42/mods"
    assert captured["authorization"] == "Bearer tok"


# ---------------------------------------------------------------------------
# refresh_session_entitlements_from_market
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_session_admin_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch_user(token: str, target_uid: int) -> set[str]:
        assert target_uid == 99
        return {"taiyangniao-pro"}

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.fetch_entitled_client_mod_ids_for_market_user",
        _fake_fetch_user,
    )

    def _fake_load_meta(sid: str) -> dict[str, Any]:
        return {
            "account_kind": "admin",
            "market_is_admin": True,
            "impersonating_market_user_id": 99,
        }

    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        _fake_load_meta,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await refresh_session_entitlements_from_market(
        market_token="tok",
        market_user_id=1,
        market_username="admin",
        session_id="sid-1",
    )
    assert out == {"taiyangniao-pro"}
    assert is_admin_account_session() is True


@pytest.mark.asyncio
async def test_refresh_session_admin_no_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.PROTECTED_CLIENT_MOD_IDS",
        ("taiyangniao-pro", "sz-qsm-pro"),
    )

    def _fake_load_meta(sid: str) -> dict[str, Any]:
        return {"account_kind": "admin", "market_is_admin": True}

    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        _fake_load_meta,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await refresh_session_entitlements_from_market(
        market_token="tok",
        market_user_id=1,
        market_username="admin",
        session_id="sid-1",
    )
    assert out == {"taiyangniao-pro", "sz-qsm-pro"}


@pytest.mark.asyncio
async def test_refresh_session_enterprise_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch(token: str) -> set[str]:
        return {"sz-qsm-pro"}

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.fetch_entitled_client_mod_ids_from_market",
        _fake_fetch,
    )

    def _fake_load_meta(sid: str) -> dict[str, Any]:
        return {"account_kind": "enterprise", "market_is_admin": False}

    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        _fake_load_meta,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await refresh_session_entitlements_from_market(
        market_token="tok",
        market_user_id=5,
        market_username="alice",
        session_id="sid-2",
    )
    assert out == {"sz-qsm-pro"}
    assert is_admin_account_session() is False


@pytest.mark.asyncio
async def test_refresh_session_meta_load_raises_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch(token: str) -> set[str]:
        return {"taiyangniao-pro"}

    def _raise(sid: str) -> dict[str, Any]:
        raise RuntimeError("meta load boom")

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.fetch_entitled_client_mod_ids_from_market",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        _raise,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await refresh_session_entitlements_from_market(
        market_token="tok",
        market_user_id=1,
        market_username="u",
        session_id="sid-3",
    )
    # meta 加载失败 → 走 enterprise 分支
    assert out == {"taiyangniao-pro"}


@pytest.mark.asyncio
async def test_refresh_session_empty_session_id_skips_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch(token: str) -> set[str]:
        return {"taiyangniao-pro"}

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.fetch_entitled_client_mod_ids_from_market",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await refresh_session_entitlements_from_market(
        market_token="tok",
        market_user_id=1,
        market_username="u",
        session_id="",
    )
    assert out == {"taiyangniao-pro"}


# ---------------------------------------------------------------------------
# persist_entitlements_to_session_row / restore_entitlements_from_session_row
# ---------------------------------------------------------------------------


def test_persist_empty_session_id_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    # 不应触发任何 DB 调用
    called = {"n": 0}

    def _fail(*args: Any, **kwargs: Any) -> None:
        called["n"] += 1
        raise AssertionError("should not be called")

    monkeypatch.setattr("app.db.session.get_db", _fail)
    persist_entitlements_to_session_row("", {"a"})
    assert called["n"] == 0


def test_persist_no_session_row_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_db

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    persist_entitlements_to_session_row("sid", {"a"})
    mock_db.query.return_value.filter.return_value.first.assert_called_once()
    mock_db.commit.assert_not_called()


def test_persist_writes_row(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_row = MagicMock()
    mock_row.market_user_id = None
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_row

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_db

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    set_session_entitlements(
        market_user_id=10,
        market_username="u",
        entitled_client_mod_ids={"a", "b"},
    )
    persist_entitlements_to_session_row("sid", {"a", "b"})
    assert mock_row.market_user_id == 10
    assert json.loads(mock_row.entitled_mod_ids_json) == ["a", "b"]
    mock_db.commit.assert_called_once()


def test_persist_recoverable_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.session.get_db", _fail)
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    # 不应抛出
    persist_entitlements_to_session_row("sid", {"a"})


def test_restore_empty_session_id_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    assert restore_entitlements_from_session_row("") is False


def test_restore_inactive_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )
    assert restore_entitlements_from_session_row("sid") is False


def test_restore_no_row_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_db

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    assert restore_entitlements_from_session_row("sid") is False


def test_restore_row_found_sets_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    mock_row = MagicMock()
    mock_row.market_user_id = 7
    mock_row.entitled_mod_ids_json = '["a", "b"]'
    mock_row.account_kind = "enterprise"
    mock_row.market_is_admin = False
    mock_row.impersonating_username = "alice"
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_row

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_db

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    assert restore_entitlements_from_session_row("sid") is True
    uid, uname = get_cached_market_identity()
    assert uid == 7
    assert uname == "alice"
    assert get_cached_entitled_client_mod_ids() == {"a", "b"}


def test_restore_recoverable_error_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )

    def _fail() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr("app.db.session.get_db", _fail)
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    assert restore_entitlements_from_session_row("sid") is False


def test_restore_invalid_json_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    mock_row = MagicMock()
    mock_row.market_user_id = 7
    mock_row.entitled_mod_ids_json = "not-json"
    mock_row.account_kind = "enterprise"
    mock_row.market_is_admin = False
    mock_row.impersonating_username = ""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_row

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_db

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.db.session.get_db", lambda: _Ctx())
    monkeypatch.setattr("app.db.models.user.Session", MagicMock())
    # json.JSONDecodeError 属于 RECOVERABLE_ERRORS → 返回 False
    assert restore_entitlements_from_session_row("sid") is False


# ---------------------------------------------------------------------------
# sync_entitlements_for_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_inactive_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )
    out = await sync_entitlements_for_session("sid")
    assert out == set()


@pytest.mark.asyncio
async def test_sync_empty_session_id_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    out = await sync_entitlements_for_session("")
    assert out == set()


@pytest.mark.asyncio
async def test_sync_with_token_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )

    async def _resolve(sid: str) -> str:
        return "tok"

    async def _refresh(
        *,
        market_token: str,
        market_user_id: int | None = None,
        market_username: str = "",
        session_id: str = "",
    ) -> set[str]:
        return {"taiyangniao-pro"}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        _resolve,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.refresh_session_entitlements_from_market",
        _refresh,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._session_username_for_entitlements",
        lambda sid: "alice",
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.persist_entitlements_to_session_row",
        lambda sid, ids: None,
    )

    reloaded = {"called": False}

    async def _reload() -> None:
        reloaded["called"] = True

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
        _reload,
    )
    out = await sync_entitlements_for_session("sid")
    assert out == {"taiyangniao-pro"}
    assert reloaded["called"] is True


@pytest.mark.asyncio
async def test_sync_no_token_falls_back_to_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )

    async def _resolve(sid: str) -> str:
        return ""

    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        _resolve,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._session_username_for_entitlements",
        lambda sid: "alice",
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.restore_entitlements_from_session_row",
        lambda sid: True,
    )
    # 预设缓存（restore 会写入）
    set_session_entitlements(
        market_user_id=1,
        market_username="alice",
        entitled_client_mod_ids={"cached-mod"},
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await sync_entitlements_for_session("sid")
    assert out == {"cached-mod"}


@pytest.mark.asyncio
async def test_sync_resolve_raises_recoverable_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )

    async def _resolve(sid: str) -> str:
        raise RuntimeError("market down")

    monkeypatch.setattr(
        "app.fastapi_routes.market_account.resolve_valid_market_access_token",
        _resolve,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._session_username_for_entitlements",
        lambda sid: "alice",
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.restore_entitlements_from_session_row",
        lambda sid: False,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements._augment_entitled_for_username",
        lambda u, s: s or set(),
    )
    out = await sync_entitlements_for_session("sid")
    assert out == set()


# ---------------------------------------------------------------------------
# reload_enterprise_mods_after_login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_inactive_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )
    # 不应触发任何 import
    await reload_enterprise_mods_after_login()


@pytest.mark.asyncio
async def test_reload_active_loads_mods(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    mock_mm = MagicMock()
    mock_mm.load_all_mods.return_value = ["taiyangniao-pro"]
    mock_app = MagicMock()

    def _ensure(mod_id: str, session_id: str | None = None) -> bool:
        return True

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: mock_mm,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.load_mod_routes",
        lambda app, mm: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
        _ensure,
    )
    monkeypatch.setattr(
        "app.fastapi_app.get_fastapi_app",
        lambda: mock_app,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mid: True,
    )
    await reload_enterprise_mods_after_login()
    mock_mm.load_all_mods.assert_called_once()


@pytest.mark.asyncio
async def test_reload_recoverable_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )

    def _fail() -> None:
        raise RuntimeError("mod manager boom")

    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        _fail,
    )
    # 不应抛出
    await reload_enterprise_mods_after_login()


# ---------------------------------------------------------------------------
# sync_entitlements_from_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_from_request_inactive_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )
    request = MagicMock()
    await sync_entitlements_from_request(request)


@pytest.mark.asyncio
async def test_sync_from_request_with_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)
    request = MagicMock()
    request.cookies.get.return_value = "  sid-from-cookie  "

    called = {"sid": ""}

    async def _sync(sid: str) -> set[str]:
        called["sid"] = sid
        return {"x"}

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session",
        _sync,
    )
    await sync_entitlements_from_request(request)
    assert called["sid"] == "sid-from-cookie"


@pytest.mark.asyncio
async def test_sync_from_request_no_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)
    request = MagicMock()
    request.cookies.get.return_value = ""

    called = {"n": 0}

    async def _sync(sid: str) -> set[str]:
        called["n"] += 1
        return set()

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session",
        _sync,
    )
    await sync_entitlements_from_request(request)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_sync_from_request_recoverable_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.delenv("SESSION_COOKIE_NAME", raising=False)
    request = MagicMock()
    request.cookies.get.side_effect = RuntimeError("cookie boom")
    # 不应抛出
    await sync_entitlements_from_request(request)


# ---------------------------------------------------------------------------
# mods_routes — FastAPI router tests
# ---------------------------------------------------------------------------


def _build_mods_app() -> FastAPI:
    """构造一个仅挂载 mods_routes 的 FastAPI 子应用，隔离测试。"""
    from app.fastapi_routes import mods_routes

    # 重置模块级 router 单例，确保每次都重新注册
    mods_routes.router = None
    app = FastAPI()
    app.include_router(mods_routes.get_mods_router())
    return app


def test_get_mods_router_singleton() -> None:
    from app.fastapi_routes import mods_routes

    mods_routes.router = None
    r1 = mods_routes.get_mods_router()
    r2 = mods_routes.get_mods_router()
    assert r1 is r2


def test_loading_status_mods_disabled() -> None:
    app = _build_mods_app()
    with patch(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        return_value=True,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["mods_disabled"] is True
    assert body["data"]["discovered_mod_ids"] == []
    assert body["data"]["mods_loaded"] == 0


def test_loading_status_happy_path() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm._refresh_mods_root_if_needed.return_value = None
    mock_mm.scan_mods.return_value = []
    mock_mm.list_loaded_mods.return_value = []
    mock_mm._scan_manifest_errors = []
    mock_mm._blueprint_failures = []
    mock_mm._recent_load_failures = []
    mock_mm.mods_root = "/tmp/mods"
    mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
            side_effect=lambda ids: ids,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["mods_disabled"] is False
    assert body["data"]["discovered_mod_ids"] == []
    assert body["data"]["partial_failure"] is False


def test_loading_status_with_primary_mod() -> None:
    app = _build_mods_app()
    mod_a = MagicMock()
    mod_a.id = "mod-a"
    mod_a.primary = True
    mod_b = MagicMock()
    mod_b.id = "mod-b"
    mod_b.primary = False
    mock_mm = MagicMock()
    mock_mm._refresh_mods_root_if_needed.return_value = None
    mock_mm.scan_mods.return_value = [mod_a, mod_b]
    mock_mm.list_loaded_mods.return_value = ["mod-a", "mod-b"]
    mock_mm._scan_manifest_errors = []
    mock_mm._blueprint_failures = []
    mock_mm._recent_load_failures = []
    mock_mm.mods_root = "/tmp/mods"
    mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
            side_effect=lambda ids: ids,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    body = resp.json()
    # 单个 primary_mod → primary_mod_id 为该 mod id
    assert body["data"]["primary_mod_id"] == "mod-a"
    assert body["data"]["primary_mod_count"] == 1
    assert body["data"]["mods_loaded"] == 2


def test_loading_status_with_multiple_primary_mods() -> None:
    app = _build_mods_app()
    mod_a = MagicMock()
    mod_a.id = "mod-a"
    mod_a.primary = True
    mod_b = MagicMock()
    mod_b.id = "mod-b"
    mod_b.primary = True
    mock_mm = MagicMock()
    mock_mm._refresh_mods_root_if_needed.return_value = None
    mock_mm.scan_mods.return_value = [mod_a, mod_b]
    mock_mm.list_loaded_mods.return_value = []
    mock_mm._scan_manifest_errors = []
    mock_mm._blueprint_failures = []
    mock_mm._recent_load_failures = []
    mock_mm.mods_root = "/tmp/mods"
    mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
            side_effect=lambda ids: ids,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    body = resp.json()
    # 多个 primary_mod → primary_mod_id 为 None
    assert body["data"]["primary_mod_id"] is None
    assert body["data"]["primary_mod_count"] == 2


def test_loading_status_with_errors() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm._refresh_mods_root_if_needed.return_value = None
    mock_mm.scan_mods.return_value = []
    mock_mm.list_loaded_mods.return_value = []
    mock_mm._scan_manifest_errors = [{"mod_id": "m1", "error": "bad manifest"}]
    mock_mm._blueprint_failures = [{"mod_id": "m2", "error": "bp fail"}]
    mock_mm._recent_load_failures = [{"mod_id": "m3", "error": "load fail"}]
    mock_mm.mods_root = "/tmp/mods"
    mock_mm.all_mods_roots.return_value = ["/tmp/mods"]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.enterprise.mod_entitlements.filter_mod_id_list_for_enterprise",
            side_effect=lambda ids: ids,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    body = resp.json()
    assert body["data"]["partial_failure"] is True
    assert len(body["data"]["load_errors"]) == 1
    assert len(body["data"]["manifest_errors"]) == 1
    assert len(body["data"]["blueprint_errors"]) == 1


def test_loading_status_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("mod manager boom")

    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=_fail,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/loading-status")
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["partial_failure"] is True
    assert body["data"]["load_errors"][0]["mod_id"] == "unknown"
    assert "mod manager boom" in body["data"]["load_errors"][0]["error"]


def test_list_mods_happy_path() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm._mods_scan_fingerprint.return_value = "fp-1"
    mock_mm.list_all_mods.return_value = [{"id": "m1"}, {"id": "m2"}]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.fastapi_routes.mods_routes._sync_enterprise_entitlements_from_request",
            return_value=None,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == [{"id": "m1"}, {"id": "m2"}]
    assert resp.headers.get("ETag") is not None


def test_list_mods_etag_304() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm._mods_scan_fingerprint.return_value = "fp-1"
    mock_mm.list_all_mods.return_value = []
    import hashlib

    expected_etag = hashlib.sha256(b"fp-1").hexdigest()[:32]
    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
        patch(
            "app.fastapi_routes.mods_routes._sync_enterprise_entitlements_from_request",
            return_value=None,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/", headers={"if-none-match": expected_etag})
    assert resp.status_code == 304


def test_list_mods_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("list boom")

    with (
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=_fail,
        ),
        patch(
            "app.fastapi_routes.mods_routes._sync_enterprise_entitlements_from_request",
            return_value=None,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/")
    body = resp.json()
    assert body["success"] is False
    assert "list boom" in body["error"]


def test_list_routes_happy_path() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm.get_routes.return_value = [{"path": "/x"}]
    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        return_value=mock_mm,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/routes")
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == [{"path": "/x"}]


def test_list_routes_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("routes boom")

    with patch(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        side_effect=_fail,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/routes")
    body = resp.json()
    assert body["success"] is False
    assert "routes boom" in body["error"]


def test_list_comms_endpoints_happy_path() -> None:
    app = _build_mods_app()
    mock_comms = MagicMock()
    mock_comms.list_endpoints.return_value = [{"name": "ep1"}]
    with patch(
        "app.infrastructure.mods.comms.get_mod_comms",
        return_value=mock_comms,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/comms/endpoints")
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == [{"name": "ep1"}]


def test_list_comms_endpoints_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("comms boom")

    with patch(
        "app.infrastructure.mods.comms.get_mod_comms",
        side_effect=_fail,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/comms/endpoints")
    body = resp.json()
    assert body["success"] is False
    assert "comms boom" in body["error"]


def test_employee_pack_config_preview_not_found(tmp_path: Any) -> None:
    app = _build_mods_app()
    with patch(
        "app.infrastructure.mods.mod_manager._default_mods_root",
        return_value=str(tmp_path),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/employee-packs/missing-pack/config-preview")
    body = resp.json()
    assert body["success"] is False
    assert "未安装" in body["error"] or "manifest" in body["error"]


def test_employee_pack_config_preview_valid(tmp_path: Any) -> None:
    app = _build_mods_app()
    pack_dir = tmp_path / "_employees" / "pack-1"
    pack_dir.mkdir(parents=True)
    manifest = {
        "id": "pack-1",
        "employee_config_v2": {
            "cognition": {
                "agent": {
                    "model": {"name": "gpt-4"},
                    "system_prompt": "You are helpful.",
                }
            }
        },
        "xcagi_host_profile": {"sku": "enterprise"},
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with patch(
        "app.infrastructure.mods.mod_manager._default_mods_root",
        return_value=str(tmp_path),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/employee-packs/pack-1/config-preview")
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["pack_id"] == "pack-1"
    assert body["data"]["has_employee_config_v2"] is True
    assert body["data"]["cognition_model"] == {"name": "gpt-4"}
    assert "You are helpful" in body["data"]["system_prompt_preview"]
    assert body["data"]["xcagi_host_profile"] == {"sku": "enterprise"}


def test_employee_pack_config_preview_invalid_json(tmp_path: Any) -> None:
    app = _build_mods_app()
    pack_dir = tmp_path / "_employees" / "pack-2"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text("not-json", encoding="utf-8")
    with patch(
        "app.infrastructure.mods.mod_manager._default_mods_root",
        return_value=str(tmp_path),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/employee-packs/pack-2/config-preview")
    body = resp.json()
    assert body["success"] is False


def test_employee_pack_config_preview_no_v2(tmp_path: Any) -> None:
    app = _build_mods_app()
    pack_dir = tmp_path / "_employees" / "pack-3"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(json.dumps({"id": "pack-3"}), encoding="utf-8")
    with patch(
        "app.infrastructure.mods.mod_manager._default_mods_root",
        return_value=str(tmp_path),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/employee-packs/pack-3/config-preview")
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["has_employee_config_v2"] is False
    assert body["data"]["cognition_model"] == {}
    assert body["data"]["system_prompt_preview"] == ""
    assert body["data"]["xcagi_host_profile"] is None


def test_get_mod_detail_mods_disabled_returns_404() -> None:
    app = _build_mods_app()
    with patch(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        return_value=True,
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/some-mod")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_get_mod_detail_not_found() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm.ensure_mods_loaded.return_value = None
    mock_mm.get_mod.return_value = None
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/missing-mod")
    assert resp.status_code == 404


def test_get_mod_detail_happy_path() -> None:
    app = _build_mods_app()
    mock_mod = MagicMock()
    mock_mod.id = "m1"
    mock_mod.name = "Mod 1"
    mock_mod.version = "1.0.0"
    mock_mod.author = "author"
    mock_mod.description = "desc"
    mock_mod.frontend_menu = {}
    mock_mod.frontend_menu_overrides = {}
    mock_mod.comms_exports = []
    mock_mm = MagicMock()
    mock_mm.ensure_mods_loaded.return_value = None
    mock_mm.get_mod.return_value = mock_mod
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/m1")
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == "m1"
    assert body["data"]["name"] == "Mod 1"


def test_get_mod_detail_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("detail boom")

    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=_fail,
        ),
    ):
        client = TestClient(app)
        resp = client.get("/api/mods/m1")
    assert resp.status_code == 500
    assert resp.json()["success"] is False


def test_uninstall_mod_mods_disabled_returns_403() -> None:
    app = _build_mods_app()
    with patch(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        return_value=True,
    ):
        client = TestClient(app)
        resp = client.delete("/api/mods/m1")
    assert resp.status_code == 403


def test_uninstall_mod_empty_id_returns_400() -> None:
    app = _build_mods_app()
    with patch(
        "app.infrastructure.mods.mod_manager.is_mods_disabled",
        return_value=False,
    ):
        client = TestClient(app)
        resp = client.delete("/api/mods/   ")
    assert resp.status_code == 400


def test_uninstall_mod_failure_returns_400() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm.uninstall_mod.return_value = (False, "mod not installed")
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
    ):
        client = TestClient(app)
        resp = client.delete("/api/mods/m1")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_uninstall_mod_happy_path() -> None:
    app = _build_mods_app()
    mock_mm = MagicMock()
    mock_mm.uninstall_mod.return_value = (True, "uninstalled")
    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            return_value=mock_mm,
        ),
    ):
        client = TestClient(app)
        resp = client.delete("/api/mods/m1")
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == {"id": "m1"}


def test_uninstall_mod_recoverable_error() -> None:
    app = _build_mods_app()

    def _fail() -> None:
        raise RuntimeError("uninstall boom")

    with (
        patch(
            "app.infrastructure.mods.mod_manager.is_mods_disabled",
            return_value=False,
        ),
        patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=_fail,
        ),
    ):
        client = TestClient(app)
        resp = client.delete("/api/mods/m1")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# mods_routes — _sync_enterprise_entitlements_from_request helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_enterprise_entitlements_helper_happy_path() -> None:
    from app.fastapi_routes import mods_routes

    request = MagicMock()
    called = {"n": 0}

    async def _sync(req: Any) -> None:
        called["n"] += 1

    with patch(
        "app.enterprise.mod_entitlements.sync_entitlements_from_request",
        _sync,
    ):
        await mods_routes._sync_enterprise_entitlements_from_request(request)
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_sync_enterprise_entitlements_helper_recoverable_error() -> None:
    from app.fastapi_routes import mods_routes

    request = MagicMock()

    async def _sync(req: Any) -> None:
        raise RuntimeError("sync boom")

    with patch(
        "app.enterprise.mod_entitlements.sync_entitlements_from_request",
        _sync,
    ):
        # 不应抛出
        await mods_routes._sync_enterprise_entitlements_from_request(request)
