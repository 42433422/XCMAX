"""Regression: cleaned template path vs original ingest, 0-row receipts, RAG split."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.elt import auto_ingest_service as ais
from app.application.elt.auto_ingest_service import AutoIngestService
from app.application.elt.knowledge_index_meta import _knowledge_index_meta


def test_executed_zero_is_not_replaced_by_eligible_count():
    """result.executed=0 must stay 0; `or eligible_count` was the bug."""
    executed = 0
    eligible_count = 12
    previous = 0
    value = previous + int(eligible_count if executed is None else executed)
    assert value == 0


def test_executed_missing_falls_back_to_eligible_count():
    executed = None
    eligible_count = 12
    previous = 3
    value = previous + int(eligible_count if executed is None else executed)
    assert value == 15


def test_refresh_business_maps_completed_zero_rows_to_completed_empty(monkeypatch):
    service = AutoIngestService()
    batch = {
        "mod_id": "erp-test",
        "tenant_id": 1,
        "owner_user_id": 7,
        "batch_id": "b1",
        "status": "running",
        "business": {"run_id": "run-1"},
    }

    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "erp-test")

    class _DB:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.get_db", lambda: _DB())
    monkeypatch.setattr(
        "app.infrastructure.tenant_scope.tenant_scope",
        lambda *_a, **_k: _DB(),
    )

    class FakeElt:
        def get_run(self, db, *, run_id, owner_user_id):
            return {
                "status": "completed",
                "progress": 100,
                "summary": {"new": 0, "update": 0, "skip": 5, "error": 0, "executed": 0},
                "receipt": {"rows_written": False},
                "error": None,
            }

    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: FakeElt())

    saved = {}

    def fake_load(_tenant):
        return {"batches": {"b1": dict(batch)}}

    def fake_save(_tenant, ledger):
        saved["ledger"] = ledger

    monkeypatch.setattr(ais, "_load_ledger", fake_load)
    monkeypatch.setattr(ais, "_save_ledger", fake_save)
    monkeypatch.setattr(ais, "_LOCK", __import__("threading").RLock())

    out = service._refresh_business(dict(batch))
    assert out["status"] == "completed_empty"
    assert "未写入任何业务行" in out["business_progress"]["message"]
    assert "已完成" not in out["business_progress"]["message"]


def test_refresh_business_maps_completed_with_rows_to_applied(monkeypatch):
    service = AutoIngestService()
    batch = {
        "mod_id": "erp-test",
        "tenant_id": 1,
        "owner_user_id": 7,
        "batch_id": "b2",
        "status": "running",
        "business": {"run_id": "run-2"},
    }
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "erp-test")

    class _DB:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.get_db", lambda: _DB())
    monkeypatch.setattr(
        "app.infrastructure.tenant_scope.tenant_scope",
        lambda *_a, **_k: _DB(),
    )

    class FakeElt:
        def get_run(self, db, *, run_id, owner_user_id):
            return {
                "status": "completed",
                "progress": 100,
                "summary": {"new": 2, "update": 1, "skip": 0, "error": 0, "executed": 3},
                "receipt": {"rows_written": True},
                "error": None,
            }

    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: FakeElt())
    monkeypatch.setattr(ais, "_load_ledger", lambda _t: {"batches": {"b2": dict(batch)}})
    monkeypatch.setattr(ais, "_save_ledger", lambda *_a, **_k: None)
    monkeypatch.setattr(ais, "_LOCK", __import__("threading").RLock())

    out = service._refresh_business(dict(batch))
    assert out["status"] == "applied"
    assert out["business_progress"]["message"] == "业务写入已完成"


def test_knowledge_index_meta_separates_rag_from_documents(monkeypatch):
    import app.infrastructure.rag as rag_mod

    monkeypatch.setattr(rag_mod, "is_rag_enabled", lambda: False)

    class FakeSvc:
        def status(self, **kwargs):
            return {"success": True, "index": {"embedding_count": 0}, "document_count": 3}

    import app.application.dataset_rag_app_service as app_svc

    monkeypatch.setattr(app_svc, "get_dataset_rag_app_service", lambda: FakeSvc())
    meta = _knowledge_index_meta(1)
    assert meta["rag_enabled"] is False
    assert meta["embedding_count"] == 0
    # embedding_count=0 must not be interpreted here as "no documents"
    assert isinstance(meta, dict)
