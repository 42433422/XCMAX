"""测试 sidebar_menu_manager 模块 - 侧边栏菜单管理。"""

from __future__ import annotations

import importlib
import os
import tempfile
from unittest.mock import patch

import pytest

# The module uses a hyphen in directory name, so we need importlib
_MODULE_PATH = os.path.join(
    os.path.dirname(__file__),  # tests/test_infrastructure/
    "..", "..",  # FHD/
    "app", "infrastructure", "skills", "sidebar-menu-manager", "sidebar_menu_manager.py",
)
spec = importlib.util.spec_from_file_location(
    "sidebar_menu_manager",
    os.path.abspath(_MODULE_PATH),
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)

add_menu_item = _mod.add_menu_item
find_menu_items_block = _mod.find_menu_items_block
get_menu_items = _mod.get_menu_items
get_sidebar_component_path = _mod.get_sidebar_component_path
get_sidebar_info = _mod.get_sidebar_info
get_sidebar_menu_manager_skill = _mod.get_sidebar_menu_manager_skill
remove_menu_item = _mod.remove_menu_item
reorder_menu_items = _mod.reorder_menu_items
update_menu_item = _mod.update_menu_item


SAMPLE_SIDEBAR = """<template>
  <div class="sidebar">
    <div v-for="item in menuItems" :key="item.key">
      {{ item.name }}
    </div>
  </div>
</template>

<script setup>
const menuItems = [
  { key: 'dashboard', name: '仪表盘', icon: '📊' },
  { key: 'products', name: '产品管理', icon: '📦' },
  { key: 'customers', name: '客户管理', icon: '👥' },
]
</script>
"""


@pytest.fixture
def sidebar_file(tmp_path):
    """创建临时 Sidebar.vue 文件。"""
    frontend_dir = tmp_path / "frontend" / "src" / "components"
    frontend_dir.mkdir(parents=True)
    sidebar_path = frontend_dir / "Sidebar.vue"
    sidebar_path.write_text(SAMPLE_SIDEBAR, encoding="utf-8")
    return str(sidebar_path)


@pytest.fixture(autouse=True)
def _patch_base_dir(tmp_path):
    """重定向 get_base_dir 到临时目录。"""
    original = _mod.get_base_dir
    _mod.get_base_dir = lambda: str(tmp_path)
    yield
    _mod.get_base_dir = original


class TestGetSidebarComponentPath:
    """测试 get_sidebar_component_path 函数。"""

    def test_returns_expected_path(self, tmp_path):
        path = get_sidebar_component_path()
        assert "Sidebar.vue" in path
        assert "components" in path


class TestGetMenuItems:
    """测试 get_menu_items 函数。"""

    def test_parses_menu_items(self, sidebar_file):
        items = get_menu_items()
        assert len(items) == 3
        assert items[0]["key"] == "dashboard"
        assert items[0]["name"] == "仪表盘"
        assert items[0]["icon"] == "📊"

    def test_nonexistent_file_returns_empty(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            items = get_menu_items()
            assert items == []


class TestFindMenuItemsBlock:
    """测试 find_menu_items_block 函数。"""

    def test_finds_block(self):
        result = find_menu_items_block(SAMPLE_SIDEBAR)
        assert result is not None
        assert "const menuItems" in result
        assert "dashboard" in result

    def test_no_block_returns_none(self):
        content = "no menu items here"
        result = find_menu_items_block(content)
        assert result is None


class TestAddMenuItem:
    """测试 add_menu_item 函数。"""

    def test_add_new_item(self, sidebar_file):
        result = add_menu_item("settings", "设置", "⚙️")
        assert result["success"] is True
        assert "设置" in result["message"]

        items = get_menu_items()
        keys = [i["key"] for i in items]
        assert "settings" in keys

    def test_add_duplicate_returns_failure(self, sidebar_file):
        result = add_menu_item("dashboard", "仪表盘", "📊")
        assert result["success"] is False
        assert "already exists" in result["message"]

    def test_add_to_nonexistent_file(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            result = add_menu_item("test", "测试", "📌")
            assert result["success"] is False


class TestRemoveMenuItem:
    """测试 remove_menu_item 函数。"""

    def test_remove_existing_item(self, sidebar_file):
        result = remove_menu_item("products")
        assert result["success"] is True

        items = get_menu_items()
        keys = [i["key"] for i in items]
        assert "products" not in keys

    def test_remove_nonexistent_item(self, sidebar_file):
        result = remove_menu_item("nonexistent")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_remove_from_nonexistent_file(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            result = remove_menu_item("test")
            assert result["success"] is False


class TestUpdateMenuItem:
    """测试 update_menu_item 函数。"""

    def test_update_name(self, sidebar_file):
        result = update_menu_item("dashboard", name="控制台")
        assert result["success"] is True

        items = get_menu_items()
        dashboard = next(i for i in items if i["key"] == "dashboard")
        assert dashboard["name"] == "控制台"

    def test_update_icon(self, sidebar_file):
        result = update_menu_item("dashboard", icon="🏠")
        assert result["success"] is True

        items = get_menu_items()
        dashboard = next(i for i in items if i["key"] == "dashboard")
        assert dashboard["icon"] == "🏠"

    def test_update_nonexistent_item(self, sidebar_file):
        result = update_menu_item("nonexistent", name="测试")
        assert result["success"] is False

    def test_update_nonexistent_file(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            result = update_menu_item("test", name="测试")
            assert result["success"] is False


class TestReorderMenuItems:
    """测试 reorder_menu_items 函数。"""

    def test_reorder_item(self, sidebar_file):
        result = reorder_menu_items("customers", 0)
        assert result["success"] is True

        items = get_menu_items()
        assert items[0]["key"] == "customers"

    def test_same_position(self, sidebar_file):
        result = reorder_menu_items("dashboard", 0)
        assert result["success"] is True
        assert "already at position" in result["message"]

    def test_invalid_index(self, sidebar_file):
        result = reorder_menu_items("dashboard", 100)
        assert result["success"] is False
        assert "Invalid" in result["message"]

    def test_negative_index(self, sidebar_file):
        result = reorder_menu_items("dashboard", -1)
        assert result["success"] is False

    def test_nonexistent_key(self, sidebar_file):
        result = reorder_menu_items("nonexistent", 0)
        assert result["success"] is False

    def test_nonexistent_file(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            result = reorder_menu_items("test", 0)
            assert result["success"] is False


class TestGetSidebarInfo:
    """测试 get_sidebar_info 函数。"""

    def test_returns_info(self, sidebar_file):
        info = get_sidebar_info()
        assert "path" in info
        assert "exists" in info
        assert "item_count" in info
        assert "menu_items" in info
        assert info["item_count"] == 3

    def test_nonexistent_file(self, tmp_path):
        with patch.object(
            _mod,
            "get_sidebar_component_path",
            return_value=str(tmp_path / "nonexistent.vue"),
        ):
            info = get_sidebar_info()
            assert info["exists"] is False
            assert info["item_count"] == 0


class TestGetSidebarMenuManagerSkill:
    """测试 get_sidebar_menu_manager_skill 函数。"""

    def test_returns_skill_dict(self):
        skill = get_sidebar_menu_manager_skill()
        assert skill["name"] == "sidebar-menu-manager"
        assert "functions" in skill
        assert "get_menu_items" in skill["functions"]
        assert "add_menu_item" in skill["functions"]
        assert "remove_menu_item" in skill["functions"]
