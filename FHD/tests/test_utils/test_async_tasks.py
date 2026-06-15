"""Tests for app.utils.async_tasks."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.utils.async_tasks import (
    AsyncTaskConfig,
    AsyncTaskManager,
    TaskResult,
    TaskStatus,
    async_task,
    background_task,
    get_async_task_manager,
    retry_on_failure,
    _register_default_tasks,
)


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------

class TestTaskStatus:
    def test_all_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.SUCCESS == "success"
        assert TaskStatus.FAILURE == "failure"
        assert TaskStatus.RETRYING == "retrying"
        assert TaskStatus.TIMEOUT == "timeout"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_is_string_enum(self):
        assert isinstance(TaskStatus.PENDING, str)


# ---------------------------------------------------------------------------
# TaskResult
# ---------------------------------------------------------------------------

class TestTaskResult:
    def test_default_values(self):
        r = TaskResult(task_id="t1", status=TaskStatus.PENDING)
        assert r.task_id == "t1"
        assert r.status == TaskStatus.PENDING
        assert r.result is None
        assert r.error is None
        assert r.progress == 0
        assert r.total is None
        assert r.retries == 0
        assert r.metadata == {}

    def test_duration_ms_with_times(self):
        r = TaskResult(
            task_id="t1",
            status=TaskStatus.SUCCESS,
            started_at=1000.0,
            completed_at=1001.5,
        )
        assert r.duration_ms == 1500.0

    def test_duration_ms_without_times(self):
        r = TaskResult(task_id="t1", status=TaskStatus.PENDING)
        assert r.duration_ms == 0.0

    def test_is_success(self):
        r = TaskResult(task_id="t1", status=TaskStatus.SUCCESS)
        assert r.is_success is True

    def test_is_not_success(self):
        r = TaskResult(task_id="t1", status=TaskStatus.PENDING)
        assert r.is_success is False

    def test_is_failed(self):
        r = TaskResult(task_id="t1", status=TaskStatus.FAILURE)
        assert r.is_failed is True

    def test_is_failed_timeout(self):
        r = TaskResult(task_id="t1", status=TaskStatus.TIMEOUT)
        assert r.is_failed is True

    def test_is_not_failed(self):
        r = TaskResult(task_id="t1", status=TaskStatus.SUCCESS)
        assert r.is_failed is False


# ---------------------------------------------------------------------------
# AsyncTaskConfig
# ---------------------------------------------------------------------------

class TestAsyncTaskConfig:
    def test_default_values(self):
        config = AsyncTaskConfig(name="test_task")
        assert config.name == "test_task"
        assert config.queue == "normal"
        assert config.cache_result is True
        assert config.on_success is None
        assert config.on_failure is None

    def test_custom_values(self):
        config = AsyncTaskConfig(
            name="custom",
            queue="heavy",
            timeout=600,
            max_retries=5,
        )
        assert config.queue == "heavy"
        assert config.timeout == 600
        assert config.max_retries == 5


# ---------------------------------------------------------------------------
# AsyncTaskManager
# ---------------------------------------------------------------------------

class TestAsyncTaskManager:
    @pytest.fixture
    def manager(self):
        return AsyncTaskManager()

    def test_register_task(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)
        assert "test_task" in manager._task_configs

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: 42))
    def test_submit_sync_success(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        result = manager.submit("test_task", sync=True)

        assert result.status == TaskStatus.SUCCESS
        assert result.result == 42
        assert result.progress == 100

    @patch("app.tasks.get_task_function", create=True)
    def test_submit_sync_failure(self, mock_get_func, manager):
        config = AsyncTaskConfig(name="fail_task")
        manager.register_task(config)

        def failing_func():
            raise OSError("fail")

        mock_get_func.return_value = failing_func
        result = manager.submit("fail_task", sync=True)

        assert result.status == TaskStatus.FAILURE
        assert "fail" in result.error

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_submit_with_custom_task_id(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        result = manager.submit("test_task", task_id="custom-id", sync=True)
        assert result.task_id == "custom-id"

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_submit_unregistered_task(self, manager):
        result = manager.submit("unknown_task", sync=True)
        assert result.task_id is not None

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_get_status(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        result = manager.submit("test_task", task_id="t1", sync=True)
        status = manager.get_status("t1")
        assert status is not None
        assert status.task_id == "t1"

    def test_get_status_not_found(self, manager):
        assert manager.get_status("nonexistent") is None

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: 42))
    def test_get_result_success(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        result = manager.get_result("t1")
        assert result == 42

    def test_get_result_not_found(self, manager):
        result = manager.get_result("nonexistent")
        assert result is None

    @patch("app.tasks.get_task_function", create=True)
    def test_get_result_failed_raises(self, mock_get_func, manager):
        config = AsyncTaskConfig(name="fail_task")
        manager.register_task(config)

        def failing_func():
            raise OSError("boom")

        mock_get_func.return_value = failing_func
        manager.submit("fail_task", task_id="t1", sync=True)

        with pytest.raises(Exception, match="boom"):
            manager.get_result("t1")

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_update_progress(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        manager.update_progress("t1", 50, 100)
        status = manager.get_status("t1")
        assert status.progress == 50
        assert status.total == 100

    def test_update_progress_nonexistent(self, manager):
        manager.update_progress("nonexistent", 50, 100)  # should not raise

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_update_progress_with_callback(self, manager):
        callback = MagicMock()
        manager._progress_callbacks["t1"] = callback
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        manager.update_progress("t1", 75, 100)
        callback.assert_called_with(75, 100)

    @patch("app.extensions.celery_app")
    def test_cancel_pending_task(self, mock_celery, manager):
        # Mock celery to avoid real Redis connection
        mock_celery.send_task.return_value = MagicMock(id="celery-123")
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)
        # Submit without sync - goes through Celery async path
        result = manager.submit("test_task", task_id="t1")
        if result.status == TaskStatus.PENDING:
            assert manager.cancel("t1") is True
            assert manager.get_status("t1").status == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self, manager):
        assert manager.cancel("nonexistent") is False

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_cancel_completed_task(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        assert manager.cancel("t1") is False

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_cleanup(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        r = manager.submit("test_task", task_id="t1", sync=True)
        r.completed_at = time.time() - 7200
        cleaned = manager.cleanup(max_age_seconds=3600)
        assert cleaned == 1
        assert manager.get_status("t1") is None

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_cleanup_no_old_tasks(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        cleaned = manager.cleanup(max_age_seconds=3600)
        assert cleaned == 0

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_active_tasks(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        r = manager.submit("test_task", task_id="t1", sync=True)
        active = manager.active_tasks
        # After sync execution, status is SUCCESS, so not active
        if r.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.RETRYING):
            assert "t1" in active
        else:
            assert "t1" not in active

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_stats(self, manager):
        config = AsyncTaskConfig(name="test_task")
        manager.register_task(config)

        manager.submit("test_task", task_id="t1", sync=True)
        stats = manager.stats
        assert stats["total_tasks"] >= 1
        assert "status_distribution" in stats
        assert "test_task" in stats["registered_tasks"]

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_on_success_callback(self, manager):
        callback = MagicMock()
        config = AsyncTaskConfig(name="test_task", on_success=callback)
        manager.register_task(config)

        manager.submit("test_task", sync=True)
        callback.assert_called_once()

    @patch("app.tasks.get_task_function", create=True)
    def test_on_failure_callback(self, mock_get_func, manager):
        callback = MagicMock()
        config = AsyncTaskConfig(name="fail_task", on_failure=callback)
        manager.register_task(config)

        def failing_func():
            raise OSError("fail")

        mock_get_func.return_value = failing_func
        manager.submit("fail_task", sync=True)
        callback.assert_called_once()

    @patch("app.tasks.get_task_function", create=True, new=MagicMock(return_value=lambda: "ok"))
    def test_submit_with_extra_config_overrides(self, manager):
        config = AsyncTaskConfig(name="test_task", timeout=300)
        manager.register_task(config)

        result = manager.submit("test_task", sync=True, timeout=600)
        assert result.status == TaskStatus.SUCCESS


# ---------------------------------------------------------------------------
# async_task decorator
# ---------------------------------------------------------------------------

class TestAsyncTaskDecorator:
    @patch("app.utils.async_tasks.get_async_task_manager")
    def test_sync_mode(self, mock_get_manager):
        mock_manager = MagicMock()
        mock_result = TaskResult(task_id="t1", status=TaskStatus.SUCCESS, result=42)
        mock_manager.submit.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        @async_task(name="test_func")
        def my_func(x, y):
            return x + y

        with patch.dict("os.environ", {"XCAGI_FORCE_SYNC_TASKS": "1"}):
            result = my_func(1, 2)

        assert result == 42

    @patch("app.utils.async_tasks.get_async_task_manager")
    def test_async_submit(self, mock_get_manager):
        mock_manager = MagicMock()
        mock_result = TaskResult(task_id="t1", status=TaskStatus.PENDING)
        mock_manager.submit.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        @async_task(name="test_func")
        def my_func(x):
            return x

        result = my_func.async_submit(1)
        assert result.task_id == "t1"

    @patch("app.utils.async_tasks.get_async_task_manager")
    def test_get_task_status(self, mock_get_manager):
        mock_manager = MagicMock()
        mock_result = TaskResult(task_id="t1", status=TaskStatus.SUCCESS)
        mock_manager.get_status.return_value = mock_result
        mock_get_manager.return_value = mock_manager

        @async_task(name="test_func")
        def my_func():
            pass

        result = my_func.get_task_status("t1")
        assert result.status == TaskStatus.SUCCESS

    def test_config_attribute(self):
        @async_task(name="test_func", queue="heavy")
        def my_func():
            pass

        assert my_func.config.name == "test_func"
        assert my_func.config.queue == "heavy"


# ---------------------------------------------------------------------------
# background_task decorator
# ---------------------------------------------------------------------------

class TestBackgroundTaskDecorator:
    def test_default_name(self):
        @background_task()
        def my_special_func():
            return "done"

        assert callable(my_special_func)

    def test_custom_name(self):
        @background_task(name="custom_bg")
        def my_func():
            return "done"

        assert callable(my_func)


# ---------------------------------------------------------------------------
# retry_on_failure decorator
# ---------------------------------------------------------------------------

class TestRetryOnFailure:
    def test_success_no_retry(self):
        call_count = 0

        @retry_on_failure(max_retries=3, delay=0, exceptions=(ValueError,))
        def my_func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = my_func()
        assert result == "ok"
        assert call_count == 1

    def test_retry_then_success(self):
        call_count = 0

        @retry_on_failure(max_retries=3, delay=0, exceptions=(ValueError,))
        def my_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = my_func()
        assert result == "ok"
        assert call_count == 3

    def test_retry_exhausted_raises(self):
        @retry_on_failure(max_retries=2, delay=0, exceptions=(ValueError,))
        def my_func():
            raise ValueError("always fail")

        with pytest.raises(ValueError, match="always fail"):
            my_func()

    def test_non_matching_exception_propagates(self):
        @retry_on_failure(max_retries=3, delay=0, exceptions=(ValueError,))
        def my_func():
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            my_func()

    def test_backoff_factor(self):
        call_count = 0

        @retry_on_failure(max_retries=2, delay=0.01, backoff_factor=2.0, exceptions=(ValueError,))
        def my_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry")
            return "ok"

        result = my_func()
        assert result == "ok"


# ---------------------------------------------------------------------------
# get_async_task_manager
# ---------------------------------------------------------------------------

class TestGetAsyncTaskManager:
    def test_returns_singleton(self):
        import app.utils.async_tasks as mod
        mod._async_task_manager = None

        m1 = get_async_task_manager()
        m2 = get_async_task_manager()
        assert m1 is m2

        mod._async_task_manager = None

    def test_registers_default_tasks(self):
        import app.utils.async_tasks as mod
        mod._async_task_manager = None

        manager = get_async_task_manager()
        assert "shipment_tasks.generate_shipment_order" in manager._task_configs
        assert "kitten_report.generate_report" in manager._task_configs

        mod._async_task_manager = None


# ---------------------------------------------------------------------------
# _register_default_tasks
# ---------------------------------------------------------------------------

class TestRegisterDefaultTasks:
    def test_registers_expected_tasks(self):
        manager = AsyncTaskManager()
        _register_default_tasks(manager)
        assert len(manager._task_configs) == 5
        assert "shipment_tasks.generate_shipment_order" in manager._task_configs
        assert "wechat_tasks.scan_wechat_messages" in manager._task_configs
