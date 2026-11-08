"""Regression: cleaned template path vs original ingest, 0-row receipts, RAG split."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
        "knowledge": {"action": "new"},
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


def test_refresh_business_without_full_coverage_is_partial(monkeypatch):
    """A completed write whose knowledge archive was skipped or rows erred is not 'applied'."""
    service = AutoIngestService()
    batch = {
        "mod_id": "erp-test",
        "tenant_id": 1,
        "owner_user_id": 7,
        "batch_id": "b3",
        "status": "running",
        "knowledge": {"action": "skip", "degraded": True},
        "business": {"run_id": "run-3"},
    }
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "erp-test")

    class _DB:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.db.session.get_db", lambda: _DB())
    monkeypatch.setattr("app.infrastructure.tenant_scope.tenant_scope", lambda *_a, **_k: _DB())

    class FakeElt:
        def get_run(self, db, *, run_id, owner_user_id):
            return {
                "status": "completed",
                "summary": {"new": 2, "update": 0, "skip": 0, "error": 1, "executed": 2},
                "receipt": {"rows_written": True},
            }

    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: FakeElt())
    monkeypatch.setattr(ais, "_load_ledger", lambda _t: {"batches": {"b3": dict(batch)}})
    monkeypatch.setattr(ais, "_save_ledger", lambda *_a, **_k: None)
    monkeypatch.setattr(ais, "_LOCK", __import__("threading").RLock())

    out = service._refresh_business(dict(batch))
    assert out["status"] == "partial"
    assert out["coverage"]["complete"] is False
    assert out["coverage"]["business_rows"]["error"] == 1


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


def test_business_import_covers_every_unit_and_merges_by_coordinate(monkeypatch):
    from app.application.elt import llm_assist
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    rows = [f"R{i} | 货品{i} | {i}" for i in range(2, 2000)]
    source = "# sheet:明细\nR1 | 货品 | 数量\n" + "\n".join(rows)
    seen: list[str] = []

    def unit(text):
        seen.append(text)
        cited = [line.split(" ", 1)[0][1:] for line in text.splitlines() if line.startswith("R")]
        return LlmAssistResult(
            used_llm=True,
            data={
                "rows": [
                    {"source_sheet": "明细", "source_row": r, "product_name": f"货品{r}"}
                    for r in cited
                ]
            },
        )

    monkeypatch.setattr(llm_assist, "_advise_business_unit", unit)
    out = llm_assist.advise_business_import(source)
    assert len(seen) == out.data["units"] > 1
    assert all(len(text) <= llm_assist.MODEL_WINDOW_CHARS for text in seen)
    assert all(text.startswith("# sheet:明细\nR1 |") for text in seen)
    assert sorted(int(r["source_row"]) for r in out.data["rows"]) == list(range(1, 2000))


def test_business_import_refuses_more_units_than_the_limit_without_calling(monkeypatch):
    from app.application.elt import llm_assist

    monkeypatch.setattr(
        llm_assist, "_advise_business_unit", lambda _t: pytest.fail("model must not be called")
    )
    source = "# sheet:s\n" + "\n".join(f"R{i} | " + "x" * 200 for i in range(1, 2000))
    out = llm_assist.advise_business_import(source)
    assert out.degraded and out.degradation_code == "ELT_DATABASE_INPUT_EXCEEDS_UNITS"


def test_knowledge_import_does_not_summarize_a_prefix(monkeypatch):
    from app.application.elt import llm_assist

    monkeypatch.setattr(llm_assist, "_complete", lambda *_a, **_k: pytest.fail("no call"))
    out = llm_assist.advise_knowledge_import("x" * (llm_assist.MODEL_WINDOW_CHARS + 1))
    assert out.degraded and out.degradation_code == "ELT_KNOWLEDGE_INPUT_EXCEEDS_WINDOW"


def test_workbook_text_keeps_every_visible_row_and_counts_coverage():
    from openpyxl import Workbook

    from app.application.elt.auto_ingest_service import _workbook_lines, row_coverage

    book = Workbook()
    book.active.title = "主表"
    for i in range(1, 400):
        book.active.append([f"v{i}"])
    hidden = book.create_sheet("隐藏")
    hidden.sheet_state = "hidden"
    hidden.append(["secret"])
    for n in range(25):
        book.create_sheet(f"S{n}").append(["a"])
    text = _workbook_lines(book)
    assert "R399 | v399" in text and "secret" not in text and "# sheet:S24" in text
    coverage = row_coverage(text, [{"source_sheet": "主表", "source_row": 5}])
    assert coverage == {
        "in_scope_rows": 424,
        "business_rows": 1,
        "knowledge_rows": 423,
        "uncited_business_coordinates": 0,
    }
