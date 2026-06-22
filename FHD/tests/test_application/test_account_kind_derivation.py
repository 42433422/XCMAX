"""会话档位派生（维度 1：account_kind ← User.tier + 市场身份提升）单元测试。"""

from __future__ import annotations

from app.application.session_account_meta import derive_account_kind_from_user


class TestDeriveAccountKindFromUser:
    def test_tier_primary(self):
        assert derive_account_kind_from_user(tier="admin") == "admin"
        assert derive_account_kind_from_user(tier="enterprise") == "enterprise"
        assert derive_account_kind_from_user(tier="personal") == "personal"
        assert derive_account_kind_from_user(tier="") == "personal"
        assert derive_account_kind_from_user(tier=None) == "personal"

    def test_market_elevates_up(self):
        # 市场身份高于本地 tier 时向上提升
        assert (
            derive_account_kind_from_user(tier="personal", market_is_enterprise=True)
            == "enterprise"
        )
        assert derive_account_kind_from_user(tier="personal", market_is_admin=True) == "admin"
        assert derive_account_kind_from_user(tier="enterprise", market_is_admin=True) == "admin"

    def test_market_does_not_downgrade(self):
        # 本地 tier 高于市场身份时不下调
        assert derive_account_kind_from_user(tier="admin", market_is_enterprise=False) == "admin"
        assert (
            derive_account_kind_from_user(tier="enterprise", market_is_enterprise=False)
            == "enterprise"
        )
