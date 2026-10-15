"""RbacAppService 持久化行为与单例测试。"""

from __future__ import annotations

from uuid import uuid4

import app.application.rbac_app_service as rbac_mod
from app.application.rbac_app_service import RbacAppService, get_rbac_app_service
from app.db.models.user import User
from app.db.session import get_db, get_host_db


def test_rbac_crud_persists_roles_permissions_and_assignments():
    svc = RbacAppService()
    assert svc.list_tenants() == []
    code = f"rbac.read.{uuid4().hex}"
    permission = svc.create_permission(code, "读取", "desc", "mod")
    role = svc.create_role(f"ops-{uuid4().hex}", "运维", [code])
    assert any(item["id"] == role["id"] for item in svc.list_roles())
    assert svc.get_role(role["id"])["permissions"][0]["code"] == code
    updated = svc.update_role(role["id"], description="d", permissions=[])
    assert updated["description"] == "d"
    assert svc.delete_role(role["id"]) is None
    svc.delete_permission(permission["id"])

    role = svc.create_role(f"operator-{uuid4().hex}", "运维", [])
    with get_host_db() as db:
        user = User(username=f"rbac-{uuid4().hex}", password="test", role="user")
        db.add(user)
        db.flush()
        user_id = user.id
    assert svc.assign_user_role(user_id, role["key"])["role"] == role["key"]
    with get_host_db() as db:
        db.query(User).filter(User.id == user_id).delete()
    svc.delete_role(role["id"])


def test_get_rbac_app_service_singleton():
    rbac_mod._service = None
    a = get_rbac_app_service()
    b = get_rbac_app_service()
    assert a is b
    rbac_mod._service = None
