"""多租户作用域过滤（apply_tenant_filter / tenant_scope）测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models.product import Product
from app.infrastructure.tenant_scope import (
    apply_tenant_filter,
    append_tenant_scope_where,
    current_tenant_id,
    require_raw_sql_tenant_id,
    set_current_tenant_id,
    TenantScopeError,
    tenant_scope,
)


@pytest.fixture()
def session_with_products(monkeypatch):
    """内存 sqlite：3 条产品分属 tenant=1 / tenant=2 / NULL。"""
    eng = create_engine("sqlite://")
    Product.__table__.create(bind=eng)
    with Session(eng) as db:
        monkeypatch.setenv("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE", "1")
        db.add_all(
            [
                Product(name="t1-only", unit="个", is_active=1, tenant_id=1),
                Product(name="t2-only", unit="个", is_active=1, tenant_id=2),
                Product(name="legacy-null", unit="个", is_active=1, tenant_id=None),
            ]
        )
        db.commit()
        monkeypatch.delenv("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE")
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
    def test_no_tenant_sees_none(self, session_with_products):
        # 当前租户为 None → 业务数据 fail-closed，避免未登录/上下文丢失时看全库
        assert _names(session_with_products) == set()

    def test_strict_default(self, session_with_products):
        # 默认严格：tenant=1 只看到本租户，看不到 tenant=2 / NULL 存量
        with tenant_scope(1):
            assert _names(session_with_products) == {"t1-only"}
        with tenant_scope(2):
            assert _names(session_with_products) == {"t2-only"}

    def test_legacy_null_visible_requires_explicit_migration_flag(
        self, session_with_products, monkeypatch
    ):
        monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
        with tenant_scope(1):
            assert _names(session_with_products) == {"t1-only", "legacy-null"}

    def test_model_without_tenant_column_unchanged(self):
        class _NoTenant:
            pass

        sentinel = object()
        assert apply_tenant_filter(sentinel, _NoTenant) is sentinel


class TestRawSqlTenantScope:
    def test_append_where_missing_tenant_column_fail_closed(self):
        where_parts: list[str] = []
        bind: dict[str, object] = {}
        with tenant_scope(1):
            ok = append_tenant_scope_where(where_parts, bind, {"id"}, table_name="products")
        assert ok is False
        assert where_parts == ["1 = 0"]
        assert bind == {}

    def test_require_tenant_id_missing_column_raises(self):
        with tenant_scope(1):
            with pytest.raises(TenantScopeError):
                require_raw_sql_tenant_id({"id"}, table_name="products")


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

    def test_event_isolation_and_write_tag(self, db, monkeypatch):
        from app.db.models.material import Material

        # 写入打标（before_flush）：scope 内不显式设 tenant_id
        with tenant_scope(1):
            db.add(Material(material_code="a", name="t1", unit="个", quantity=0))
            db.commit()
        with tenant_scope(2):
            db.add(Material(material_code="b", name="t2", unit="个", quantity=0))
            db.commit()
        monkeypatch.setenv("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE", "1")
        db.add(Material(material_code="c", name="legacy", unit="个", quantity=0))
        db.commit()
        monkeypatch.delenv("XCAGI_TENANT_ALLOW_UNSCOPED_WRITE")
        db.expire_all()

        # 事件读过滤（Material 无手工接线，纯靠全局事件）
        with tenant_scope(1):
            assert {m.name for m in db.query(Material).all()} == {"t1"}
        with tenant_scope(2):
            assert {m.name for m in db.query(Material).all()} == {"t2"}
        # 无 scope 看不到业务数据
        assert {m.name for m in db.query(Material).all()} == set()

    def test_unscoped_write_rejected(self, db):
        from app.db.models.material import Material
        from app.infrastructure.tenant_scope import TenantScopeError

        db.add(Material(material_code="c", name="legacy", unit="个", quantity=0))
        with pytest.raises(TenantScopeError):
            db.commit()
        db.rollback()

    def test_auth_tables_not_filtered(self, db):
        # 关键：User 不继承 TenantScopedMixin → 即使在租户作用域内也不被过滤（登录安全）
        from app.db.models.user import User

        db.add(User(username="x", password="p", tenant_id=1))
        db.add(User(username="y", password="p", tenant_id=2))
        db.commit()
        db.expire_all()
        with tenant_scope(1):
            assert {u.username for u in db.query(User).all()} == {"x", "y"}
