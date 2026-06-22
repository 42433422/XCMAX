"""租户隔离 × 真实业务模型(Product/Customer) 集成测试 + 列迁移幂等性。"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.init_db import ensure_business_tenant_id_columns
from app.db.models.customer import Customer
from app.db.models.product import Product
from app.db.tenant_filter import install_tenant_filter
from app.request_tenant_ctx import tenant_scope


def _maker(engine):
    Base.metadata.create_all(engine, tables=[Product.__table__, Customer.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_real_product_cross_tenant_isolation():
    install_tenant_filter()
    engine = create_engine("sqlite://")
    maker = _maker(engine)

    # 两租户各写自己的产品/客户（写时自动打标，不显式带 tenant_id）。
    with maker() as s, tenant_scope(1), s.begin():
        s.add(Product(name="t1-widget"))
        s.add(Customer(customer_name="t1-acme"))
    with maker() as s, tenant_scope(2), s.begin():
        s.add(Product(name="t2-gadget"))

    # 租户1 只见自己的产品。
    with maker() as s, tenant_scope(1):
        assert {p.name for p in s.execute(select(Product)).scalars()} == {"t1-widget"}
        assert {c.customer_name for c in s.execute(select(Customer)).scalars()} == {"t1-acme"}

    # 租户2 看不到租户1 的任何业务数据（漏洞修复本体）。
    with maker() as s, tenant_scope(2):
        assert {p.name for p in s.execute(select(Product)).scalars()} == {"t2-gadget"}
        assert s.execute(select(Customer)).scalars().all() == []

    # 平台管理员（无租户上下文）仍可见全部。
    with maker() as s:
        assert {p.name for p in s.execute(select(Product)).scalars()} == {"t1-widget", "t2-gadget"}

    engine.dispose()


def test_ensure_adds_tenant_id_to_legacy_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    # 模拟旧库：业务表存在但缺 tenant_id 列。
    with engine.begin() as c:
        c.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR)"))
        c.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, customer_name VARCHAR)"))

    ensure_business_tenant_id_columns(engine=engine)
    assert "tenant_id" in {col["name"] for col in inspect(engine).get_columns("products")}
    assert "tenant_id" in {col["name"] for col in inspect(engine).get_columns("customers")}

    # 幂等：列已存在时再跑不应报错或重复加列。
    ensure_business_tenant_id_columns(engine=engine)
    engine.dispose()
