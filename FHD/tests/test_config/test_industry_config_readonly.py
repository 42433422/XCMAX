"""industry_config 只读化测试（Task 6）。

验证：
- set_current_industry 为 no-op + DeprecationWarning，返回 True
- get_current_industry 优先从请求上下文读取
- 无请求上下文时回退到原逻辑
"""

from __future__ import annotations

import warnings
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from resources.config import industry_config


class TestSetCurrentIndustryReadOnly:
    """验证 set_current_industry 已变为 no-op。"""

    def test_returns_true(self):
        """set_current_industry 始终返回 True（向后兼容）。"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert industry_config.set_current_industry("涂料") is True

    def test_emits_deprecation_warning(self):
        """set_current_industry 发出 DeprecationWarning。"""
        with pytest.warns(DeprecationWarning):
            industry_config.set_current_industry("电商")

    def test_does_not_mutate_runtime_state(self):
        """set_current_industry 不再修改运行时 default_industry。"""
        config_before = industry_config._load_config()
        default_before = config_before.get("default_industry")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            industry_config.set_current_industry("餐饮")

        # 强制重新加载以验证未被修改
        industry_config.reload_industry_config()
        config_after = industry_config._load_config()
        default_after = config_after.get("default_industry")
        assert default_after == default_before


class TestGetCurrentIndustryFromRequestContext:
    """验证 get_current_industry 优先从请求上下文读取。"""

    def test_reads_from_request_state(self):
        """有请求上下文时，读取 request.state.industry_id。"""
        fake_request = SimpleNamespace(state=SimpleNamespace(industry_id="电商"))
        with patch(
            "app.infrastructure.request_context.get_current_request",
            return_value=fake_request,
        ):
            assert industry_config.get_current_industry() == "电商"

    def test_falls_back_when_no_request(self):
        """无请求上下文时，回退到原逻辑（YAML/Mod 默认）。"""
        with patch(
            "app.infrastructure.request_context.get_current_request",
            return_value=None,
        ):
            result = industry_config.get_current_industry()
            # 应回退到某个有效行业 id（涂料或 Mod 声明的行业）
            assert isinstance(result, str)
            assert len(result) > 0

    def test_falls_back_when_request_state_empty(self):
        """请求上下文存在但 industry_id 为空时，回退到原逻辑。"""
        fake_request = SimpleNamespace(state=SimpleNamespace(industry_id=None))
        with patch(
            "app.infrastructure.request_context.get_current_request",
            return_value=fake_request,
        ):
            result = industry_config.get_current_industry()
            assert isinstance(result, str)
            assert len(result) > 0
