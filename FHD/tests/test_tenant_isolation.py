"""全局租户隔离机制单元测试（仅依赖 SQLAlchemy，无需整 app 启动）。

覆盖安全语义：无上下文放行、租户隔离、NULL 容忍、严格模式、
写自动打标、逐查询逃生舱、应急总开关。
"""

from __future__ import annotations

import pytest
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.db.base import Base
from app.db.mixins import IntegerPrimaryKeyMixin, TenantScopedMixin
from app.db.tenant_filter import install_tenant_filter
from app.request_tenant_ctx import tenant_scope


class _TenantThing(IntegerPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "_test_tenant_things"

    name: Mapped[str] = mapped_column(String(64), nullable=False)


@pytest.fixture(scope="module", autouse=True)
def _install_filter():
    install_tenant_filter()


@pytest.fixture()
def make_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[_TenantThing.__table__])
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield maker
    engine.dispose()


def _seed(maker):
    """无上下文直写固定分布：租户1 两行、租户2 一行、NULL(存量) 一行。"""
    with maker() as s, s.begin():
        s.add_all(
            [
                _TenantThing(name="a", tenant_id=1),
                _TenantThing(name="b", tenant_id=1),
                _TenantThing(name="c", tenant_id=2),
                _TenantThing(name="legacy", tenant_id=None),
            ]
        )


def test_no_context_sees_all(make_session):
    _seed(make_session)
    with make_session() as s:
        rows = s.execute(select(_TenantThing)).scalars().all()
    assert len(rows) == 4  # 无租户上下文 → 不过滤


def test_tenant_scope_isolates_with_null_tolerance(make_session):
    _seed(make_session)
    with make_session() as s, tenant_scope(1):
        names = {r.name for r in s.execute(select(_TenantThing)).scalars()}
    assert names == {"a", "b", "legacy"}  # 租户1 + NULL 容忍


def test_other_tenant_cannot_see_first(make_session):
    _seed(make_session)
    with make_session() as s, tenant_scope(2):
        names = {r.name for r in s.execute(select(_TenantThing)).scalars()}
    assert names == {"c", "legacy"}  # 看不到租户1 的 a/b


def test_strict_mode_excludes_null(make_session, monkeypatch):
    monkeypatch.setenv("XCAGI_TENANT_STRICT", "1")
    _seed(make_session)
    with make_session() as s, tenant_scope(1):
        names = {r.name for r in s.execute(select(_TenantThing)).scalars()}
    assert names == {"a", "b"}  # 严格相等：排除 NULL


def test_before_flush_stamps_current_tenant(make_session):
    with make_session() as s, tenant_scope(7):
        with s.begin():
            s.add(_TenantThing(name="new"))  # 不显式带 tenant_id
        obj = s.execute(select(_TenantThing).filter_by(name="new")).scalar_one()
        assert obj.tenant_id == 7


def test_escape_hatch_bypasses_filter(make_session):
    _seed(make_session)
    with make_session() as s, tenant_scope(1):
        rows = (
            s.execute(
                select(_TenantThing),
                execution_options={"skip_tenant_filter": True},
            )
            .scalars()
            .all()
        )
    assert len(rows) == 4


def test_kill_switch_disables_filter(make_session, monkeypatch):
    monkeypatch.setenv("XCAGI_DISABLE_TENANT_FILTER", "1")
    _seed(make_session)
    with make_session() as s, tenant_scope(1):
        rows = s.execute(select(_TenantThing)).scalars().all()
    assert len(rows) == 4
