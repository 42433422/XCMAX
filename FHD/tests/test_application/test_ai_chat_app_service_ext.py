"""Tests for app.application.ai_chat_app_service — coverage ramp."""

import math
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
)
from tests.test_application.ai_chat_test_helpers import (
    _make_svc as _make_service,
)

# Helper: create service with all heavy deps mocked


class TestInjectExcelVectorContext:
    def test_no_index_id(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", {"other_key": "val"})
        assert result == {"other_key": "val"}

    def test_non_dict_context(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", None)
        assert result == {}

    def test_with_index_id_success(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": True, "hits": [{"text": "hit1"}]}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" in result

    def test_with_index_id_failure(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.return_value = {"success": False}
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" not in result


class TestProcessChat:
    def test_empty_message(self):
        service = _make_service()
        result = service.process_chat("u1", "")
        assert result["success"] is False
        assert "不能为空" in result["message"]
