"""finance_schema / rbac_schema Pydantic 模型单元测试（必填/可选/默认/校验失败）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.finance_schema import FinanceTransactionCreate, FinanceTransactionUpdate
from app.schemas.rbac_schema import (
    PermissionCreate,
    RoleCreate,
    RoleUpdate,
    UserRoleAssign,
)


class TestFinanceSchema:
    def test_create_minimal(self):
        tx = FinanceTransactionCreate(transaction_type="revenue", amount=100.0)
        assert tx.transaction_type == "revenue"
        assert tx.amount == 100.0
        assert tx.description is None

    def test_create_full(self):
        tx = FinanceTransactionCreate(
            transaction_type="expense",
            amount=50.5,
            description="办公",
            reference_id="ref1",
            status="posted",
        )
        assert tx.reference_id == "ref1"
        assert tx.status == "posted"

    def test_create_missing_required_raises(self):
        with pytest.raises(ValidationError):
            FinanceTransactionCreate(amount=1.0)
        with pytest.raises(ValidationError):
            FinanceTransactionCreate(transaction_type="revenue")

    def test_create_amount_coerces_int(self):
        tx = FinanceTransactionCreate(transaction_type="revenue", amount=10)
        assert tx.amount == 10.0

    def test_update_all_optional(self):
        upd = FinanceTransactionUpdate()
        assert upd.transaction_type is None
        assert upd.amount is None

    def test_update_partial(self):
        upd = FinanceTransactionUpdate(amount=9.9, status="void")
        assert upd.amount == 9.9
        assert upd.status == "void"


class TestRbacSchema:
    def test_role_create_minimal_default_permissions(self):
        role = RoleCreate(name="admin")
        assert role.name == "admin"
        assert role.permissions == []
        assert role.description is None

    def test_role_create_with_permissions(self):
        role = RoleCreate(name="ops", description="运维", permissions=["a", "b"])
        assert role.permissions == ["a", "b"]

    def test_role_create_blank_name_raises(self):
        with pytest.raises(ValidationError):
            RoleCreate(name="")

    def test_role_update_optional(self):
        upd = RoleUpdate()
        assert upd.description is None
        assert upd.permissions is None

    def test_permission_create_required(self):
        perm = PermissionCreate(code="user.read", name="读用户")
        assert perm.code == "user.read"
        assert perm.module is None

    def test_permission_create_blank_code_raises(self):
        with pytest.raises(ValidationError):
            PermissionCreate(code="", name="x")

    def test_permission_create_blank_name_raises(self):
        with pytest.raises(ValidationError):
            PermissionCreate(code="x", name="")

    def test_user_role_assign(self):
        assign = UserRoleAssign(role="admin")
        assert assign.role == "admin"

    def test_user_role_assign_blank_raises(self):
        with pytest.raises(ValidationError):
            UserRoleAssign(role="")
