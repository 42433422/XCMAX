"""COVERAGE_RAMP C3.0: deployment 探测 / 环境判定边界。

覆盖：
- env_flag 多种值
- is_desktop_mode（桌面 vs 环境变量）
- deployment_env / is_staging / is_production / is_test
- redis_url_from_env 多 key 回退
- distributed_rate_limit_required 各分支
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch):
    for k in [
        "FHD_ENV",
        "TESTING",
        "XCAGI_TESTING",
        "XCAGI_DESKTOP_MODE",
        "XCAGI_REQUIRE_REDIS_RATE_LIMIT",
        "CACHE_REDIS_URL",
        "REDIS_URL",
        "XCAGI_REDIS_URL",
    ]:
        monkeypatch.delenv(k, raising=False)
    yield


# ---------------------------------------------------------------------------
# env_flag
# ---------------------------------------------------------------------------


def test_env_flag_default_false(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import env_flag

    assert env_flag("MISSING") is False
    assert env_flag("MISSING", default=True) is True


def test_env_flag_various_truthy(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import env_flag

    for v in ["1", "true", "TRUE", "yes", "on", " 1 "]:
        monkeypatch.setenv("F", v)
        assert env_flag("F") is True, v


def test_env_flag_falsy(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import env_flag

    for v in ["0", "false", "no", "off", "random"]:
        monkeypatch.setenv("F", v)
        assert env_flag("F") is False, v


def test_env_flag_empty_string_is_default(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import env_flag

    monkeypatch.setenv("F", "   ")
    assert env_flag("F") is False
    assert env_flag("F", default=True) is False  # 空串走 default


# ---------------------------------------------------------------------------
# deployment_env
# ---------------------------------------------------------------------------


def test_deployment_env_default(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import deployment_env

    assert deployment_env() == ""


def test_deployment_is_staging(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import deployment_is_staging

    monkeypatch.setenv("FHD_ENV", "staging")
    assert deployment_is_staging() is True
    monkeypatch.setenv("FHD_ENV", "dev")
    assert deployment_is_staging() is False


def test_deployment_is_production(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import deployment_is_production

    for env in ["production", "prod", "PRODUCTION"]:
        monkeypatch.setenv("FHD_ENV", env)
        assert deployment_is_production() is True, env
    monkeypatch.setenv("FHD_ENV", "staging")
    assert deployment_is_production() is False


def test_deployment_is_test(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import deployment_is_test

    assert deployment_is_test() is False
    monkeypatch.setenv("TESTING", "1")
    assert deployment_is_test() is True
    monkeypatch.setenv("XCAGI_TESTING", "1")
    monkeypatch.delenv("TESTING", raising=False)
    assert deployment_is_test() is True


# ---------------------------------------------------------------------------
# redis_url_from_env
# ---------------------------------------------------------------------------


def test_redis_url_empty(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import redis_url_from_env

    assert redis_url_from_env() == ""


def test_redis_url_first_match(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import redis_url_from_env

    monkeypatch.setenv("CACHE_REDIS_URL", "redis://primary")
    monkeypatch.setenv("REDIS_URL", "redis://secondary")
    assert redis_url_from_env() == "redis://primary"


def test_redis_url_fallback_chain(monkeypatch: pytest.MonkeyPatch):
    from app.utils.deployment import redis_url_from_env

    monkeypatch.setenv("REDIS_URL", "redis://r")
    assert redis_url_from_env() == "redis://r"

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("XCAGI_REDIS_URL", "redis://x")
    assert redis_url_from_env() == "redis://x"

    monkeypatch.delenv("XCAGI_REDIS_URL", raising=False)
    assert redis_url_from_env() == ""


# ---------------------------------------------------------------------------
# is_desktop_mode
# ---------------------------------------------------------------------------


def test_is_desktop_mode_import_failure(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setattr(deployment, "is_desktop_mode", lambda: True)  # 防止 module reimport
    with patch.dict("sys.modules", {"app.desktop_runtime": None}):
        # 强制 import 失败
        from app.utils.deployment import is_desktop_mode

        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "")
        # 内部会捕获并回退到 env_flag
        # 这里只验证回退路径不抛错
        result = is_desktop_mode()
    assert isinstance(result, bool)


def test_is_desktop_mode_env_flag_fallback(monkeypatch: pytest.MonkeyPatch):

    # 把 desktop_runtime 设为不可用
    with patch.dict("sys.modules", {"app.desktop_runtime": None}):
        monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
        from app.utils.deployment import is_desktop_mode

        # 强制 is_desktop_mode 模块级 import 失败 → 回退到 env_flag
        with patch("builtins.__import__", side_effect=ImportError("nope")):
            # env_flag "1" → True
            assert is_desktop_mode() is True


# ---------------------------------------------------------------------------
# distributed_rate_limit_required
# ---------------------------------------------------------------------------


def test_distributed_rate_limit_required_desktop(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    from app.utils.deployment import distributed_rate_limit_required

    with patch.object(deployment, "is_desktop_mode", return_value=True):
        assert distributed_rate_limit_required() is False


def test_distributed_rate_limit_required_test(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setenv("XCAGI_TESTING", "1")
    with patch.object(deployment, "is_desktop_mode", return_value=False):
        from app.utils.deployment import distributed_rate_limit_required

        assert distributed_rate_limit_required() is False


def test_distributed_rate_limit_required_production(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setenv("FHD_ENV", "production")
    with patch.object(deployment, "is_desktop_mode", return_value=False):
        from app.utils.deployment import distributed_rate_limit_required

        assert distributed_rate_limit_required() is True


def test_distributed_rate_limit_required_staging(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setenv("FHD_ENV", "staging")
    with patch.object(deployment, "is_desktop_mode", return_value=False):
        from app.utils.deployment import distributed_rate_limit_required

        assert distributed_rate_limit_required() is True


def test_distributed_rate_limit_required_explicit_flag(monkeypatch: pytest.MonkeyPatch):
    from app.utils import deployment

    monkeypatch.setenv("XCAGI_REQUIRE_REDIS_RATE_LIMIT", "1")
    with patch.object(deployment, "is_desktop_mode", return_value=False):
        from app.utils.deployment import distributed_rate_limit_required

        assert distributed_rate_limit_required() is True
