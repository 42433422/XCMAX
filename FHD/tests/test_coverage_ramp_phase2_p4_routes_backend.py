"""COVERAGE_RAMP Phase 2 (p2-p4): persistence stores (mocked DB) + di/contexts helpers."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.contexts.context_notifier import get_context_notifier
from app.infrastructure.persistence.extract_log_store_impl import SQLAlchemyExtractLogStore


def _fake_extract_row(**kwargs):
    defaults = {
        "id": 1,
        "file_name": "demo.xlsx",
        "file_path": "/tmp/demo.xlsx",
        "data_type": "product",
        "total_rows": 10,
        "valid_rows": 8,
        "imported_rows": 7,
        "skipped_rows": 1,
        "failed_rows": 0,
        "status": "done",
        "error_message": None,
        "field_mapping": json.dumps({"a": "b"}),
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@contextmanager
def _mock_extract_db(*, fetchall=None, fetchone=None, lastrowid=99, rowcount=3):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall or []
    result.fetchone.return_value = fetchone
    result.lastrowid = lastrowid
    result.rowcount = rowcount
    db.execute.return_value = result

    @contextmanager
    def fake_get_db():
        yield db

    with patch("app.infrastructure.persistence.extract_log_store_impl.get_db", fake_get_db):
        yield db


def test_extract_log_find_all_unit_filter() -> None:
    rows = [
        _fake_extract_row(id=1, file_name="七彩_products.xlsx"),
        _fake_extract_row(id=2, file_name="other.xlsx"),
    ]
    with _mock_extract_db(fetchall=rows):
        out = SQLAlchemyExtractLogStore().find_all(page=1, per_page=10, unit_name="七彩")
    assert out["success"] is True
    assert out["total"] == 1


def test_extract_log_create_success() -> None:
    with _mock_extract_db(lastrowid=42):
        out = SQLAlchemyExtractLogStore().create(
            {
                "file_name": "new.xlsx",
                "file_path": "/tmp/new.xlsx",
                "data_type": "customers",
                "total_rows": 5,
                "field_mapping": {"name": "名称"},
            }
        )
    assert out["success"] is True
    assert out["log_id"] == 42


def test_extract_log_delete_success() -> None:
    with _mock_extract_db(rowcount=1):
        out = SQLAlchemyExtractLogStore().delete(1)
    assert out["success"] is True


def test_context_notifier_default_none() -> None:
    assert get_context_notifier() is None
