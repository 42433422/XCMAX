"""覆盖 app/application/session_account_meta.py 的 DB 触达分支与边界。

聚焦此前未覆盖的逻辑：
- extract_market_user_blob 的 data 非 dict 兜底
- persist_session_membership_tier（成功/空 sid/行不存在/异常）
- enrich_session_meta_with_tenant（user.tenant_id / bind_tenant_for_login / tenant 名查询 / 回写 sessions.tenant_id）
- clear_impersonation
- should_receive_enterprise_dedicated_cs（meta 命中各分支 + DB 兜底）
- audit_admin_action（成功 + ImportError 兜底）

所有外部依赖（get_host_db、bind_tenant_for_login、legacy_helpers）均被 mock，
测试离线、确定性。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.application.session_account_meta as mod
from app.application.session_account_meta import (
    audit_admin_action,
    clear_impersonation,
    enrich_session_meta_with_tenant,
    extract_market_user_blob,
    persist_session_membership_tier,
    should_receive_enterprise_dedicated_cs,
)

MODPATH = "app.application.session_account_meta"


def _make_db_cm(db):
    """构造一个上下文管理器函数，yield 出给定的 fake db。"""

    @contextmanager
    def _cm():
        yield db

    return _cm


# --------------------------------------------------------------------------- #
# extract_market_user_blob: data 既无 user 又非可用 dict 的尾部 return {} (line 59)
# --------------------------------------------------------------------------- #
class TestExtractMarketUserBlobTail:
    def test_data_not_dict_returns_empty(self):
        # raw.data 不是 dict -> 跳过 data 分支 -> 落到尾部 return {}
        assert extract_market_user_blob({"raw": {"data": "not-a-dict"}}) == {}

    def test_data_dict_user_not_dict_returns_data(self):
        # data 是 dict 但 data.user 不是 dict -> 返回 data 本身
        out = extract_market_user_blob({"raw": {"data": {"user": "x", "company": "C"}}})
        assert out == {"user": "x", "company": "C"}


# --------------------------------------------------------------------------- #
# persist_session_membership_tier (lines 140-151)
# --------------------------------------------------------------------------- #
class TestPersistMembershipTier:
    def test_empty_sid_noop(self):
        # 空 session_id 直接返回，不应触碰 DB
        with patch(f"{MODPATH}.get_host_db") as gh:
            persist_session_membership_tier("", "vip")
            gh.assert_not_called()

    def test_writes_tier_trimmed_and_capped(self):
        row = SimpleNamespace(market_membership_tier=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            persist_session_membership_tier("sid-1", "  gold  ")
        assert row.market_membership_tier == "gold"
        db.commit.assert_called_once()

    def test_long_tier_truncated_to_32(self):
        row = SimpleNamespace(market_membership_tier=None)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            persist_session_membership_tier("sid-1", "x" * 100)
        assert row.market_membership_tier == "x" * 32

    def test_blank_tier_becomes_none(self):
        # 空白 tier -> "".strip()[:32] -> "" -> or None
        row = SimpleNamespace(market_membership_tier="old")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            persist_session_membership_tier("sid-1", "   ")
        assert row.market_membership_tier is None
        db.commit.assert_called_once()

    def test_row_missing_noop(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            persist_session_membership_tier("sid-x", "gold")
        db.commit.assert_not_called()

    def test_db_error_swallowed(self):
        # get_host_db 抛 RECOVERABLE_ERRORS 子类 -> except 分支吞掉，不抛出
        @contextmanager
        def _boom():
            raise ValueError("db down")
            yield  # pragma: no cover

        with patch(f"{MODPATH}.get_host_db", _boom):
            # 不应抛异常
            persist_session_membership_tier("sid-1", "gold")


# --------------------------------------------------------------------------- #
# clear_impersonation (lines 253-266)
# --------------------------------------------------------------------------- #
class TestClearImpersonation:
    def test_empty_sid_noop(self):
        with patch(f"{MODPATH}.get_host_db") as gh:
            clear_impersonation("")
            gh.assert_not_called()

    def test_clears_fields(self):
        row = SimpleNamespace(
            impersonating_market_user_id=42,
            impersonating_username="boss",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = row
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            clear_impersonation("sid-1")
        assert row.impersonating_market_user_id is None
        assert row.impersonating_username == ""
        db.commit.assert_called_once()

    def test_row_missing_noop(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
            clear_impersonation("sid-x")
        db.commit.assert_not_called()

    def test_db_error_swallowed(self):
        @contextmanager
        def _boom():
            raise RuntimeError("boom")
            yield  # pragma: no cover

        with patch(f"{MODPATH}.get_host_db", _boom):
            clear_impersonation("sid-1")  # 不抛出即通过


# --------------------------------------------------------------------------- #
# should_receive_enterprise_dedicated_cs (lines 282-304)
# --------------------------------------------------------------------------- #
class TestShouldReceiveDedicatedCS:
    def test_admin_meta_returns_false(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "admin"},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is False

    def test_market_admin_flag_returns_false(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "enterprise", "market_is_admin": True},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is False

    def test_enterprise_kind_returns_true(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "enterprise"},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is True

    def test_market_enterprise_flag_returns_true(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "personal", "market_is_enterprise": True},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is True

    def test_impersonating_returns_true(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={
                "account_kind": "personal",
                "impersonating_market_user_id": 5,
            },
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is True

    def test_personal_no_flags_returns_false(self):
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "personal"},
        ):
            assert should_receive_enterprise_dedicated_cs("sid", None, None) is False

    def test_no_meta_no_user_returns_false(self):
        # meta 为空 + user_id None -> 兜底 False (line 292-293)
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, None, None) is False

    def test_no_meta_db_none_returns_false(self):
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, 7, None) is False

    def test_db_fallback_normal_role_true(self):
        # meta 空 -> 走 DB 兜底；user.role 非管理员 -> True (line 303-304)
        db = MagicMock()
        db.get.return_value = SimpleNamespace(role="user")
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, 7, db) is True
        db.get.assert_called_once()

    def test_db_fallback_admin_role_false(self):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(role="market_admin")
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, 7, db) is False

    def test_db_fallback_lookup_error_returns_false(self):
        # db.get 抛 RECOVERABLE_ERRORS -> except 分支 False (line 298-300)
        db = MagicMock()
        db.get.side_effect = RuntimeError("db gone")
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, 7, db) is False

    def test_db_fallback_bad_user_id_returns_false(self):
        # int(user_id) 抛 ValueError -> except (TypeError, ValueError) -> False (line 301-302)
        db = MagicMock()
        with patch(f"{MODPATH}.load_session_account_meta", return_value=None):
            assert should_receive_enterprise_dedicated_cs(None, "not-int", db) is False


# --------------------------------------------------------------------------- #
# enrich_session_meta_with_tenant (lines 207, 213-223, 235-248)
# --------------------------------------------------------------------------- #
class TestEnrichSessionMetaWithTenant:
    def test_admin_short_circuits(self):
        # account_kind=admin -> 直接返回 meta，不查租户
        with patch(
            f"{MODPATH}.load_session_account_meta",
            return_value={"account_kind": "admin"},
        ):
            user = SimpleNamespace(id=11, tenant_id=99, username="a")
            meta = enrich_session_meta_with_tenant("sid", user)
        assert meta["account_kind"] == "admin"
        assert meta["local_user_id"] == 11
        assert "tenant_id" not in meta or meta.get("tenant_id") is None

    def test_tenant_from_user_attr(self):
        # meta 无 tenant_id，从 user.tenant_id 取 (line 207)；tenant_name 从 company_brand 兜底 (238)
        meta_in = {"account_kind": "enterprise", "company_brand": "甲公司"}
        with patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in):
            db = MagicMock()
            # tenant 查询返回 None -> 不设置 tenant_name；之后 company_brand 兜底
            db.query.return_value.filter.return_value.first.return_value = None
            user = SimpleNamespace(id=3, tenant_id=55, username="u")
            with patch(f"{MODPATH}.get_host_db", _make_db_cm(db)):
                meta = enrich_session_meta_with_tenant("sid-attr", user)
        assert meta["tenant_id"] == 55
        assert meta["tenant_name"] == "甲公司"

    def test_tenant_name_from_db(self):
        # tenant 查询命中且有 name -> tenant_name 来自 DB (line 233-234)
        meta_in = {"account_kind": "enterprise", "tenant_id": 7, "company_brand": "fallback"}
        tenant = SimpleNamespace(id=7, name="  真实租户  ")
        # sessions 回写时该行 tenant_id 已等于 7 -> 不触发 commit（覆盖 244 的 != 假分支）
        sess_row = SimpleNamespace(tenant_id=7)
        db = MagicMock()
        # 第一次 first() 返回 tenant（名查询），第二次返回 sess_row（回写查询）
        db.query.return_value.filter.return_value.first.side_effect = [tenant, sess_row]
        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in),
            patch(f"{MODPATH}.get_host_db", _make_db_cm(db)),
        ):
            meta = enrich_session_meta_with_tenant("sid-db", None)
        assert meta["tenant_id"] == 7
        assert meta["tenant_name"] == "真实租户"

    def test_tenant_name_lookup_error_swallowed(self):
        # tenant 名查询抛 RECOVERABLE_ERRORS -> except 吞掉 (line 235-236)，再走 company_brand 兜底
        meta_in = {"account_kind": "enterprise", "tenant_id": 8, "company_brand": "牌子"}

        @contextmanager
        def _boom():
            raise RuntimeError("tenant query down")
            yield  # pragma: no cover

        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in),
            patch(f"{MODPATH}.get_host_db", _boom),
        ):
            meta = enrich_session_meta_with_tenant("sid-err", None)
        assert meta["tenant_id"] == 8
        # DB 失败 -> 兜底用 company_brand
        assert meta["tenant_name"] == "牌子"

    def test_bind_tenant_for_login_branch(self):
        # meta 无 tenant_id 且无 user.tenant_id，但有 local_user_id -> 走 bind (line 212-223)
        meta_in = {"account_kind": "enterprise", "company_brand": "C"}
        user = SimpleNamespace(id=21, tenant_id=None, username="zhang")

        fake_bind = MagicMock(return_value={"tenant_id": 77, "tenant_name": "绑定租户"})
        # tid 已得到 -> 进入 line 225+；tenant_name 已由 bind 提供，故不查 DB
        db = MagicMock()
        # 用于回写 sessions.tenant_id 的 row（tenant_id 不同 -> 触发回写 245-246）
        row = SimpleNamespace(tenant_id=1)
        db.query.return_value.filter.return_value.first.return_value = row

        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in),
            patch(f"{MODPATH}.get_host_db", _make_db_cm(db)),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                fake_bind,
            ),
        ):
            meta = enrich_session_meta_with_tenant("sid-bind", user)

        fake_bind.assert_called_once()
        assert meta["tenant_id"] == 77
        assert meta["tenant_name"] == "绑定租户"
        # sessions.tenant_id 已回写
        assert row.tenant_id == 77
        db.commit.assert_called_once()

    def test_persist_session_tenant_error_swallowed(self):
        # 回写 sessions.tenant_id 时 DB 抛错 -> except 吞掉 (line 247-248)
        meta_in = {
            "account_kind": "enterprise",
            "tenant_id": 9,
            "company_brand": "X",
            "tenant_name": "已有名",
        }
        calls = {"n": 0}

        @contextmanager
        def _cm():
            # tenant_name 已存在 -> 不进 tenant 名查询块；只在回写 sessions 块用一次 -> 抛错
            calls["n"] += 1
            raise RuntimeError("persist failed")
            yield  # pragma: no cover

        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in),
            patch(f"{MODPATH}.get_host_db", _cm),
        ):
            meta = enrich_session_meta_with_tenant("sid-9", None)
        # 即使回写失败，meta 仍正确返回
        assert meta["tenant_id"] == 9
        assert meta["tenant_name"] == "已有名"

    def test_no_tenant_anywhere_returns_meta(self):
        # 无 tenant_id、无 user、无 local_user_id -> tid 仍 None -> 直接返回 meta
        meta_in = {"account_kind": "enterprise", "company_brand": "C"}
        with patch(f"{MODPATH}.load_session_account_meta", return_value=meta_in):
            meta = enrich_session_meta_with_tenant("sid-none", None)
        assert meta.get("tenant_id") is None
        assert "tenant_name" not in meta


# --------------------------------------------------------------------------- #
# audit_admin_action (lines 326-344)
# --------------------------------------------------------------------------- #
class TestAuditAdminAction:
    def _install_fake_legacy(self, sid_value):
        """注入 fake app.fastapi_routes.legacy_helpers 模块（真实模块不存在）。"""
        fake = ModuleType("app.fastapi_routes.legacy_helpers")
        fake._session_id_from_request = MagicMock(return_value=sid_value)
        sys.modules["app.fastapi_routes.legacy_helpers"] = fake
        return fake

    def teardown_method(self):
        sys.modules.pop("app.fastapi_routes.legacy_helpers", None)

    def test_success_logs_with_operator(self):
        fake = self._install_fake_legacy("sid-77")
        meta = {"impersonating_username": "boss", "market_user_id": 9}
        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta),
            patch.object(mod.logger, "info") as log_info,
        ):
            audit_admin_action(
                request=object(),
                action="delete_user",
                target_user_id=5,
                mod_id="m1",
                detail="boom",
            )
        fake._session_id_from_request.assert_called_once()
        log_info.assert_called_once()
        # 校验关键参数被传入日志
        args = log_info.call_args.args
        assert "delete_user" in args
        assert "sid-77" in args

    def test_success_operator_from_market_user_id(self):
        # impersonating_username 为空 -> 第二次 load 取 market_user_id (line 332-334)
        self._install_fake_legacy("sid-88")
        meta = {"impersonating_username": "", "market_user_id": 123}
        with (
            patch(f"{MODPATH}.load_session_account_meta", return_value=meta) as load_mock,
            patch.object(mod.logger, "info") as log_info,
        ):
            audit_admin_action(request=object(), action="grant", detail="")
        # detail 为空 -> 走 operator 分支，触发第二次 load
        assert load_mock.call_count == 2
        log_info.assert_called_once()

    def test_import_error_swallowed(self):
        # 不注入 fake 模块 -> import 抛 ImportError ∈ RECOVERABLE_ERRORS -> except 吞掉
        sys.modules.pop("app.fastapi_routes.legacy_helpers", None)
        with patch.object(mod.logger, "exception") as log_exc:
            audit_admin_action(request=object(), action="x")
        # except 分支记录 exception
        log_exc.assert_called_once()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
