"""会议纪要 ORM 模型：表结构、导出、增查、陈旧检测。"""

from __future__ import annotations

from sqlalchemy.orm import Session

import app.mod_sdk  # noqa: F401  # 预热 app.services 包，规避隔离运行时已知的循环导入


def test_model_exported_from_package():
    import app.db.models as m

    assert hasattr(m, "MeetingMinute")
    assert "MeetingMinute" in m.__all__


def test_table_columns():
    from app.db.models.meeting_minutes import MeetingMinute

    assert MeetingMinute.__tablename__ == "meeting_minutes"
    cols = set(MeetingMinute.__table__.columns.keys())
    assert {
        "id",
        "title",
        "user_id",
        "raw_transcript",
        "source_hash",
        "level1_script",
        "level2_architecture",
        "level3_plain",
        "status",
        "error_message",
        "tenant_id",  # TenantScopedMixin
        "created_at",  # TimestampMixin
        "updated_at",
    } <= cols


def test_insert_and_query(tmp_sqlite_db):
    from app.db.models.meeting_minutes import MeetingMinute
    from app.services.meeting_minutes.pipeline import compute_source_hash

    _engine, SessionLocal = tmp_sqlite_db
    raw = "张三：下周上线。李四：好。"
    with SessionLocal() as db:  # type: Session
        row = MeetingMinute(
            title="周会",
            user_id=7,
            raw_transcript=raw,
            source_hash=compute_source_hash(raw),
            status="completed",
            level1_script="【张三】：下周上线。",
            level2_architecture="```mermaid\nflowchart TD\nA-->B\n```",
            level3_plain="说白了：下周要上线。",
        )
        db.add(row)
        db.commit()
        rid = row.id

    with SessionLocal() as db:
        got = db.get(MeetingMinute, rid)
        assert got is not None
        assert got.title == "周会"
        d = got.to_dict()
        assert d["level1_script"] and d["level2_architecture"] and d["level3_plain"]
        assert got.is_stale() is False  # 原文未变


def test_is_stale_when_raw_changes(tmp_sqlite_db):
    from app.db.models.meeting_minutes import MeetingMinute

    _engine, SessionLocal = tmp_sqlite_db
    with SessionLocal() as db:
        row = MeetingMinute(
            raw_transcript="原始内容",
            source_hash="deadbeef",  # 与 sha256(原始内容) 不一致
            status="completed",
        )
        db.add(row)
        db.commit()
        assert row.is_stale() is True
