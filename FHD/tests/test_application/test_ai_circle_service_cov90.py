"""Real-behavior tests for app.application.ai_circle_service.

Strategy: drive the real service functions against an in-memory SQLite engine
with the real ORM models. ``get_db`` (the function-internal context manager) is
patched at the use-site (``app.application.ai_circle_service.get_db``) to yield a
real Session bound to the throwaway engine, so every query / flush / filter in
the module executes for real. Tests are offline, deterministic and fast.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application import ai_circle_service as svc
from app.db.base import Base
from app.db.models.ai_circle import AiCircleComment, AiCirclePost, AiCircleReaction


@pytest.fixture()
def db_factory(monkeypatch):
    """In-memory SQLite + real models; patches get_db at the service use-site.

    Returns a ``Session`` factory so a test can open its own session to seed /
    assert rows independently of the service's own transactions.
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            AiCirclePost.__table__,
            AiCircleReaction.__table__,
            AiCircleComment.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, future=True)

    @contextmanager
    def fake_get_db():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(svc, "get_db", fake_get_db)
    return SessionLocal


# --------------------------------------------------------------------------- #
# _iso (lines 34-39)
# --------------------------------------------------------------------------- #


def test_iso_none_returns_current_utc_isoformat():
    out = svc._iso(None)
    # Parses back as an aware datetime with explicit offset.
    parsed = datetime.fromisoformat(out)
    assert parsed.tzinfo is not None


def test_iso_naive_datetime_gets_utc_offset():
    out = svc._iso(datetime(2024, 1, 2, 3, 4, 5))
    assert out == "2024-01-02T03:04:05+00:00"


def test_iso_aware_datetime_preserved():
    aware = datetime.fromisoformat("2024-05-06T07:08:09+02:00")
    assert svc._iso(aware) == "2024-05-06T07:08:09+02:00"


# --------------------------------------------------------------------------- #
# create_user_post (lines 42-60)
# --------------------------------------------------------------------------- #


def test_create_user_post_persists_and_returns_id(db_factory):
    new_id = svc.create_user_post(
        user_id=7, author_name="  Alice  ", avatar="http://a/x.png", body="  hello world  "
    )
    assert isinstance(new_id, int)
    with db_factory() as db:
        row = db.get(AiCirclePost, new_id)
        assert row.author_kind == "user"
        assert row.author_user_id == 7
        assert row.author_name == "Alice"  # trimmed
        assert row.author_avatar == "http://a/x.png"
        assert row.body == "hello world"  # trimmed
        assert row.source_type == "manual"


def test_create_user_post_blank_author_name_falls_back(db_factory):
    new_id = svc.create_user_post(user_id=1, author_name="   ", avatar=None, body="hi")
    with db_factory() as db:
        assert db.get(AiCirclePost, new_id).author_name == "企业成员"


def test_create_user_post_empty_body_raises(db_factory):
    with pytest.raises(ValueError, match="不能为空"):
        svc.create_user_post(user_id=1, author_name="x", avatar=None, body="   ")


def test_create_user_post_none_body_raises(db_factory):
    with pytest.raises(ValueError, match="不能为空"):
        svc.create_user_post(user_id=1, author_name="x", avatar=None, body=None)


def test_create_user_post_too_long_raises(db_factory):
    with pytest.raises(ValueError, match="2000"):
        svc.create_user_post(user_id=1, author_name="x", avatar=None, body="a" * 2001)


# --------------------------------------------------------------------------- #
# record_employee_activity (lines 63-103)
# --------------------------------------------------------------------------- #


def test_record_employee_activity_blank_id_noops(db_factory):
    svc.record_employee_activity("   ", success=True, task="t", summary="s")
    with db_factory() as db:
        assert db.query(AiCirclePost).count() == 0


def test_record_employee_activity_success_persists_completed_state(db_factory):
    svc.record_employee_activity("emp-1", success=True, task="build it", summary="all good")
    with db_factory() as db:
        row = db.query(AiCirclePost).one()
        assert row.author_kind == "employee"
        assert row.employee_id == "emp-1"
        assert row.source_type == "employee_execution"
        assert row.source_ref.startswith("employee-run:")
        assert "任务执行完成" in row.body
        assert "任务：build it" in row.body
        assert "结果：all good" in row.body


def test_record_employee_activity_failure_state(db_factory):
    svc.record_employee_activity("emp-2", success=False)
    with db_factory() as db:
        row = db.query(AiCirclePost).one()
        # No task/summary => body is exactly the state line (no details block).
        assert row.body == "任务执行失败"


def test_record_employee_activity_blocked_overrides_success(db_factory):
    svc.record_employee_activity("emp-3", success=True, blocked=True, task="x")
    with db_factory() as db:
        row = db.query(AiCirclePost).one()
        assert "任务被安全策略拦截" in row.body


def test_record_employee_activity_swallows_recoverable_errors(monkeypatch):
    # ensure_ai_circle_tables raises a recoverable error -> warning logged, no raise.
    def boom():
        raise ValueError("db down")

    monkeypatch.setattr(svc, "ensure_ai_circle_tables", boom)
    # Should NOT raise.
    svc.record_employee_activity("emp-x", success=True)


# --------------------------------------------------------------------------- #
# list_posts (lines 106-163)
# --------------------------------------------------------------------------- #


def test_list_posts_empty_returns_empty_list(db_factory):
    assert svc.list_posts(user_id=1) == []


