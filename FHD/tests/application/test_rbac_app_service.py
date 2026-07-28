"""RbacAppService 桩实现与单例测试。"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.application.rbac_app_service as rbac_mod
from app.application.rbac_app_service import RbacAppService, get_rbac_app_service
from app.errors import DatabaseError


def test_rbac_crud_stubs():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    svc = RbacAppService(db_factory=lambda: nullcontext(db))
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


def test_rbac_lists_active_tenants_from_database():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        SimpleNamespace(
            id=7,
            code="beichen",
            name="北辰科技",
            is_active=True,
            plan_id="saas-enterprise",
        )
    ]
    svc = RbacAppService(db_factory=lambda: nullcontext(db))

    assert svc.list_tenants() == [
        {
            "id": 7,
            "tenant_id": "7",
            "code": "beichen",
            "name": "北辰科技",
            "is_active": True,
            "plan_id": "saas-enterprise",
        }
    ]


def test_rbac_tenant_directory_failure_is_not_reported_as_empty():
    class BrokenFactory:
        def __enter__(self):
            raise OSError("database unavailable")

        def __exit__(self, *_args):
            return False

    svc = RbacAppService(db_factory=BrokenFactory)

    with pytest.raises(DatabaseError, match="企业目录暂时不可用"):
        svc.list_tenants()


def test_get_rbac_app_service_singleton():
    rbac_mod._service = None
    a = get_rbac_app_service()
    b = get_rbac_app_service()
    assert a is b
    rbac_mod._service = None
