"""会议纪要多租户隔离：全局事件写打标 + 读过滤（纯靠 TenantScopedMixin）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture()
def db():
    import app.db.models  # noqa: F401  导入触发全局租户事件安装
    from app.db.models.meeting_minutes import MeetingMinute

    eng = create_engine("sqlite://")
    MeetingMinute.__table__.create(eng)
    with Session(eng) as session:
        yield session


def _mk(name: str):
    from app.db.models.meeting_minutes import MeetingMinute

    return MeetingMinute(title=name, raw_transcript=name, source_hash=name, status="completed")


def test_write_tag_and_read_filter(db):
    from app.db.models.meeting_minutes import MeetingMinute

    # 写入打标：scope 内不显式设 tenant_id，由 before_flush 自动打
    with tenant_scope(1):
        db.add(_mk("t1"))
        db.commit()
    with tenant_scope(2):
        db.add(_mk("t2"))
        db.commit()
    db.add(_mk("legacy"))  # 无 scope → tenant_id NULL（存量）
    db.commit()
    db.expire_all()

    # 读过滤（NULL 容忍）：本租户 + 未打标存量
    with tenant_scope(1):
        assert {m.title for m in db.query(MeetingMinute).all()} == {"t1", "legacy"}
    with tenant_scope(2):
        assert {m.title for m in db.query(MeetingMinute).all()} == {"t2", "legacy"}
    # admin（无 scope）看全部
    assert {m.title for m in db.query(MeetingMinute).all()} == {"t1", "t2", "legacy"}


def test_tenant_id_auto_set(db):
    from app.db.models.meeting_minutes import MeetingMinute

    with tenant_scope(42):
        row = _mk("x")
        db.add(row)
        db.commit()
    db.expire_all()
    got = db.query(MeetingMinute).filter_by(title="x").one()
    assert got.tenant_id == 42