def test_list_posts_returns_posts_with_counts_likes_and_comments(db_factory):
    p1 = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="first")
    p2 = svc.create_user_post(user_id=2, author_name="B", avatar=None, body="second")

    # Two likes on p1 (user 1 and user 9); none on p2.
    svc.toggle_like(post_id=p1, user_id=1)
    svc.toggle_like(post_id=p1, user_id=9)
    # Comment on p1.
    svc.add_comment(post_id=p1, user_id=5, author_name="C", body="nice")

    posts = svc.list_posts(user_id=1, limit=50)
    by_id = {p["id"]: p for p in posts}

    # ordered desc by id => p2 first
    assert [p["id"] for p in posts] == sorted([p1, p2], reverse=True)

    assert by_id[p1]["like_count"] == 2
    assert by_id[p1]["liked_by_me"] is True  # user 1 liked it
    assert by_id[p2]["like_count"] == 0
    assert by_id[p2]["liked_by_me"] is False

    assert len(by_id[p1]["comments"]) == 1
    assert by_id[p1]["comments"][0]["author_name"] == "C"
    assert by_id[p1]["comments"][0]["body"] == "nice"
    assert by_id[p2]["comments"] == []
    # created_at always serialised to a string via _iso.
    assert isinstance(by_id[p1]["created_at"], str)


def test_list_posts_liked_by_me_false_for_other_user(db_factory):
    p1 = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    svc.toggle_like(post_id=p1, user_id=99)  # someone else likes
    posts = svc.list_posts(user_id=1)
    assert posts[0]["like_count"] == 1
    assert posts[0]["liked_by_me"] is False


def test_list_posts_limit_clamped_low(db_factory):
    for i in range(3):
        svc.create_user_post(user_id=1, author_name="A", avatar=None, body=f"b{i}")
    # limit below 1 is clamped to 1
    posts = svc.list_posts(user_id=1, limit=0)
    assert len(posts) == 1


def test_list_posts_limit_clamped_high(db_factory):
    p = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    # limit above 100 is clamped to 100; only one post exists so result is 1.
    posts = svc.list_posts(user_id=1, limit=10_000)
    assert len(posts) == 1 and posts[0]["id"] == p


def test_list_posts_comments_capped_at_20(db_factory):
    p = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    for i in range(25):
        svc.add_comment(post_id=p, user_id=1, author_name="C", body=f"c{i}")
    posts = svc.list_posts(user_id=1)
    comments = posts[0]["comments"]
    assert len(comments) == 20
    # Keeps the LAST 20 (ascending id order, sliced [-20:]).
    assert comments[0]["body"] == "c5"
    assert comments[-1]["body"] == "c24"


# --------------------------------------------------------------------------- #
# toggle_like (lines 166-180)
# --------------------------------------------------------------------------- #


def test_toggle_like_adds_then_removes(db_factory):
    p = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")

    assert svc.toggle_like(post_id=p, user_id=3) is True
    with db_factory() as db:
        assert db.query(AiCircleReaction).filter_by(post_id=p, user_id=3, kind="like").count() == 1

    assert svc.toggle_like(post_id=p, user_id=3) is False
    with db_factory() as db:
        assert db.query(AiCircleReaction).filter_by(post_id=p, user_id=3, kind="like").count() == 0


def test_toggle_like_missing_post_raises(db_factory):
    with pytest.raises(LookupError, match="动态不存在"):
        svc.toggle_like(post_id=999_999, user_id=1)


# --------------------------------------------------------------------------- #
# add_comment (lines 183-201)
# --------------------------------------------------------------------------- #


def test_add_comment_persists_and_returns_id(db_factory):
    p = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    cid = svc.add_comment(post_id=p, user_id=4, author_name="  Bob  ", body="  great  ")
    assert isinstance(cid, int)
    with db_factory() as db:
        row = db.get(AiCircleComment, cid)
        assert row.post_id == p
        assert row.user_id == 4
        assert row.author_name == "Bob"  # trimmed
        assert row.body == "great"  # trimmed


def test_add_comment_blank_author_falls_back(db_factory):
    p = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    cid = svc.add_comment(post_id=p, user_id=1, author_name="  ", body="ok")
    with db_factory() as db:
        assert db.get(AiCircleComment, cid).author_name == "企业成员"


def test_add_comment_empty_body_raises(db_factory):
    with pytest.raises(ValueError, match="不能为空"):
        svc.add_comment(post_id=1, user_id=1, author_name="x", body="   ")


def test_add_comment_too_long_raises(db_factory):
    with pytest.raises(ValueError, match="500"):
        svc.add_comment(post_id=1, user_id=1, author_name="x", body="a" * 501)


def test_add_comment_missing_post_raises(db_factory):
    with pytest.raises(LookupError, match="动态不存在"):
        svc.add_comment(post_id=888_888, user_id=1, author_name="x", body="hello")


# --------------------------------------------------------------------------- #
# ensure_ai_circle_tables (lines 20-31) — idempotent create_all
# --------------------------------------------------------------------------- #


def test_ensure_ai_circle_tables_idempotent(db_factory):
    # Tables already created by the fixture; calling again must not raise.
    svc.ensure_ai_circle_tables()
    svc.ensure_ai_circle_tables()
    # And a post can still be created afterwards.
    new_id = svc.create_user_post(user_id=1, author_name="A", avatar=None, body="x")
    assert isinstance(new_id, int)
