"""Tests for app.application.tools.rbac_tools.

覆盖 create_role / assign_role / list_roles 三个核心执行器。Mock RbacAppService。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.tools import rbac_tools


class TestCreateRole:
    """create_role 执行器测试套件。"""

    def test_create_role_without_confirm_returns_needs_confirm(self):
        """未传 confirm=true 时应拒绝执行。"""
        result = rbac_tools.create_role(
            {"name": "manager", "permissions": ["admin.manage_users"], "confirm": False}
        )
        assert result["success"] is False
        assert result.get("needs_confirm") is True
        assert result["name"] == "manager"

    def test_create_role_missing_name_returns_error(self):
        """缺少 name 应返回错误。"""
        result = rbac_tools.create_role(
            {"permissions": ["admin.manage_users"], "confirm": True}
        )
        assert result["success"] is False
        assert result["error"] == "name is required"

    def test_create_role_invalid_permissions_type_returns_error(self):
        """permissions 非 list 应返回错误。"""
        result = rbac_tools.create_role(
            {"name": "manager", "permissions": "admin", "confirm": True}
        )
        assert result["success"] is False
        assert result["error"] == "permissions must be a list"

    def test_create_role_with_confirm_calls_service(self):
        """传 confirm=true 时应调用 service.create_role。"""
        mock_svc = MagicMock()
        mock_svc.create_role.return_value = {
            "id": 7,
            "name": "manager",
            "permissions": ["admin.manage_users"],
        }
        with patch.object(rbac_tools, "_get_service", return_value=mock_svc):
            result = rbac_tools.create_role(
                {
                    "name": "manager",
                    "permissions": ["admin.manage_users", "report.view"],
                    "description": "管理员角色",
                    "confirm": True,
                }
            )

        mock_svc.create_role.assert_called_once_with(
            "manager", "管理员角色", ["admin.manage_users", "report.view"]
        )
        assert result["success"] is True
        assert result["name"] == "manager"
        assert "manager 已创建" in result["message"]
        assert result["data"]["id"] == 7


class TestAssignRole:
    """assign_role 执行器测试套件。"""

    def test_assign_role_without_confirm_returns_needs_confirm(self):
        """未传 confirm=true 时应拒绝执行。"""
        result = rbac_tools.assign_role(
            {"user_id": 10, "role": "manager", "confirm": False}
        )
        assert result["success"] is False
        assert result.get("needs_confirm") is True
        assert result["user_id"] == 10
        assert result["role"] == "manager"

    def test_assign_role_missing_role_returns_error(self):
        """缺少 role 应返回错误。"""
        result = rbac_tools.assign_role({"user_id": 10, "confirm": True})
        assert result["success"] is False
        assert result["error"] == "role is required"

    def test_assign_role_invalid_user_id_returns_error(self):
        """user_id 非 int 应返回错误。"""
        result = rbac_tools.assign_role(
            {"user_id": "abc", "role": "manager", "confirm": True}
        )
        assert result["success"] is False
        assert result["error"] == "user_id is required and must be int"

    def test_assign_role_with_confirm_calls_service(self):
        """传 confirm=true 时应调用 service.assign_user_role。"""
        mock_svc = MagicMock()
        mock_svc.assign_user_role.return_value = {
            "user_id": 10,
            "role": "manager",
        }
        with patch.object(rbac_tools, "_get_service", return_value=mock_svc):
            result = rbac_tools.assign_role(
                {"user_id": 10, "role": "manager", "confirm": True}
            )

        mock_svc.assign_user_role.assert_called_once_with(10, "manager")
        assert result["success"] is True
        assert result["user_id"] == 10
        assert result["role"] == "manager"
        assert "已分配到角色 manager" in result["message"]

    def test_assign_role_accepts_role_name_alias(self):
        """role_name 别名应被接受。"""
        mock_svc = MagicMock()
        mock_svc.assign_user_role.return_value = {"user_id": 10, "role": "admin"}
        with patch.object(rbac_tools, "_get_service", return_value=mock_svc):
            result = rbac_tools.assign_role(
                {"user_id": 10, "role_name": "admin", "confirm": True}
            )

        mock_svc.assign_user_role.assert_called_once_with(10, "admin")
        assert result["success"] is True


class TestListRoles:
    """list_roles 执行器测试套件。"""

    def test_list_roles_returns_all_roles(self):
        """无 tenant_id 时调用 list_roles(tenant_id=None)。"""
        mock_svc = MagicMock()
        mock_svc.list_roles.return_value = [
            {"id": 1, "name": "admin", "permissions": ["admin.manage_users"]},
            {"id": 2, "name": "user", "permissions": []},
        ]
        with patch.object(rbac_tools, "_get_service", return_value=mock_svc):
            result = rbac_tools.list_roles({})

        mock_svc.list_roles.assert_called_once_with(tenant_id=None)
        assert result["success"] is True
        assert result["count"] == 2
        assert result["data"][0]["name"] == "admin"

    def test_list_roles_with_tenant_id_passes_through(self):
        """tenant_id 应被字符串化并传递。"""
        mock_svc = MagicMock()
        mock_svc.list_roles.return_value = []
        with patch.object(rbac_tools, "_get_service", return_value=mock_svc):
            rbac_tools.list_roles({"tenant_id": 42})

        mock_svc.list_roles.assert_called_once_with(tenant_id="42")
