"""COVERAGE_RAMP Phase 2 (p2-p3-ext): planner tools, spreadsheet reader,
ai_chat helpers, ocr cache, rag semantic chunker fixed, contexts notifier."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.ai_chat_app_service import (
    AIChatApplicationService,
    _skip_pro_excel_deterministic_import,
)
from app.application.tools.workflow import (
    _read_excel_dataframe,
)
from app.infrastructure.rag.rag_service import RagQuery
from app.infrastructure.rag.semantic_chunker import SemanticChunker

# ---------------------------------------------------------------------------
# spreadsheet reader
# ---------------------------------------------------------------------------


@patch("app.application.tools.workflow_tools.excel_analysis.pd.read_excel")
def test_read_excel_dataframe_passes_header(mock_read: MagicMock, tmp_path) -> None:
    fp = tmp_path / "t.xlsx"
    fp.write_bytes(b"x")
    mock_read.return_value = pd.DataFrame({"a": [1]})
    df = _read_excel_dataframe(Path(fp), sheet_name="S1", header_row_1based=2)
    assert len(df) == 1
    mock_read.assert_called_once_with(fp, engine="openpyxl", sheet_name="S1", header=1)


# ---------------------------------------------------------------------------
# ai_chat_app_service helpers
# ---------------------------------------------------------------------------


def test_skip_pro_excel_deterministic_import_context() -> None:
    assert _skip_pro_excel_deterministic_import({"excel_import_ai_decides": True}) is True
    assert (
        _skip_pro_excel_deterministic_import({"excel_import_use_deterministic_shortcut": True})
        is False
    )


def test_skip_pro_excel_deterministic_import_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT", "1")
    assert _skip_pro_excel_deterministic_import({}) is True


def test_ai_chat_service_instantiation() -> None:
    svc = AIChatApplicationService()
    assert svc is not None


# ---------------------------------------------------------------------------
# rag semantic + query dataclass
# ---------------------------------------------------------------------------


def test_semantic_chunker_split_by_fixed_windows() -> None:
    chunker = SemanticChunker(embedder=None, max_chunk_chars=50, min_chunk_chars=10)
    text = "段落一内容。" * 10 + "段落二内容。" * 10
    chunks = chunker.split_by_fixed(text)
    assert len(chunks) >= 1
    assert all(c.char_start <= c.char_end for c in chunks)


def test_rag_query_dataclass() -> None:
    q = RagQuery(user_message="什么是发货单", knowledge_text="发货单说明")
    assert q.user_message == "什么是发货单"
