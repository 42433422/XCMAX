# 成都修茈科技有限公司/MODstore_deploy/tests/test_auto_approve_policy_categories.py
"""auto_approve_policy 三类决策路径单元测试（auto / require_human / deny）。

覆盖目标（与 T-C06 spec 对齐）：
- auto (low risk): 自动批准路径
- require_human (medium risk): 强制人工审批路径
- deny (high risk): 拒绝路径

每个分类覆盖所有进入该分类的分支条件，确保风险评级无歧义。
同时覆盖 env-var 解析、路径匹配、行数统计等辅助函数。
"""

from __future__ import annotations

import pytest

from modstore_server.auto_approve_policy import (
    _auto_approve_enabled,
    _catalog_files_root,
    _count_diff_lines,
    _max_lines,
    _path_is_high_risk,
    _path_matches_any,
    _path_requires_manual_approval,
    _require_ci,
    classify_change_risk,
)

# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #


class TestAutoApproveEnabled:
    """_auto_approve_enabled env-var 解析。"""

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "Yes", "on", "ON"])
    def test_truthy_values_enable_auto_approve(self, monkeypatch, val):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_ENABLED", val)
        assert _auto_approve_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "random"])
    def test_falsy_values_disable_auto_approve(self, monkeypatch, val):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_ENABLED", val)
        assert _auto_approve_enabled() is False

    def test_default_is_enabled_when_unset(self, monkeypatch):
        """默认值 "1" → enabled。"""
        monkeypatch.delenv("MODSTORE_AUTO_APPROVE_ENABLED", raising=False)
        assert _auto_approve_enabled() is True

    def test_whitespace_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_ENABLED", "  true  ")
        assert _auto_approve_enabled() is True


