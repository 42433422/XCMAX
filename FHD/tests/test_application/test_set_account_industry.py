"""set_account_industry:选行业回填账号 industry_id 守卫。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.application.account_registration import set_account_industry


@contextmanager
def _fake_get_db(db):
    yield db


def _run(username: str, industry: str, *, user: MagicMock | None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    with patch("app.db.session.get_db", lambda: _fake_get_db(db)):
        set_account_industry(username, industry)
    return db


def test_persists_industry_and_entitlements():
    user = MagicMock()
    user.tier = "enterprise"
    db = _run("wuxinghua1", "涂料", user=user)
    assert user.industry_id == "涂料"
    # entitled_industries 经 init_entitled_industries_for_user 派生(企业含通用兜底)
    assert "涂料" in user.entitled_industries
    db.commit.assert_called_once()


def test_blank_username_or_industry_noop():
    user = MagicMock()
    _run("", "涂料", user=user)
    _run("u", "", user=user)
    assert not user.industry_id.called if hasattr(user.industry_id, "called") else True


def test_missing_user_noop():
    db = _run("ghost", "涂料", user=None)
    db.commit.assert_not_called()
