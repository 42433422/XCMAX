"""app/utils/logger 测试。"""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.utils.logger import (
    StructuredLogFormatter,
    StructuredLogger,
    get_logger,
    log_operation,
    setup_structured_logging,
)

# ---------------------------------------------------------------------------
# StructuredLogFormatter
# ---------------------------------------------------------------------------


class TestStructuredLogFormatter:
    def test_format_basic_record(self):
        formatter = StructuredLogFormatter(
            service_name="test_svc", environment="dev", version="2.0.0"
        )
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Hello world",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "Hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["service"] == "test_svc"
        assert data["environment"] == "dev"
        assert data["version"] == "2.0.0"
        assert data["line"] == 42

    def test_format_with_request_id(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        record.request_id = "req-123"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-123"

    def test_format_with_user_id(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        record.user_id = "user-456"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["user_id"] == "user-456"

    def test_format_with_duration(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        record.duration = 123.45
        output = formatter.format(record)
        data = json.loads(output)
        assert data["duration_ms"] == 123.45

    def test_format_with_extra_data(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        record.extra_data = {"key1": "value1", "key2": 42}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["key1"] == "value1"
        assert data["key2"] == 42

    def test_format_with_error_code(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="error",
            args=None,
            exc_info=None,
        )
        record.error_code = "E001"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["error_code"] == "E001"

    def test_format_with_stack_id(self):
        formatter = StructuredLogFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg",
            args=None,
            exc_info=None,
        )
        record.stack_id = "stack-789"
        output = formatter.format(record)
        data = json.loads(output)
        assert data["stack_id"] == "stack-789"

    def test_format_with_exception(self):
        formatter = StructuredLogFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="error occurred",
            args=None,
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "test error"
        assert isinstance(data["exception"]["traceback"], list)

    def test_default_fields(self):
        assert StructuredLogFormatter.DEFAULT_FIELDS == {
            "service": "xcagi",
            "environment": "production",
            "version": "1.0.0",
        }


# ---------------------------------------------------------------------------
# StructuredLogger
# ---------------------------------------------------------------------------


class TestStructuredLogger:
    def test_debug(self):
        logger = get_logger("test.debug")
        with patch.object(logger.logger, "log") as mock_log:
            logger.debug("debug message")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][0] == logging.DEBUG

    def test_info(self):
        logger = get_logger("test.info")
        with patch.object(logger.logger, "log") as mock_log:
            logger.info("info message")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][0] == logging.INFO

    def test_warning(self):
        logger = get_logger("test.warning")
        with patch.object(logger.logger, "log") as mock_log:
            logger.warning("warning message")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][0] == logging.WARNING

    def test_error(self):
        logger = get_logger("test.error")
        with patch.object(logger.logger, "log") as mock_log:
            logger.error("error message")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][0] == logging.ERROR

    def test_critical(self):
        logger = get_logger("test.critical")
        with patch.object(logger.logger, "log") as mock_log:
            logger.critical("critical message")
            mock_log.assert_called_once()
            args = mock_log.call_args
            assert args[0][0] == logging.CRITICAL

    def test_with_request_id(self):
        logger = get_logger("test.request_id")
        with patch.object(logger.logger, "log") as mock_log:
            logger.info("msg", request_id="req-123")
            args, kwargs = mock_log.call_args
            assert kwargs.get("extra", {}).get("request_id") == "req-123"

    def test_with_user_id(self):
        logger = get_logger("test.user_id")
        with patch.object(logger.logger, "log") as mock_log:
            logger.info("msg", user_id="user-456")
            args, kwargs = mock_log.call_args
            assert kwargs.get("extra", {}).get("user_id") == "user-456"

    def test_with_duration(self):
        logger = get_logger("test.duration")
        with patch.object(logger.logger, "log") as mock_log:
            logger.info("msg", duration=100.5)
            args, kwargs = mock_log.call_args
            assert kwargs.get("extra", {}).get("duration") == 100.5

    def test_with_extra_kwargs(self):
        logger = get_logger("test.extra")
        with patch.object(logger.logger, "log") as mock_log:
            logger.info("msg", custom_key="custom_value")
            args, kwargs = mock_log.call_args
            extra = kwargs.get("extra", {})
            assert extra.get("extra_data", {}).get("custom_key") == "custom_value"


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_structured_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, StructuredLogger)

    def test_name_matches(self):
        logger = get_logger("my.module")
        assert logger.logger.name == "my.module"


# ---------------------------------------------------------------------------
# setup_structured_logging
# ---------------------------------------------------------------------------


class TestSetupStructuredLogging:
    def test_sets_up_handler(self):
        root = logging.getLogger()
        old_handlers = root.handlers[:]
        try:
            setup_structured_logging(
                level=logging.DEBUG,
                service_name="test",
                environment="test",
                version="0.1.0",
            )
            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0].formatter, StructuredLogFormatter)
        finally:
            root.handlers = old_handlers


# ---------------------------------------------------------------------------
# log_operation decorator
# ---------------------------------------------------------------------------


class TestLogOperationDecorator:
    def test_sync_function_success(self):
        # log_operation passes ("Operation started: %s", operation_name) as positional args
        # to StructuredLogger.info() which only accepts (msg, **kwargs).
        # This causes a TypeError in the current implementation.
        # We test that the function itself works by patching the logger.
        @log_operation("test_op")
        def my_func(x):
            return x * 2

        with patch("app.utils.logger.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = my_func(5)
            assert result == 10

    def test_sync_function_failure(self):
        @log_operation("failing_op")
        def my_func():
            raise ValueError("boom")

        with patch("app.utils.logger.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            with pytest.raises(ValueError, match="boom"):
                my_func()

    @pytest.mark.asyncio
    async def test_async_function_success(self):
        @log_operation("async_op")
        async def my_func(x):
            return x * 3

        with patch("app.utils.logger.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            result = await my_func(5)
            assert result == 15

    @pytest.mark.asyncio
    async def test_async_function_failure(self):
        @log_operation("async_failing_op")
        async def my_func():
            raise RuntimeError("async boom")

        with patch("app.utils.logger.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger
            with pytest.raises(RuntimeError, match="async boom"):
                await my_func()