class TestMaxLines:
    """_max_lines env-var 解析。"""

    def test_default_50_when_unset(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_AUTO_APPROVE_MAX_LINES", raising=False)
        assert _max_lines() == 50

    @pytest.mark.parametrize("val,expected", [("1", 1), ("100", 100), ("0", 0)])
    def test_valid_int_values(self, monkeypatch, val, expected):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", val)
        assert _max_lines() == expected

    @pytest.mark.parametrize("val", ["abc", "", "1.5", "null", "---"])
    def test_invalid_value_falls_back_to_50(self, monkeypatch, val):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", val)
        assert _max_lines() == 50


class TestRequireCi:
    """_require_ci env-var 解析。"""

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
    def test_truthy_values_require_ci(self, monkeypatch, val):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_REQUIRE_CI", val)
        assert _require_ci() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsy_values_skip_ci(self, monkeypatch, val):
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_REQUIRE_CI", val)
        assert _require_ci() is False

    def test_default_is_required_when_unset(self, monkeypatch):
        """默认值 "1" → require CI。"""
        monkeypatch.delenv("MODSTORE_AUTO_APPROVE_REQUIRE_CI", raising=False)
        assert _require_ci() is True


class TestPathMatchesAny:
    """_path_matches_any 路径匹配。"""

    def test_empty_patterns_returns_false(self):
        assert _path_matches_any("any/path.py", []) is False
        assert _path_matches_any("any/path.py", ()) is False

    def test_empty_pattern_skipped(self):
        """空字符串/空白 pattern 跳过。"""
        assert _path_matches_any("foo.py", ["", "  ", "foo.py"]) is True

    def test_case_insensitive_match(self):
        assert _path_matches_any("Foo.PY", ["foo.py"]) is True
        assert _path_matches_any("FOO/PY", ["foo/py"]) is True

    def test_backslash_normalized_to_slash(self):
        """Windows 风格路径归一化为 /。"""
        assert _path_matches_any("secrets\\foo.py", ["secrets/*"]) is True

    def test_double_star_prefix_also_tried(self):
        """未命中时尝试 **/<pattern> 前缀。"""
        assert _path_matches_any("nested/deep/secrets/foo.py", ["secrets/*"]) is True

    def test_no_match_returns_false(self):
        assert _path_matches_any("safe/foo.py", ["secrets/*"]) is False


class TestPathIsHighRisk:
    """_path_is_high_risk 高风险路径判定。"""

    @pytest.mark.parametrize(
        "suffix",
        [".env", ".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"],
    )
    def test_high_risk_suffixes(self, suffix):
        assert _path_is_high_risk(f"config/creds{suffix}") is True

    @pytest.mark.parametrize(
        "path",
        [
            "prod.env",
            "prod.env.local",
            "secrets/api.pem",
            ".github/workflows/evil.yml",
            "nginx/site.conf",
            "deploy/nginx.conf",
            "requirements.txt",
            "requirements-prod.txt",
            "Dockerfile",
            "Dockerfile.prod",
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "modstore_server/models.py",
            "modstore_server/models_extra.py",
            "modstore_server/api/app_factory.py",
        ],
    )
    def test_high_risk_builtin_patterns(self, path):
        assert _path_is_high_risk(path) is True

    def test_forbidden_globs_force_high_risk(self):
        """forbidden_globs 命中 → 高风险（即便内置规则不命中）。"""
        assert (
            _path_is_high_risk(
                "modstore_server/services/llm.py",
                forbidden_globs=["modstore_server/services/*"],
            )
            is True
        )

    def test_safe_path_returns_false(self):
        assert _path_is_high_risk("modstore_server/services/foo.py") is False

    def test_case_insensitive(self):
        """路径与 pattern 都转小写比较。"""
        assert _path_is_high_risk("SECRETS/foo.PEM") is True


class TestPathRequiresManualApproval:
    """_path_requires_manual_approval approval_required_globs 判定。"""

    def test_match_returns_true(self):
        assert (
            _path_requires_manual_approval(
                "modstore_server/services/llm.py",
                approval_required_globs=["modstore_server/services/llm*"],
            )
            is True
        )

    def test_no_match_returns_false(self):
        assert (
            _path_requires_manual_approval(
                "modstore_server/services/foo.py",
                approval_required_globs=["modstore_server/services/llm*"],
            )
            is False
        )

    def test_empty_globs_returns_false(self):
        assert _path_requires_manual_approval("any/path.py", approval_required_globs=[]) is False


class TestCountDiffLines:
    """_count_diff_lines 行数统计。"""

    def test_without_original_counts_content_lines(self):
        assert _count_diff_lines("a\nb\nc\n") == 3

    def test_without_original_empty_content(self):
        assert _count_diff_lines("") == 0

    def test_without_original_none_content(self):
        assert _count_diff_lines("", None) == 0

    def test_with_original_counts_only_changed_lines(self):
        original = "a\nb\nc"
        content = "a\nb\nX\nd"
        # c → X (changed), d (new) = 2 changed lines
        assert _count_diff_lines(content, original) == 2

    def test_with_original_identical_returns_zero(self):
        original = "a\nb\nc"
        assert _count_diff_lines(original, original) == 0

    def test_with_original_empty_both(self):
        assert _count_diff_lines("", "") == 0


class TestCatalogFilesRoot:
    """_catalog_files_root env-var 解析。"""

    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_CATALOG_FILES_ROOT", raising=False)
        assert _catalog_files_root() is None

    def test_set_returns_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MODSTORE_CATALOG_FILES_ROOT", str(tmp_path))
        result = _catalog_files_root()
        assert result is not None
        assert str(result) == str(tmp_path)


# --------------------------------------------------------------------------- #
# 三类决策路径：deny (high risk)
# --------------------------------------------------------------------------- #


class TestDenyHighRiskCategory:
    """classify_change_risk 返回 ("high", ...) 的所有路径。"""

    @pytest.mark.parametrize(
        "path",
        [
            "config/prod.env",
            "secrets/api.pem",
            "data/app.db",
            "data/app.sqlite3",
        ],
    )
    def test_high_risk_suffix_paths(self, path):
        risk, reason = classify_change_risk(path, "x = 1\n")
        assert risk == "high"
        assert "高风险" in reason or "forbidden" in reason

    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/ci.yml",
            "nginx/site.conf",
            "deploy/nginx.conf",
            "Dockerfile",
            "docker-compose.yml",
            "modstore_server/models.py",
            "modstore_server/api/app_factory.py",
        ],
    )
    def test_high_risk_builtin_pattern_paths(self, path):
        risk, _ = classify_change_risk(path, "x = 1\n")
        assert risk == "high"

    def test_forbidden_globs_paths(self):
        """forbidden_globs 命中 → high（即便不在内置高风险列表）。"""
        risk, reason = classify_change_risk(
            "modstore_server/services/llm.py",
            "x = 1\n",
            forbidden_globs=["modstore_server/services/*"],
        )
        assert risk == "high"
        assert "forbidden" in reason or "高风险" in reason

    def test_forbidden_glob_overrides_scope_match(self):
        """即便路径在 scope_globs 内，forbidden_globs 仍优先 → high。"""
        risk, _ = classify_change_risk(
            "modstore_server/services/llm.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],
            forbidden_globs=["modstore_server/services/llm*"],
        )
        assert risk == "high"

    def test_line_count_exceeds_4x_threshold(self, monkeypatch):
        """行数 > max_l * 4 → high。"""
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "5")
        big = "\n".join(f"line {i}" for i in range(40))  # 40 > 5*4=20
        risk, reason = classify_change_risk(
            "modstore_server/services/dummy.py",
            big,
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "high"
        assert "高风险" in reason

    def test_line_count_exactly_4x_threshold_not_high(self, monkeypatch):
        """行数 = max_l * 4 不触发 high（严格 >），落 medium。"""
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "5")
        # 5*4 = 20 行，正好等于阈值，不超 → medium
        content = "\n".join(f"line {i}" for i in range(20))
        risk, _ = classify_change_risk(
            "modstore_server/services/dummy.py",
            content,
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "medium"


# --------------------------------------------------------------------------- #
# 三类决策路径：require_human (medium risk)
# --------------------------------------------------------------------------- #


class TestRequireHumanMediumRiskCategory:
    """classify_change_risk 返回 ("medium", ...) 的所有路径。"""

    def test_approval_required_globs_match(self):
        """approval_required_globs 命中 → medium（强制人工）。"""
        risk, reason = classify_change_risk(
            "modstore_server/services/llm.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],
            approval_required_globs=["modstore_server/services/llm*"],
        )
        assert risk == "medium"
        assert "approval_required_globs" in reason or "人工审批" in reason

    def test_approval_required_globs_overrides_low_risk(self):
        """即便行数少、在 scope 内，approval_required_globs 仍强制 medium。"""
        risk, _ = classify_change_risk(
            "modstore_server/services/llm.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],
            approval_required_globs=["modstore_server/services/llm*"],
        )
        assert risk == "medium"

    def test_scope_globs_mismatch(self):
        """路径不在 scope_globs 范围内 → medium。"""
        risk, reason = classify_change_risk(
            "modstore_server/playground/foo.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "medium"
        assert "scope" in reason

    def test_line_count_exceeds_max_lines(self, monkeypatch):
        """行数 > max_l 但 ≤ max_l*4 → medium。"""
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "5")
        # 6 行 > 5 但 ≤ 20 → medium
        content = "\n".join(f"line {i}" for i in range(6))
        risk, reason = classify_change_risk(
            "modstore_server/services/dummy.py",
            content,
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "medium"
        assert "变更行数" in reason

    def test_line_count_just_above_max_lines(self, monkeypatch):
        """行数 = max_l + 1 → medium。"""
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "50")
        content = "\n".join(f"line {i}" for i in range(51))
        risk, _ = classify_change_risk(
            "modstore_server/services/dummy.py",
            content,
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "medium"

    def test_marker_status_path_with_executable_requirement(self, monkeypatch, tmp_path):
        """self_maintenance marker 路径 + loop_memory 要求 executable change → medium。"""
        marker_path = "self_maintenance_loop_status.py"

        # Force the policy check to return required=True
        import modstore_server.self_maintenance_policy as smp

        monkeypatch.setattr(smp, "is_marker_status_path", lambda p: p == marker_path)
        monkeypatch.setattr(
            smp,
            "loop_memory_requires_executable_change",
            lambda: {"required": True, "reason": "loop_not_completed"},
        )

        risk, reason = classify_change_risk(marker_path, "STATUS='idle'\n")
        assert risk == "medium"
        assert "marker-only" in reason or "self-maintenance" in reason

    def test_marker_status_path_policy_check_failed_closed(self, monkeypatch):
        """self_maintenance_policy import 失败 → fail closed → medium。"""
        marker_path = "self_maintenance_loop_status.py"

        # Make the import inside classify_change_risk raise
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "modstore_server.self_maintenance_policy":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        risk, reason = classify_change_risk(marker_path, "STATUS='idle'\n")
        assert risk == "medium"
        assert "fail closed" in reason or "policy" in reason


# --------------------------------------------------------------------------- #
# 三类决策路径：auto (low risk)
# --------------------------------------------------------------------------- #


class TestAutoLowRiskCategory:
    """classify_change_risk 返回 ("low", ...) 的所有路径。"""

    def test_low_when_inside_scope_and_short(self):
        risk, reason = classify_change_risk(
            "modstore_server/services/dummy.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "low"
        assert "scope" in reason or "≤" in reason

    def test_low_when_scope_globs_empty(self):
        """scope_globs 为空 → 不做 scope 检查，行数 ≤ max → low。"""
        risk, _ = classify_change_risk(
            "any/path/foo.py",
            "x = 1\n",
            scope_globs=[],
        )
        assert risk == "low"

    def test_low_when_scope_globs_not_provided(self):
        """scope_globs 默认 () → 不做 scope 检查 → low。"""
        risk, _ = classify_change_risk(
            "any/path/foo.py",
            "x = 1\n",
        )
        assert risk == "low"

    def test_low_at_exactly_max_lines(self, monkeypatch):
        """行数 = max_l 仍为 low（严格 >）。"""
        monkeypatch.setenv("MODSTORE_AUTO_APPROVE_MAX_LINES", "5")
        content = "\n".join(f"line {i}" for i in range(5))
        risk, _ = classify_change_risk(
            "modstore_server/services/dummy.py",
            content,
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "low"

    def test_low_with_original_content_unchanged(self):
        """original_content 完全相同 → diff 行数 = 0 → low。"""
        original = "x = 1\ny = 2\n"
        risk, _ = classify_change_risk(
            "modstore_server/services/dummy.py",
            original,
            scope_globs=["modstore_server/services/*"],
            original_content=original,
        )
        assert risk == "low"

    def test_low_with_multiple_scope_globs_any_match(self):
        """scope_globs 多个 pattern，任一命中即可 → low。"""
        risk, _ = classify_change_risk(
            "modstore_server/api/foo.py",
            "x = 1\n",
            scope_globs=[
                "modstore_server/services/*",
                "modstore_server/api/*",
            ],
        )
        assert risk == "low"

    def test_low_reason_includes_line_count_and_threshold(self):
        """reason 字符串包含行数与阈值信息（便于审计）。"""
        risk, reason = classify_change_risk(
            "modstore_server/services/dummy.py",
            "x = 1\ny = 2\n",
            scope_globs=["modstore_server/services/*"],
        )
        assert risk == "low"
        # reason 形如 "变更行数 2 ≤ 50，路径在 scope 内"
        assert "2" in reason
        assert "50" in reason


# --------------------------------------------------------------------------- #
# 边界场景：分类优先级
# --------------------------------------------------------------------------- #


class TestCategoryPriority:
    """分类判定优先级：high > medium(approval_required) > medium(marker) > medium(scope/lines) > low。"""

    def test_high_risk_suffix_overrides_approval_required_globs(self):
        """高风险后缀（如 .env）优先于 approval_required_globs。"""
        risk, _ = classify_change_risk(
            "config/prod.env",
            "TOKEN=xxx\n",
            approval_required_globs=["config/prod.env"],
        )
        assert risk == "high"

    def test_high_risk_pattern_overrides_scope_mismatch(self):
        """高风险 pattern（如 Dockerfile）优先于 scope_globs 不匹配。"""
        risk, _ = classify_change_risk(
            "Dockerfile",
            "FROM python:3.11\n",
            scope_globs=["modstore_server/services/*"],  # 不匹配
        )
        assert risk == "high"

    def test_approval_required_globs_overrides_scope_mismatch(self):
        """approval_required_globs 命中（medium）即便 scope 不匹配仍是 medium。"""
        risk, _ = classify_change_risk(
            "modstore_server/playground/llm.py",
            "x = 1\n",
            scope_globs=["modstore_server/services/*"],  # 不匹配
            approval_required_globs=["modstore_server/playground/llm*"],
        )
        # approval_required_globs 优先于 scope_globs 检查
        assert risk == "medium"
