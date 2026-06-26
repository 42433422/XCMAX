"""测试 app.application.ai_circle_service 的分支覆盖。

覆盖目标：
- _iso（None / naive datetime / aware datetime）
- create_user_post（空内容 / 超长 / 有效 / 默认作者名）
- record_employee_activity（空 employee / blocked / success / fail / 有无 task / 有无 summary / 异常）
- list_posts（空列表 / 有帖子含点赞和评论）
- toggle_like（帖子不存在 / 已点赞取消 / 新点赞）
- add_comment（空内容 / 超长 / 帖子不存在 / 有效 / 默认作者名）
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_ai_circle_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "application"
        / "ai_circle_service.py"
    )
    spec = importlib.util.spec_from_file_location("ai_circle_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ai_circle = _load_ai_circle_module()


@contextmanager
def _fake_db_ctx(db_mock: MagicMock):
    """模拟 get_db() 上下文管理器。"""

    @contextmanager
    def _ctx():
        yield db_mock

    with patch.object(ai_circle, "get_db", _ctx):
        yield


class TestIso:
    """_iso 分支覆盖。"""

    def test_none_returns_current_iso(self) -> None:
        result = ai_circle._iso(None)
        assert "T" in result

    def test_naive_datetime_gets_utc(self) -> None:
        dt = datetime(2025, 1, 1, 12, 0, 0)
        result = ai_circle._iso(dt)
        assert "+00:00" in result

    def test_aware_datetime_preserved(self) -> None:
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = ai_circle._iso(dt)
        assert result == "2025-01-01T12:00:00+00:00"


class TestCreateUserPost:
    """create_user_post 分支覆盖。"""

    def test_empty_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="不能为空"):
                ai_circle.create_user_post(
                    user_id=1, author_name="x", avatar=None, body=""
                )

    def test_whitespace_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="不能为空"):
                ai_circle.create_user_post(
                    user_id=1, author_name="x", avatar=None, body="   "
                )

    def test_too_long_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="2000"):
                ai_circle.create_user_post(
                    user_id=1, author_name="x", avatar=None, body="x" * 2001
                )

    def test_valid_post_with_author_name(self) -> None:
        db_mock = MagicMock()
        row_mock = MagicMock()
        row_mock.id = 42
        db_mock.add = MagicMock(side_effect=lambda r: setattr(r, "id", 42))
        db_mock.flush = MagicMock()
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            post_id = ai_circle.create_user_post(
                user_id=1, author_name="Alice", avatar="http://x/a.png", body="hello"
            )
            assert post_id == 42
            db_mock.add.assert_called_once()
            db_mock.flush.assert_called_once()

    def test_valid_post_with_empty_author_name_uses_default(self) -> None:
        db_mock = MagicMock()
        added_rows: list = []

        def _add(row):
            row.id = 7
            added_rows.append(row)

        db_mock.add = MagicMock(side_effect=_add)
        db_mock.flush = MagicMock()
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            post_id = ai_circle.create_user_post(
                user_id=1, author_name="  ", avatar=None, body="hello"
            )
            assert post_id == 7
            assert added_rows[0].author_name == "企业成员"


class TestRecordEmployeeActivity:
    """record_employee_activity 分支覆盖。"""

    def test_empty_employee_returns_early(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables") as mock_ensure:
            ai_circle.record_employee_activity("", success=True)
            mock_ensure.assert_not_called()

    def test_whitespace_employee_returns_early(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables") as mock_ensure:
            ai_circle.record_employee_activity("   ", success=True)
            mock_ensure.assert_not_called()

    def test_blocked_state(self) -> None:
        db_mock = MagicMock()
        added: list = []

        def _add(row):
            added.append(row)

        db_mock.add = MagicMock(side_effect=_add)
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity(
                "emp1", success=False, blocked=True, task="do something", summary="blocked by policy"
            )
            assert len(added) == 1
            assert "拦截" in added[0].body
            assert "do something" in added[0].body
            assert "blocked by policy" in added[0].body

    def test_success_state(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity("emp1", success=True, task="run", summary="ok")
            assert "完成" in added[0].body

    def test_failure_state(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity("emp1", success=False, task="run", summary="err")
            assert "失败" in added[0].body

    def test_no_task_no_summary_just_state(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity("emp1", success=True)
            assert added[0].body == "任务执行完成"

    def test_task_only(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity("emp1", success=True, task="only task")
            assert "任务：only task" in added[0].body
            assert "结果" not in added[0].body

    def test_summary_only(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.record_employee_activity("emp1", success=False, summary="only summary")
            assert "结果：only summary" in added[0].body
            # state line contains "任务执行失败" but no "任务：" detail line
            assert "任务：" not in added[0].body

    def test_long_task_truncated(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            long_task = "x" * 300
            ai_circle.record_employee_activity("emp1", success=True, task=long_task)
            # task_text is truncated to 240 chars
            task_line = [l for l in added[0].body.split("\n") if "任务" in l][0]
            assert len(task_line) <= 260  # "任务：" prefix + 240 chars

    def test_long_summary_truncated(self) -> None:
        db_mock = MagicMock()
        added: list = []
        db_mock.add = MagicMock(side_effect=lambda r: added.append(r))
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            long_summary = "y" * 400
            ai_circle.record_employee_activity("emp1", success=True, summary=long_summary)
            summary_line = [l for l in added[0].body.split("\n") if "结果" in l][0]
            assert len(summary_line) <= 380  # "结果：" prefix + 360 chars

    def test_recoverable_exception_swallowed(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables", side_effect=RuntimeError("db down")):
            # Should not raise - RECOVERABLE_ERRORS includes RuntimeError
            ai_circle.record_employee_activity("emp1", success=True)

    def test_unrecoverable_exception_propagates(self) -> None:
        # KeyError is in RECOVERABLE_ERRORS, but KeyboardInterrupt is not
        with patch.object(ai_circle, "ensure_ai_circle_tables", side_effect=KeyboardInterrupt("halt")):
            with pytest.raises(KeyboardInterrupt):
                ai_circle.record_employee_activity("emp1", success=True)


class TestListPosts:
    """list_posts 分支覆盖。"""

    def test_empty_posts_returns_empty_list(self) -> None:
        db_mock = MagicMock()
        db_mock.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            result = ai_circle.list_posts(user_id=1, limit=50)
            assert result == []

    def test_posts_with_likes_and_comments(self) -> None:
        db_mock = MagicMock()
        post1 = MagicMock()
        post1.id = 1
        post1.author_kind = "user"
        post1.author_user_id = 10
        post1.employee_id = None
        post1.author_name = "Alice"
        post1.author_avatar = "http://x/a.png"
        post1.body = "hello"
        post1.source_type = "manual"
        post1.created_at = datetime(2025, 1, 1, tzinfo=UTC)

        post2 = MagicMock()
        post2.id = 2
        post2.author_kind = "employee"
        post2.author_user_id = None
        post2.employee_id = "emp1"
        post2.author_name = "emp1"
        post2.author_avatar = None
        post2.body = "task done"
        post2.source_type = "employee_execution"
        post2.created_at = datetime(2025, 1, 2, tzinfo=UTC)

        query_mock = db_mock.query.return_value
        query_mock.order_by.return_value.limit.return_value.all.return_value = [post1, post2]

        # like_rows query: post_id, count
        like_query = db_mock.query.return_value.filter.return_value.group_by.return_value
        like_query.all.return_value = [(1, 3), (2, 0)]

        # liked_ids query
        liked_query = db_mock.query.return_value.filter.return_value
        liked_query.all.return_value = [MagicMock(post_id=1)]

        # comments query
        comment1 = MagicMock()
        comment1.id = 100
        comment1.post_id = 1
        comment1.author_name = "Bob"
        comment1.body = "nice"
        comment1.created_at = datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
        comment_query = db_mock.query.return_value.filter.return_value.order_by.return_value
        comment_query.all.return_value = [comment1]

        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            result = ai_circle.list_posts(user_id=10, limit=50)
            assert len(result) == 2
            # mock returns posts in order [post1, post2]; code preserves query order
            assert result[0]["id"] == 1
            assert result[0]["author_kind"] == "user"
            assert result[1]["id"] == 2
            assert result[1]["like_count"] == 0
            assert result[0]["like_count"] == 3
            assert result[0]["liked_by_me"] is True
            assert len(result[0]["comments"]) == 1
            assert result[0]["comments"][0]["body"] == "nice"

    def test_limit_clamped_to_max(self) -> None:
        db_mock = MagicMock()
        db_mock.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.list_posts(user_id=1, limit=200)
            # limit should be clamped to 100
            db_mock.query.return_value.order_by.return_value.limit.assert_called_with(100)

    def test_limit_clamped_to_min(self) -> None:
        db_mock = MagicMock()
        db_mock.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            ai_circle.list_posts(user_id=1, limit=0)
            db_mock.query.return_value.order_by.return_value.limit.assert_called_with(1)


class TestToggleLike:
    """toggle_like 分支覆盖。"""

    def test_post_not_found_raises(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = None
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            with pytest.raises(LookupError, match="不存在"):
                ai_circle.toggle_like(post_id=999, user_id=1)

    def test_existing_like_removed_returns_false(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = MagicMock()  # post exists
        existing_row = MagicMock()
        db_mock.query.return_value.filter_by.return_value.first.return_value = existing_row
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            result = ai_circle.toggle_like(post_id=1, user_id=1)
            assert result is False
            db_mock.delete.assert_called_once_with(existing_row)

    def test_new_like_added_returns_true(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = MagicMock()  # post exists
        db_mock.query.return_value.filter_by.return_value.first.return_value = None
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            result = ai_circle.toggle_like(post_id=1, user_id=1)
            assert result is True
            db_mock.add.assert_called_once()


class TestAddComment:
    """add_comment 分支覆盖。"""

    def test_empty_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="不能为空"):
                ai_circle.add_comment(post_id=1, user_id=1, author_name="x", body="")

    def test_whitespace_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="不能为空"):
                ai_circle.add_comment(post_id=1, user_id=1, author_name="x", body="  ")

    def test_too_long_content_raises(self) -> None:
        with patch.object(ai_circle, "ensure_ai_circle_tables"):
            with pytest.raises(ValueError, match="500"):
                ai_circle.add_comment(post_id=1, user_id=1, author_name="x", body="x" * 501)

    def test_post_not_found_raises(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = None
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            with pytest.raises(LookupError, match="不存在"):
                ai_circle.add_comment(post_id=999, user_id=1, author_name="x", body="hi")

    def test_valid_comment_with_author_name(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = MagicMock()  # post exists
        added: list = []

        def _add(row):
            row.id = 55
            added.append(row)

        db_mock.add = MagicMock(side_effect=_add)
        db_mock.flush = MagicMock()
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            comment_id = ai_circle.add_comment(
                post_id=1, user_id=1, author_name="Bob", body="nice post"
            )
            assert comment_id == 55
            assert added[0].author_name == "Bob"

    def test_valid_comment_with_empty_author_name_uses_default(self) -> None:
        db_mock = MagicMock()
        db_mock.get.return_value = MagicMock()
        added: list = []

        def _add(row):
            row.id = 66
            added.append(row)

        db_mock.add = MagicMock(side_effect=_add)
        db_mock.flush = MagicMock()
        with patch.object(ai_circle, "ensure_ai_circle_tables"), _fake_db_ctx(db_mock):
            comment_id = ai_circle.add_comment(
                post_id=1, user_id=1, author_name="", body="nice post"
            )
            assert comment_id == 66
            assert added[0].author_name == "企业成员"


class TestEnsureAiCircleTables:
    """ensure_ai_circle_tables 分支覆盖。"""

    def test_creates_tables(self) -> None:
        db_mock = MagicMock()
        with _fake_db_ctx(db_mock):
            ai_circle.ensure_ai_circle_tables()
            db_mock.get_bind.assert_called_once()
            # Base.metadata.create_all is called with bind and tables
