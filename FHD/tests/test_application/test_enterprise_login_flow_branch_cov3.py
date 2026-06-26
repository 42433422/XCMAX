"""测试 app.application.enterprise_login_flow 的异步函数分支覆盖（cov3）。

覆盖目标（cov2 已覆盖同步辅助函数，本文件聚焦异步函数的缺失分支）：
- ensure_local_user_after_market：password=None 分支、create_session_for_username 分支、
  email 从 blob 回填分支、jit_create 成功后 login 分支
- finalize_enterprise_login：skip_market_sync / market_result None / token 绑定 /
  tenant 绑定 / membership tier / enterprise mod 权益 / fallback mod 权益 /
  RECOVERABLE_ERRORS 异常分支
- run_market_first_login：enterprise SKU 市场不可达管理员应急登录 / 市场成功 /
  非企业 SKU 本地直登 / login_market_fn 调用 / 用户名为空拒绝
- finalize_auth_after_oidc：market 成功/失败 / kind_err 覆盖 / skip_market_sync
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.enterprise_login_flow import (
    ensure_local_user_after_market,
    finalize_auth_after_oidc,
    finalize_enterprise_login,
    run_market_first_login,
)


# ───────────────────── helpers ─────────────────────


def _mock_db_ctx(user=None, exc=None):
    """Build a mock get_db() context manager.

    If exc is provided, __enter__ raises it (triggers RECOVERABLE_ERRORS).
    Otherwise __enter__ returns a mock db with query/get configured.
    """
    ctx = MagicMock()
    if exc is not None:
        ctx.__enter__.side_effect = exc
        ctx.__exit__.return_value = None
        return ctx
    db = MagicMock()
    db.get.return_value = user
    db.query.return_value.filter.return_value.first.return_value = user
    ctx.__enter__.return_value = db
    ctx.__exit__.return_value = None
    return ctx


# ───────────────────── ensure_local_user_after_market ─────────────────────


class TestEnsureLocalUserAfterMarketBranches:
    """覆盖 ensure_local_user_after_market 的缺失分支。"""

    @pytest.mark.asyncio
    async def test_no_password_user_exists_creates_session(self):
        """password=None 且用户已存在 → create_session_for_username。"""
        mock_user = MagicMock()
        auth_svc = MagicMock()
        auth_svc.create_session_for_username.return_value = {"success": True, "token": "t"}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=mock_user)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
        ):
            result, err = await ensure_local_user_after_market(
                username="alice",
                password=None,
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert result["success"] is True
        assert err is None
        auth_svc.create_session_for_username.assert_called_once_with("alice")

    @pytest.mark.asyncio
    async def test_no_password_user_not_exists_jit_create_success(self):
        """password=None 且用户不存在 → jit_create → create_session。"""
        auth_svc = MagicMock()
        auth_svc.create_session_for_username.return_value = {"success": True, "token": "t"}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=None)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"email": "a@b.com"},
            ),
        ):
            result, err = await ensure_local_user_after_market(
                username="newuser",
                password=None,
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(return_value=True),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert result["success"] is True
        assert err is None

    @pytest.mark.asyncio
    async def test_no_password_user_not_exists_jit_create_fails(self):
        """password=None 且用户不存在 → jit_create 失败 → 500。"""
        auth_svc = MagicMock()
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=None)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={},
            ),
        ):
            result, err = await ensure_local_user_after_market(
                username="newuser",
                password=None,
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(return_value=False),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 500

    @pytest.mark.asyncio
    async def test_password_login_success_first_try(self):
        """password 提供且 login 成功 → 直接返回。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "token": "t"}
        result, err = await ensure_local_user_after_market(
            username="alice",
            password="pass",
            market_result={},
            auth_app_service=auth_svc,
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is not None
        assert result["success"] is True
        assert err is None

    @pytest.mark.asyncio
    async def test_password_login_fails_user_not_exists_jit_create_then_login(self):
        """password 提供、login 失败、用户不存在 → jit_create → login 再次尝试。"""
        auth_svc = MagicMock()
        auth_svc.login.side_effect = [
            {"success": False},
            {"success": True, "token": "t"},
        ]
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=None)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"email": "a@b.com"},
            ),
        ):
            result, err = await ensure_local_user_after_market(
                username="newuser",
                password="pass",
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(return_value=True),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert result["success"] is True
        assert err is None

    @pytest.mark.asyncio
    async def test_password_login_fails_user_not_exists_jit_create_then_login_fails(self):
        """password 提供、login 失败、用户不存在 → jit_create → login 仍失败 → 401。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=None)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={},
            ),
        ):
            result, err = await ensure_local_user_after_market(
                username="newuser",
                password="pass",
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(return_value=True),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 200  # 401 mapped to 200

    @pytest.mark.asyncio
    async def test_email_from_blob_when_raw_empty(self):
        """raw 无 email 但 blob 有 email → email 从 blob 回填。"""
        auth_svc = MagicMock()
        auth_svc.create_session_for_username.return_value = {"success": True}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=None)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"email": "blob@x.com"},
            ),
        ):
            await ensure_local_user_after_market(
                username="newuser",
                password=None,
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(return_value=True),
                market_user_email_from_raw=MagicMock(return_value=""),
            )

    @pytest.mark.asyncio
    async def test_database_error_returns_503(self):
        """DB 异常（RECOVERABLE_ERRORS）→ 503。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(exc=RuntimeError("db down"))),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
        ):
            result, err = await ensure_local_user_after_market(
                username="alice",
                password="pass",
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 503

    @pytest.mark.asyncio
    async def test_create_session_fails_returns_error(self):
        """password=None、用户已存在、create_session 失败 → 401。"""
        mock_user = MagicMock()
        auth_svc = MagicMock()
        auth_svc.create_session_for_username.return_value = {"success": False}
        with (
            patch("app.db.session.get_db", return_value=_mock_db_ctx(user=mock_user)),
            patch("app.db.init_db.ensure_runtime_auth_bootstrap"),
        ):
            result, err = await ensure_local_user_after_market(
                username="alice",
                password=None,
                market_result={},
                auth_app_service=auth_svc,
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 200  # 401 mapped to 200


# ───────────────────── finalize_enterprise_login ─────────────────────


class TestFinalizeEnterpriseLogin:
    """覆盖 finalize_enterprise_login 的各分支。"""

    @pytest.mark.asyncio
    async def test_no_session_id_returns_result_unchanged(self):
        """session_id=None → 直接返回 result。"""
        result = {"user": {"id": 1}}
        out = await finalize_enterprise_login(
            result=result,
            session_id=None,
            market_result=None,
            account_kind="personal",
            username="alice",
            sku="personal",
        )
        assert out is result

    @pytest.mark.asyncio
    async def test_market_result_none_personal_sku_sets_password_for_market(self):
        """market_result=None 且 sku != enterprise → password_for_market=True 分支。"""
        result = {"user": {"id": 1}}
        with patch(
            "app.fastapi_routes.market_account.save_session_market_token"
        ) as mock_save:
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=None,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        # market_result is None → no token save, no market_account key
        mock_save.assert_not_called()
        assert "market_account" not in out or out.get("market_account") is None

    @pytest.mark.asyncio
    async def test_market_result_none_enterprise_sku_sets_failed(self):
        """market_result=None 且 sku == enterprise → market_result = {"success": False}。"""
        result = {"user": {"id": 1}}
        out = await finalize_enterprise_login(
            result=result,
            session_id="sid",
            market_result=None,
            account_kind="enterprise",
            username="alice",
            sku="enterprise",
        )
        # market_result becomes {"success": False} → market_account added
        assert out.get("market_account") is not None
        assert out["market_account"]["success"] is False

    @pytest.mark.asyncio
    async def test_skip_market_sync_sets_failed_market(self):
        """skip_market_sync=True → market_result = {"success": False} 分支。"""
        result = {"user": {"id": 1}, "company_brand": "Brand"}
        with (
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": 42, "tenant_name": "Brand"},
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result={"success": True, "token": "tok"},
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
                skip_market_sync=True,
            )
        # skip_market_sync → goes to elif branch, binds tenant from result
        assert out.get("tenant_id") == 42

    @pytest.mark.asyncio
    async def test_market_success_saves_token(self):
        """market_result.success=True 且有 token → save_session_market_token。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok", "refresh_token": "mref"}
        with (
            patch(
                "app.fastapi_routes.market_account.save_session_market_token"
            ) as mock_save,
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 10, "username": "alice"},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="Brand",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": 42, "tenant_name": "Brand"},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="enterprise",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        mock_save.assert_called_once_with("sid", "mtok", "mref")
        assert out["market_access_token"] == "mtok"
        assert out["market_refresh_token"] == "mref"
        assert out["account_kind"] == "enterprise"
        assert out["company_brand"] == "Brand"
        assert out["market_is_admin"] is False
        assert out["market_is_enterprise"] is False

    @pytest.mark.asyncio
    async def test_market_success_no_refresh_token(self):
        """market_result.success=True 且有 token 但无 refresh_token。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok"}
        with (
            patch(
                "app.fastapi_routes.market_account.save_session_market_token"
            ),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 10},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="personal",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert out["market_access_token"] == "mtok"
        assert "market_refresh_token" not in out

    @pytest.mark.asyncio
    async def test_market_success_persists_membership_tier(self):
        """market_result.success=True 且 fetch_market_membership_tier 返回值 → 持久化。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok"}
        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 10},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="personal",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value="premium",
            ),
            patch(
                "app.application.session_account_meta.persist_session_membership_tier"
            ) as mock_persist_tier,
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        mock_persist_tier.assert_called_once_with("sid", "premium")
        assert out["market_membership_tier"] == "premium"

    @pytest.mark.asyncio
    async def test_market_success_user_id_none_skips_tenant(self):
        """market_result.success=True 但 result 无 user.id → 跳过 tenant 绑定。"""
        result = {}
        market = {"success": True, "token": "mtok"}
        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 10},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="Brand",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login"
            ) as mock_bind,
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="personal",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        mock_bind.assert_not_called()
        assert "tenant_id" not in out

    @pytest.mark.asyncio
    async def test_market_success_market_uid_from_blob(self):
        """market_result.success=True 且 blob 有 id → market_uid = int(id)。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok"}
        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": "42"},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="personal",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ) as mock_persist,
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        # persist_session_account_meta called with market_user_id=42
        call_args = mock_persist.call_args
        assert call_args.kwargs.get("market_user_id") == 42

    @pytest.mark.asyncio
    async def test_enterprise_sku_mod_entitlements(self):
        """sku=enterprise + market success + token → mod 权益刷新。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok", "raw": {"user": {"id": 5}}}
        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 5},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="enterprise",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.refresh_session_entitlements_from_market",
                new_callable=AsyncMock,
                return_value=[1, 2, 3],
            ),
            patch(
                "app.enterprise.mod_entitlements.persist_entitlements_to_session_row"
            ),
            patch(
                "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
                new_callable=AsyncMock,
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={1, 2, 3},
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
            )
        assert out["entitled_mod_ids"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_enterprise_sku_mod_entitlements_cached_none(self):
        """sku=enterprise + market success + token + cached=None → 无 entitled_mod_ids。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok", "raw": {"user": {"id": 5}}}
        with (
            patch("app.fastapi_routes.market_account.save_session_market_token"),
            patch(
                "app.application.enterprise_login_flow.extract_market_user_blob",
                return_value={"id": 5},
            ),
            patch(
                "app.application.enterprise_login_flow.company_brand_from_user_blob",
                return_value="",
            ),
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login",
                return_value={"tenant_id": None, "tenant_name": ""},
            ),
            patch(
                "app.application.enterprise_login_flow._derive_and_heal_account_kind",
                return_value="enterprise",
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
            patch(
                "app.fastapi_routes.market_account.fetch_market_membership_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.enterprise.mod_entitlements.refresh_session_entitlements_from_market",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.enterprise.mod_entitlements.persist_entitlements_to_session_row"
            ),
            patch(
                "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
                new_callable=AsyncMock,
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value=None,
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
            )
        assert "entitled_mod_ids" not in out

    @pytest.mark.asyncio
    async def test_recoverable_error_during_market_sync(self):
        """RECOVERABLE_ERRORS 异常 → market_account success=False。"""
        result = {"user": {"id": 1}}
        market = {"success": True, "token": "mtok"}
        with (
            patch(
                "app.fastapi_routes.market_account.save_session_market_token",
                side_effect=RuntimeError("market sync failed"),
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert out["market_account"]["success"] is False
        assert "市场账号自动同步失败" in out["market_account"]["message"]

    @pytest.mark.asyncio
    async def test_fallback_mod_entitlements(self):
        """session_id 存在且无 entitled_mod_ids → fallback mod binding 分支。"""
        result = {"user": {"id": 1}}
        market = {"success": False}
        with (
            patch(
                "app.enterprise.account_mod_binding.augment_entitled_client_mod_ids_for_username",
                return_value={10, 20},
            ),
            patch(
                "app.enterprise.mod_entitlements.set_session_entitlements"
            ),
            patch(
                "app.enterprise.mod_entitlements.persist_entitlements_to_session_row"
            ),
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=True,
            ),
            patch(
                "app.enterprise.mod_entitlements.reload_enterprise_mods_after_login",
                new_callable=AsyncMock,
            ),
            patch(
                "app.enterprise.mod_entitlements.get_cached_entitled_client_mod_ids",
                return_value={10, 20},
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert out["entitled_mod_ids"] == [10, 20]

    @pytest.mark.asyncio
    async def test_fallback_mod_entitlements_empty(self):
        """fallback mod binding 返回空 → 无 entitled_mod_ids。"""
        result = {"user": {"id": 1}}
        market = {"success": False}
        with (
            patch(
                "app.enterprise.account_mod_binding.augment_entitled_client_mod_ids_for_username",
                return_value=set(),
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert "entitled_mod_ids" not in out

    @pytest.mark.asyncio
    async def test_fallback_mod_entitlements_error(self):
        """fallback mod binding 异常 → 静默处理。"""
        result = {"user": {"id": 1}}
        market = {"success": False}
        with (
            patch(
                "app.enterprise.account_mod_binding.augment_entitled_client_mod_ids_for_username",
                side_effect=RuntimeError("fallback failed"),
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result=market,
                account_kind="personal",
                username="alice",
                sku="personal",
            )
        assert "entitled_mod_ids" not in out

    @pytest.mark.asyncio
    async def test_market_result_present_but_not_success(self):
        """market_result 存在但 success=False → market_account 添加但无 token。"""
        result = {"user": {"id": 1}}
        market = {"success": False, "message": "fail", "market_base_url": "http://m/"}
        out = await finalize_enterprise_login(
            result=result,
            session_id="sid",
            market_result=market,
            account_kind="personal",
            username="alice",
            sku="personal",
        )
        assert out["market_account"]["success"] is False
        assert out["market_account"]["message"] == "fail"

    @pytest.mark.asyncio
    async def test_skip_market_sync_no_user_id(self):
        """skip_market_sync=True 且 result 无 user.id → 跳过 tenant 绑定。"""
        result = {}
        with (
            patch(
                "app.application.enterprise_login_flow.bind_tenant_for_login"
            ) as mock_bind,
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
        ):
            out = await finalize_enterprise_login(
                result=result,
                session_id="sid",
                market_result={"success": True, "token": "tok"},
                account_kind="enterprise",
                username="alice",
                sku="enterprise",
                skip_market_sync=True,
            )
        mock_bind.assert_not_called()
        assert out["account_kind"] == "enterprise"


# ───────────────────── run_market_first_login ─────────────────────


class TestRunMarketFirstLogin:
    """覆盖 run_market_first_login 的各分支。"""

    @pytest.mark.asyncio
    async def test_enterprise_market_unreachable_admin_fallback(self):
        """enterprise SKU + 市场不可达 + admin 账号 + 密码 → 本地管理员应急登录。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {
            "success": True,
            "session_id": "sid",
            "user": {"role": "admin", "id": 1},
            "company_brand": "Brand",
        }
        with (
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={
                    "success": True,
                    "session_id": "sid",
                    "user": {"role": "admin", "id": 1},
                    "company_brand": "Brand",
                    "tenant_id": 42,
                },
            ),
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
        ):
            result, err = await run_market_first_login(
                username="admin",
                password="pass",
                account_kind="admin",
                market_result={"success": False, "message": "down"},
                auth_app_service=auth_svc,
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert result["account_kind"] == "admin"
        assert result["market_is_admin"] is True
        assert result["market_is_enterprise"] is True
        assert err is None

    @pytest.mark.asyncio
    async def test_enterprise_market_unreachable_admin_wrong_role(self):
        """enterprise SKU + 市场不可达 + admin 账号 + 但本地 role != admin → 拒绝。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {
            "success": True,
            "session_id": "sid",
            "user": {"role": "user", "id": 1},
        }
        result, err = await run_market_first_login(
            username="admin",
            password="pass",
            account_kind="admin",
            market_result={"success": False, "message": "down"},
            auth_app_service=auth_svc,
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_market_unreachable_not_admin(self):
        """enterprise SKU + 市场不可达 + 非 admin 账号 → 拒绝。"""
        result, err = await run_market_first_login(
            username="alice",
            password="pass",
            account_kind="personal",
            market_result={"success": False, "message": "down"},
            auth_app_service=MagicMock(),
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_market_unreachable_admin_no_password(self):
        """enterprise SKU + 市场不可达 + admin 账号 + 无密码 → 拒绝。"""
        result, err = await run_market_first_login(
            username="admin",
            password=None,
            account_kind="admin",
            market_result={"success": False, "message": "down"},
            auth_app_service=MagicMock(),
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_market_success(self):
        """enterprise SKU + 市场成功 → ensure_local_user → finalize。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "session_id": "sid", "user": {"id": 1}}
        market = {
            "success": True,
            "token": "mtok",
            "is_enterprise": True,
            "raw": {"user": {"username": "alice"}},
        }
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="alice",
            ),
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new_callable=AsyncMock,
                return_value=({"success": True, "session_id": "sid", "user": {"id": 1}}, None),
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ),
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="enterprise",
                market_result=market,
                auth_app_service=auth_svc,
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert err is None

    @pytest.mark.asyncio
    async def test_enterprise_market_success_kind_mismatch_ignored(self):
        """enterprise SKU + 市场成功 + kind 不匹配 → 仅记录日志，不拒绝。"""
        auth_svc = MagicMock()
        market = {
            "success": True,
            "token": "mtok",
            "is_enterprise": True,
        }
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value="kind mismatch error",
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="alice",
            ),
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new_callable=AsyncMock,
                return_value=({"success": True, "session_id": "sid"}, None),
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ),
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="personal",
                market_result=market,
                auth_app_service=auth_svc,
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert err is None

    @pytest.mark.asyncio
    async def test_enterprise_market_success_no_username_resolved(self):
        """enterprise SKU + 市场成功 + 无法解析用户名 → 502。"""
        market = {"success": True, "token": "mtok"}
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="",
            ),
        ):
            result, err = await run_market_first_login(
                username="",
                password="pass",
                account_kind="enterprise",
                market_result=market,
                auth_app_service=MagicMock(),
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is not None
        assert err.status_code == 502

    @pytest.mark.asyncio
    async def test_enterprise_market_success_ensure_local_fails(self):
        """enterprise SKU + 市场成功 + ensure_local 失败 → 返回错误。"""
        market = {"success": True, "token": "mtok"}
        err_resp = MagicMock()
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="alice",
            ),
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new_callable=AsyncMock,
                return_value=(None, err_resp),
            ),
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="enterprise",
                market_result=market,
                auth_app_service=MagicMock(),
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is None
        assert err is err_resp

    @pytest.mark.asyncio
    async def test_enterprise_market_none_login_market_fn_called(self):
        """enterprise SKU + market_result=None + login_market_fn → 调用 login_market_fn。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "session_id": "sid", "user": {"id": 1}}
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="alice",
            ),
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new_callable=AsyncMock,
                return_value=({"success": True, "session_id": "sid"}, None),
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ),
        ):
            login_market_fn = AsyncMock(return_value={"success": True, "token": "mtok"})
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="enterprise",
                market_result=None,
                auth_app_service=auth_svc,
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
                login_market_fn=login_market_fn,
            )
        login_market_fn.assert_called_once_with("alice", "pass")
        assert result is not None

    @pytest.mark.asyncio
    async def test_personal_sku_no_password(self):
        """非 enterprise SKU + 无密码 → 400。"""
        result, err = await run_market_first_login(
            username="alice",
            password=None,
            account_kind="personal",
            market_result=None,
            auth_app_service=MagicMock(),
            sku="personal",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None
        assert err.status_code == 200  # 400 mapped to 200

    @pytest.mark.asyncio
    async def test_personal_sku_login_fails(self):
        """非 enterprise SKU + login 失败 → 401。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        result, err = await run_market_first_login(
            username="alice",
            password="pass",
            account_kind="personal",
            market_result=None,
            auth_app_service=auth_svc,
            sku="personal",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None
        assert err.status_code == 200  # 401 mapped to 200

    @pytest.mark.asyncio
    async def test_personal_sku_login_success_with_market_fn(self):
        """非 enterprise SKU + login 成功 + login_market_fn → 调用 market_fn + finalize。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "session_id": "sid", "user": {"id": 1}}
        with (
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ),
        ):
            login_market_fn = AsyncMock(return_value={"success": True, "token": "mtok"})
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="personal",
                market_result=None,
                auth_app_service=auth_svc,
                sku="personal",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
                login_market_fn=login_market_fn,
            )
        login_market_fn.assert_called_once_with("alice", "pass")
        assert result is not None
        assert err is None

    @pytest.mark.asyncio
    async def test_personal_sku_login_success_no_market_fn(self):
        """非 enterprise SKU + login 成功 + 无 login_market_fn → finalize with market_result=None。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": True, "session_id": "sid", "user": {"id": 1}}
        with (
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ) as mock_finalize,
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="personal",
                market_result=None,
                auth_app_service=auth_svc,
                sku="personal",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert err is None
        # finalize called with market_result=None
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs.get("market_result") is None

    @pytest.mark.asyncio
    async def test_enterprise_admin_fallback_no_session_id(self):
        """enterprise + 市场不可达 + admin 登录成功但无 session_id → 不调 finalize。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {
            "success": True,
            "session_id": None,
            "user": {"role": "admin", "id": 1},
        }
        with (
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
            ) as mock_finalize,
            patch(
                "app.application.enterprise_login_flow.persist_session_account_meta"
            ),
        ):
            result, err = await run_market_first_login(
                username="admin",
                password="pass",
                account_kind="admin",
                market_result={"success": False, "message": "down"},
                auth_app_service=auth_svc,
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        assert result["account_kind"] == "admin"
        mock_finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_enterprise_admin_fallback_login_fails(self):
        """enterprise + 市场不可达 + admin 登录失败 → 拒绝。"""
        auth_svc = MagicMock()
        auth_svc.login.return_value = {"success": False}
        result, err = await run_market_first_login(
            username="admin",
            password="pass",
            account_kind="admin",
            market_result={"success": False, "message": "down"},
            auth_app_service=auth_svc,
            sku="enterprise",
            jit_create_fn=MagicMock(),
            market_user_email_from_raw=MagicMock(return_value=""),
        )
        assert result is None
        assert err is not None

    @pytest.mark.asyncio
    async def test_enterprise_market_success_no_session_id_in_result(self):
        """enterprise + 市场成功 + ensure_local 返回 result 无 session_id → finalize session_id=None。"""
        market = {"success": True, "token": "mtok"}
        with (
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.resolve_market_username",
                return_value="alice",
            ),
            patch(
                "app.application.enterprise_login_flow.ensure_local_user_after_market",
                new_callable=AsyncMock,
                return_value=({"success": True}, None),
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as mock_finalize,
        ):
            result, err = await run_market_first_login(
                username="alice",
                password="pass",
                account_kind="enterprise",
                market_result=market,
                auth_app_service=MagicMock(),
                sku="enterprise",
                jit_create_fn=MagicMock(),
                market_user_email_from_raw=MagicMock(return_value=""),
            )
        assert result is not None
        # finalize called with session_id=None (since result has no session_id)
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs.get("session_id") is None


# ───────────────────── finalize_auth_after_oidc ─────────────────────


class TestFinalizeAuthAfterOidc:
    """覆盖 finalize_auth_after_oidc 的各分支。"""

    @pytest.mark.asyncio
    async def test_market_success_enterprise_sku(self):
        """OIDC + market success + enterprise SKU → finalize。"""
        auth_result = {"user": {"username": "alice"}, "session_id": "sid"}
        oidc_profile = {"sub": "123"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "mtok", "is_enterprise": True},
            ),
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True, "session_id": "sid"},
            ) as mock_finalize,
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile=oidc_profile,
                oidc_access_token="oidc_tok",
                account_kind="enterprise",
                sku="enterprise",
            )
        assert out["success"] is True
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs.get("skip_market_sync") is False

    @pytest.mark.asyncio
    async def test_market_success_enterprise_sku_kind_mismatch(self):
        """OIDC + market success + enterprise + kind 不匹配 → market_result 覆盖为失败。"""
        auth_result = {"user": {"username": "alice"}, "session_id": "sid"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "mtok", "is_enterprise": True},
            ),
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value="kind mismatch",
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as mock_finalize,
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="",
                account_kind="personal",
                sku="enterprise",
            )
        call_kwargs = mock_finalize.call_args.kwargs
        # market_result should be overwritten to success=False
        assert call_kwargs["market_result"]["success"] is False
        assert call_kwargs["market_result"]["message"] == "kind mismatch"
        # skip_market_sync=True because market_result.success is False
        assert call_kwargs["skip_market_sync"] is True

    @pytest.mark.asyncio
    async def test_market_success_personal_sku(self):
        """OIDC + market success + personal SKU → finalize (不校验 kind)。"""
        auth_result = {"user": {"username": "alice"}, "session_id": "sid"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "mtok"},
            ),
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
            ) as mock_validate,
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ),
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="",
                account_kind="personal",
                sku="personal",
            )
        # validate_account_kind_for_market not called for non-enterprise SKU
        mock_validate.assert_not_called()
        assert out["success"] is True

    @pytest.mark.asyncio
    async def test_market_failure(self):
        """OIDC + market 失败 → finalize with skip_market_sync=True。"""
        auth_result = {"user": {"username": "alice"}, "session_id": "sid"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": False, "message": "fail"},
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as mock_finalize,
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="",
                account_kind="personal",
                sku="personal",
            )
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["skip_market_sync"] is True

    @pytest.mark.asyncio
    async def test_no_session_id(self):
        """OIDC + auth_result 无 session_id → finalize session_id=None。"""
        auth_result = {"user": {"username": "alice"}}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as mock_finalize,
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="",
                account_kind="personal",
                sku="personal",
            )
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["session_id"] is None

    @pytest.mark.asyncio
    async def test_empty_username(self):
        """OIDC + auth_result 无 username → username="" 传入 finalize。"""
        auth_result = {"session_id": "sid"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as mock_finalize,
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="",
                account_kind="personal",
                sku="personal",
            )
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["username"] == ""

    @pytest.mark.asyncio
    async def test_enterprise_market_success_no_kind_err(self):
        """OIDC + enterprise + market success + 无 kind_err → 正常 finalize。"""
        auth_result = {"user": {"username": "alice"}, "session_id": "sid"}
        with (
            patch(
                "app.fastapi_routes.market_account.login_market_for_oidc_profile",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "mtok", "is_enterprise": True, "is_market_admin": True},
            ),
            patch(
                "app.application.enterprise_login_flow.validate_account_kind_for_market",
                return_value=None,
            ),
            patch(
                "app.application.enterprise_login_flow.finalize_enterprise_login",
                new_callable=AsyncMock,
                return_value={"success": True},
            ),
        ):
            out = await finalize_auth_after_oidc(
                auth_result=auth_result,
                oidc_profile={},
                oidc_access_token="oidc_tok",
                account_kind="enterprise",
                sku="enterprise",
            )
        assert out["success"] is True
