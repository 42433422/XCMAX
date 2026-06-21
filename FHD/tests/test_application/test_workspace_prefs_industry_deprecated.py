"""workspace_prefs.selected_industry_id 废弃测试（Task 8）。

验证：
- save_selected_industry 为 no-op + DeprecationWarning，返回空 dict
- save_selected_industry 不再写入存储
- get_selected_industry_id 保留原逻辑（兼容历史数据）
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from app.application import tenant_workspace_prefs as prefs


class TestSaveSelectedIndustryDeprecated:
    """验证 save_selected_industry 已变为 no-op。"""

    def test_returns_empty_dict(self):
        """save_selected_industry 返回空 dict。"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = prefs.save_selected_industry("tenant:1", "涂料")
        assert result == {}

    def test_emits_deprecation_warning(self):
        """save_selected_industry 发出 DeprecationWarning。"""
        with pytest.warns(DeprecationWarning):
            prefs.save_selected_industry("tenant:1", "电商")

    def test_does_not_write_to_storage(self):
        """save_selected_industry 不再调用 patch_workspace_prefs 写入存储。"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with patch(
                "app.application.tenant_workspace_prefs.patch_workspace_prefs"
            ) as mock_patch:
                prefs.save_selected_industry(
                    "tenant:1", "涂料", industry_mod_id="mod-coating"
                )
        # 不应调用 patch_workspace_prefs
        mock_patch.assert_not_called()

    def test_does_not_call_save_workspace_prefs(self):
        """save_selected_industry 不应触发底层 _save_workspace_prefs。"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with patch(
                "app.application.tenant_workspace_prefs._save_workspace_prefs"
            ) as mock_save:
                prefs.save_selected_industry("session:1", "餐饮")
        mock_save.assert_not_called()


class TestGetSelectedIndustryIdBackwardCompat:
    """验证 get_selected_industry_id 保留原逻辑（兼容历史数据）。"""

    def test_returns_none_when_no_owner(self):
        """无 owner_id 时返回 None。"""
        assert prefs.get_selected_industry_id(None) is None
        assert prefs.get_selected_industry_id("") is None

    def test_returns_saved_value_from_prefs(self):
        """有历史数据时返回保存的 industry_id。"""
        with patch(
            "app.application.tenant_workspace_prefs.get_workspace_prefs",
            return_value={"selected_industry_id": "涂料"},
        ):
            assert prefs.get_selected_industry_id("tenant:1") == "涂料"

    def test_returns_none_when_no_saved_value(self):
        """无历史数据时返回 None。"""
        with patch(
            "app.application.tenant_workspace_prefs.get_workspace_prefs",
            return_value={},
        ):
            assert prefs.get_selected_industry_id("tenant:1") is None

    def test_returns_none_when_saved_value_empty(self):
        """保存值为空字符串时返回 None。"""
        with patch(
            "app.application.tenant_workspace_prefs.get_workspace_prefs",
            return_value={"selected_industry_id": "  "},
        ):
            assert prefs.get_selected_industry_id("tenant:1") is None
