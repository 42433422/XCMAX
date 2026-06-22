"""value_objects_industry 只读化测试（Task 5）。

验证：
- set_current_industry 已移除
- get_current_industry 优先从请求上下文读取
- 无请求上下文时回退到 industry_config
- get_current_industry_config / get_current_industry_fields 按需加载
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.domain import value_objects_industry as voi


class TestReadOnlyModuleState:
    """验证模块级可变状态已移除。"""

    def test_set_current_industry_removed(self):
        """set_current_industry 函数应已不存在。"""
        assert not hasattr(voi, "set_current_industry")

    def test_no_module_level_current_industry_var(self):
        """_current_industry 模块级变量应已不存在。"""
        assert not hasattr(voi, "_current_industry")

    def test_no_cache_variables(self):
        """缓存变量应已不存在。"""
        assert not hasattr(voi, "_industry_units_cache")
        assert not hasattr(voi, "_industry_fields_cache")

    def test_register_industry_units_removed(self):
        """register_industry_units 应已不存在。"""
        assert not hasattr(voi, "register_industry_units")


class TestGetCurrentIndustryFromRequestContext:
    """验证 get_current_industry 优先从请求上下文读取。"""

    def test_reads_from_request_state(self):
        """有请求上下文时，读取 request.state.industry_id。"""
        fake_request = SimpleNamespace(state=SimpleNamespace(industry_id="电商"))
        with patch(
            "app.infrastructure.request_context.get_current_request",
            return_value=fake_request,
        ):
            assert voi.get_current_industry() == "电商"

    def test_falls_back_to_industry_config_when_no_request(self):
        """无请求上下文时，回退到 industry_config.get_current_industry()。"""
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=None,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                return_value="涂料",
            ),
        ):
            assert voi.get_current_industry() == "涂料"

    def test_falls_back_when_request_state_empty(self):
        """请求上下文存在但 industry_id 为空时，回退到 industry_config。"""
        fake_request = SimpleNamespace(state=SimpleNamespace(industry_id=None))
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=fake_request,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                return_value="涂料",
            ),
        ):
            assert voi.get_current_industry() == "涂料"


class TestOnDemandLoading:
    """验证 get_current_industry_config / get_current_industry_fields 按需加载。"""

    def test_get_current_industry_config_loads_from_profile(self):
        """get_current_industry_config 从 industry_config.get_industry_profile 按需加载。"""
        fake_profile = SimpleNamespace(
            units={"primary": "件", "secondary": "箱"},
            quantity_fields={"primary_field": "pieces"},
        )
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=None,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                return_value="电商",
            ),
            patch(
                "resources.config.industry_config.get_industry_profile",
                return_value=fake_profile,
            ),
        ):
            config = voi.get_current_industry_config()
            assert config == {"primary": "件", "secondary": "箱"}

    def test_get_current_industry_fields_loads_from_profile(self):
        """get_current_industry_fields 从 industry_config.get_industry_profile 按需加载。"""
        fake_profile = SimpleNamespace(
            units={},
            quantity_fields={"primary_field": "pieces", "secondary_field": "cartons"},
        )
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=None,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                return_value="电商",
            ),
            patch(
                "resources.config.industry_config.get_industry_profile",
                return_value=fake_profile,
            ),
        ):
            fields = voi.get_current_industry_fields()
            assert fields == {"primary_field": "pieces", "secondary_field": "cartons"}

    def test_get_current_industry_config_fallback_on_error(self):
        """行业档案加载异常时回退到内置默认单位（get_industry_profile 抛错路径）。"""
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=None,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "resources.config.industry_config.get_industry_profile",
                side_effect=RuntimeError("boom"),
            ),
        ):
            config = voi.get_current_industry_config()
            assert config["primary"] == "桶"
            assert config["primary_field"] == "tins"


class TestFieldHelpers:
    """验证字段名辅助函数正常工作。"""

    def test_get_primary_field_name(self):
        """get_primary_field_name 返回当前行业的 primary_field。"""
        fake_profile = SimpleNamespace(
            units={},
            quantity_fields={
                "primary_field": "pieces",
                "secondary_field": "cartons",
                "spec_field": "spec_per_box",
            },
        )
        with (
            patch(
                "app.infrastructure.request_context.get_current_request",
                return_value=None,
            ),
            patch(
                "resources.config.industry_config.get_current_industry",
                return_value="电商",
            ),
            patch(
                "resources.config.industry_config.get_industry_profile",
                return_value=fake_profile,
            ),
        ):
            assert voi.get_primary_field_name() == "pieces"
            assert voi.get_secondary_field_name() == "cartons"
            assert voi.get_spec_field_name() == "spec_per_box"
