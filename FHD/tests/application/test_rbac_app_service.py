# -*- coding: utf-8 -*-
"""RbacAppService 桩实现与单例测试。"""

from __future__ import annotations

import app.application.rbac_app_service as rbac_mod
from app.application.rbac_app_service import RbacAppService, get_rbac_app_service


def test_rbac_crud_stubs():
    svc = RbacAppService()
    assert svc.list_tenants() == []
    assert svc.list_roles() == []
    role = svc.create_role("ops", "运维", ["read"])
    assert role["name"] == "ops"
    assert role["permissions"] == ["read"]
    updated = svc.update_role(3, description="d", permissions=["w"])
    assert updated["id"] == 3
    assert svc.get_role(5)["id"] == 5
    assert svc.delete_role(1) is None
    perm = svc.create_permission("x.read", "读", "desc", "mod")
    assert perm["code"] == "x.read"
    assert svc.delete_permission(1) is None
    assert svc.get_user_permissions(1) == []
    assert svc.assign_user_role(2, "admin") == {"user_id": 2, "role": "admin"}
    assert svc.seed_missing_permissions() == []


def test_get_rbac_app_service_singleton():
    rbac_mod._service = None
    a = get_rbac_app_service()
    b = get_rbac_app_service()
    assert a is b
    rbac_mod._service = None
