"""验证业务编码列改为 (tenant_id, code) 复合唯一后的行为（fresh sqlite）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import purchase
from app.db.tenant_filter import install_tenant_filter
from app.request_tenant_ctx import tenant_scope


def _maker():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[purchase.Supplier.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_same_code_allowed_across_tenants():
    install_tenant_filter()
    maker = _maker()
    with maker() as s, tenant_scope(1), s.begin():
        s.add(purchase.Supplier(code="S001", name="租户1供应商"))
    # 另一租户复用同一编码：不应冲突
    with maker() as s, tenant_scope(2), s.begin():
        s.add(purchase.Supplier(code="S001", name="租户2供应商"))


def test_duplicate_code_within_tenant_rejected():
    install_tenant_filter()
    maker = _maker()
    with maker() as s, tenant_scope(1), s.begin():
        s.add(purchase.Supplier(code="S001", name="供应商A"))
    with pytest.raises(IntegrityError):  # noqa: PT012
        with maker() as s, tenant_scope(1), s.begin():
            s.add(purchase.Supplier(code="S001", name="供应商A重复"))
