"""多租户作用域过滤（apply_tenant_filter / tenant_scope）测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models.product import Product
from app.infrastructure.tenant_scope import (
    apply_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    tenant_scope,
)


@pytest.fixture()
def session_with_products():
    """内存 sqlite：3 条产品分属 tenant=1 / tenant=2 / NULL。"""
    eng = create_engine("sqlite://")
    Product.__table__.create(bind=eng)
    with Session(eng) as db:
        db.add_all(
            [
                Product(name="t1-only", unit="个", is_active=1, tenant_id=1),
                Product(name="t2-only", unit="个", is_active=1, tenant_id=2),
                Product(name="legacy-null", unit="个", is_active=1, tenant_id=None),
            ]
        )
        db.commit()
        yield db


def _names(db):
    return {p.name for p in apply_tenant_filter(db.query(Product), Product).all()}


class TestTenantScopeContextVar:
    def test_default_none(self):
        assert current_tenant_id() is None

    def test_scope_set_reset(self):
        with tenant_scope(5):
            assert current_tenant_id() == 5
        assert current_tenant_id() is None

    def test_explicit_set_reset(self):
        token = set_current_tenant_id(9)
        try:
            assert current_tenant_id() == 9
        finally:
            from app.infrastructure.tenant_scope import reset_current_tenant_id

            reset_current_tenant_id(token)
        assert current_tenant_id() is None


class TestApplyTenantFilter:
    def test_no_tenant_sees_all(self, session_with_products):
        # 当前租户为 None（管理员）→ 看全部
        assert _names(session_with_products) == {"t1-only", "t2-only", "legacy-null"}

    def test_null_tolerant_default(self, session_with_products):
        # 默认 NULL 容忍：tenant=1 看到本租户 + 未打标存量，看不到 tenant=2
        with tenant_scope(1):
            assert _names(session_with_products) == {"t1-only", "legacy-null"}
        with tenant_scope(2):
            assert _names(session_with_products) == {"t2-only", "legacy-null"}

    def test_strict_mode(self, session_with_products, monkeypatch):
        # 严格模式：只看本租户，不含 NULL 存量
        monkeypatch.setenv("XCAGI_TENANT_STRICT", "1")
        with tenant_scope(1):
            assert _names(session_with_products) == {"t1-only"}

    def test_model_without_tenant_column_unchanged(self):
        class _NoTenant:
            pass

        sentinel = object()
        assert apply_tenant_filter(sentinel, _NoTenant) is sentinel


class TestGlobalTenantEvent:
    """全局 ORM 事件（do_orm_execute 读过滤 + before_flush 写打标）端到端。"""

    @pytest.fixture()
    def db(self):
        import app.db.models  # noqa: F401  导入触发全局事件安装
        from app.db.models.material import Material
        from app.db.models.user import User

        eng = create_engine("sqlite://")
        Material.__table__.create(eng)
        User.__table__.create(eng)
        with Session(eng) as session:
            yield session

    def test_event_isolation_and_write_tag(self, db):
        from app.db.models.material import Material

        # 写入打标（before_flush）：scope 内不显式设 tenant_id
        with tenant_scope(1):
            db.add(Material(material_code="a", name="t1", unit="个", quantity=0))
            db.commit()
        with tenant_scope(2):
            db.add(Material(material_code="b", name="t2", unit="个", quantity=0))
            db.commit()
        db.add(Material(material_code="c", name="legacy", unit="个", quantity=0))
        db.commit()
        db.expire_all()

        # 事件读过滤（Material 无手工接线，纯靠全局事件）
        with tenant_scope(1):
            assert {m.name for m in db.query(Material).all()} == {"t1", "legacy"}
        with tenant_scope(2):
            assert {m.name for m in db.query(Material).all()} == {"t2", "legacy"}
        # admin（无 scope）看全部
        assert {m.name for m in db.query(Material).all()} == {"t1", "t2", "legacy"}

    def test_auth_tables_not_filtered(self, db):
        # 关键：User 不继承 TenantScopedMixin → 即使在租户作用域内也不被过滤（登录安全）
        from app.db.models.user import User

        db.add(User(username="x", password="p", tenant_id=1))
        db.add(User(username="y", password="p", tenant_id=2))
        db.commit()
        db.expire_all()
        with tenant_scope(1):
            assert {u.username for u in db.query(User).all()} == {"x", "y"}
