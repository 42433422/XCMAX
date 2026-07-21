"""test_cross_tier_gate.py — 跨端门禁纯函数测试。

覆盖 3 个跨端场景 + 查询失败 fail-open + 无匹配默认 allow。
"""

from __future__ import annotations

import pytest

from scripts.autonomy.cross_tier_gate import GateResult, check_before_action, is_enabled


class TestFailOpen:
    """跨端查询失败默认 allow=True（fail-open，不阻断主流程）。"""

    def test_remote_state_none_returns_allow(self):
        result = check_before_action("desktop", "rollback_version", None)
        assert result.allow is True
        assert "fail-open" in result.reasons[0]

    def test_remote_state_none_server_tier(self):
        result = check_before_action("server", "rollback_to_last_tarball", None)
        assert result.allow is True

    def test_remote_state_none_ci_tier(self):
        result = check_before_action("ci", "cvm-push-release", None)
        assert result.allow is True


class TestEmptyState:
    """空 state 默认 allow。"""

    def test_empty_dict_returns_allow(self):
        result = check_before_action("desktop", "rollback_version", {})
        assert result.allow is True
        assert result.reasons == []


class TestDesktopRollbackVersion:
    """桌面端 rollback_version 前检查服务器端 manifest 是否 frozen。"""

    def test_allow_when_manifest_not_frozen(self):
        result = check_before_action(
            "desktop", "rollback_version", {"server_manifest_frozen": False}
        )
        assert result.allow is True

    def test_deny_when_manifest_frozen(self):
        result = check_before_action(
            "desktop", "rollback_version", {"server_manifest_frozen": True}
        )
        assert result.allow is False
        assert any("冻结" in r for r in result.reasons)

    def test_allow_when_key_missing(self):
        # key 缺失默认 False，故 allow
        result = check_before_action("desktop", "rollback_version", {"other_key": 123})
        assert result.allow is True


class TestServerRollbackTarball:
    """服务器端 rollback_to_last_tarball 前检查桌面端 pending rollback marker。"""

    def test_allow_when_no_pending_marker(self):
        result = check_before_action(
            "server", "rollback_to_last_tarball", {"desktop_pending_rollback_marker": False}
        )
        assert result.allow is True

    def test_deny_when_pending_marker_exists(self):
        result = check_before_action(
            "server", "rollback_to_last_tarball", {"desktop_pending_rollback_marker": True}
        )
        assert result.allow is False
        assert any("嵌套回滚" in r for r in result.reasons)


class TestCiPushRelease:
    """CI cvm-push-release 前检查服务器端 manifest 是否 frozen。"""

    def test_allow_when_manifest_not_frozen(self):
        result = check_before_action("ci", "cvm-push-release", {"server_manifest_frozen": False})
        assert result.allow is True

    def test_deny_when_manifest_frozen(self):
        result = check_before_action("ci", "cvm-push-release", {"server_manifest_frozen": True})
        assert result.allow is False
        assert any("冻结" in r for r in result.reasons)


class TestUnmatchedAction:
    """未匹配的动作默认 allow。"""

    def test_unknown_action_type_allow(self):
        result = check_before_action(
            "desktop", "some_unknown_action", {"server_manifest_frozen": True}
        )
        assert result.allow is True

    def test_unknown_tier_allow(self):
        # tier 字面量类型限制，但运行时传入未匹配的 tier 也应 allow
        result = check_before_action("desktop", "restart_backend", {"server_manifest_frozen": True})
        assert result.allow is True


class TestIsEnabled:
    """env XCAGI_CROSS_TIER_GATE 检查（默认启用，opt-out）。"""

    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_CROSS_TIER_GATE", raising=False)
        assert is_enabled() is True

    def test_enabled_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "")
        assert is_enabled() is True

    def test_enabled_when_env_is_1(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "1")
        assert is_enabled() is True

    def test_enabled_when_env_is_true(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "true")
        assert is_enabled() is True

    def test_enabled_when_env_is_yes(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "yes")
        assert is_enabled() is True

    def test_enabled_when_env_is_true_uppercase(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "TRUE")
        assert is_enabled() is True

    def test_disabled_when_env_is_0(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "0")
        assert is_enabled() is False

    def test_disabled_when_env_is_false(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "false")
        assert is_enabled() is False

    def test_disabled_when_env_is_no(self, monkeypatch):
        monkeypatch.setenv("XCAGI_CROSS_TIER_GATE", "no")
        assert is_enabled() is False


class TestGateResult:
    """GateResult dataclass 基础测试。"""

    def test_default_reasons_empty(self):
        r = GateResult(allow=True)
        assert r.reasons == []

    def test_with_reasons(self):
        r = GateResult(allow=False, reasons=["a", "b"])
        assert r.reasons == ["a", "b"]
