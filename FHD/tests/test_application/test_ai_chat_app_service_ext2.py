"""Tests for app.application.ai_chat_app_service — coverage ramp for uncovered branches."""

from __future__ import annotations

import math
import uuid
from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.run_repository import (
    InMemoryAgentRunRepository,
    SQLAlchemyAgentRunRepository,
)
from app.application.ai_chat_app_service import (
    AIChatApplicationService,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.domain.autonomy.risk_types import RiskDecision
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _make_service():
    return AIChatApplicationService()


@pytest.fixture
def dataset_store(tmp_path, monkeypatch):
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    store = tmp_path / "dataset_store.json"
    monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(store))
    monkeypatch.setenv("DATASET_RAG_VECTOR_INDEX_PATH", str(tmp_path / "vectors.sqlite3"))
    monkeypatch.setenv("XCAGI_KNOWLEDGE_DEFAULT_DATASET", "confirmed-import-evidence")
    reset_dataset_rag_app_service_for_tests()
    yield store
    reset_dataset_rag_app_service_for_tests()


class TestInjectExcelVectorContextExtended:
    def test_with_non_dict_context(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", "not a dict")
        assert result == {}

    def test_with_empty_index_id(self):
        service = _make_service()
        result = service._inject_excel_vector_context("hello", {"excel_index_id": ""})
        assert "excel_vector_context" not in result

    def test_query_exception(self):
        service = _make_service()
        mock_svc = Mock()
        mock_svc.query.side_effect = RuntimeError("fail")
        with patch("app.application.get_excel_vector_search_app_service", return_value=mock_svc):
            result = service._inject_excel_vector_context("hello", {"excel_index_id": "idx1"})
        assert "excel_vector_context" not in result
