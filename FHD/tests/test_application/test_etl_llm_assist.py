from __future__ import annotations

import threading
import time

import pytest

from app.application.etl.llm_assist import (
    LlmAssistResult,
    _compact_document_evidence,
    advise_document_understanding,
    advise_field_mappings,
    clear_etl_llm_circuit,
    etl_document_timeout_seconds,
    etl_llm_timeout_seconds,
)
from app.application.etl.llm_session_provider import (
    SessionMarketProvider,
    bind_etl_llm_owner,
    current_etl_llm_owner,
    reset_etl_llm_owner,
)
from app.infrastructure.llm.structured_output import StructuredResult


@pytest.fixture(autouse=True)
def _clear_etl_llm_circuit_between_tests():
    clear_etl_llm_circuit()
    yield
    clear_etl_llm_circuit()


def test_etl_structured_assist_uses_software_conversation_provider(monkeypatch):
    software_service = object()
    captured = {}
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, software_service, None),
    )

    def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return StructuredResult(
            data={
                "mappings": [
                    {
                        "source": "货品",
                        "target": "name",
                        "transform": "trim",
                        "confidence": 0.93,
                        "reason": "货品列是产品名称",
                    }
                ]
            },
            attempts=1,
            repaired=False,
            model="software-model",
        )

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        fake_complete,
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": ["品名"],
            }
        ],
    )

    assert result.used_llm is True
    assert result.model == "software-model"
    assert result.data["mappings"][0]["target"] == "name"
    assert captured["conversation_service"] is software_service
    assert captured["provider"] is None
    assert captured["profile"] == "etl"
    assert captured["max_repairs"] == 0


def test_document_understanding_localizes_model_prose(monkeypatch):
    evidence = {
        "file_name": "采购订单.xlsx",
        "sheets": [
            {
                "name": "采购订单",
                "max_row": 3,
                "max_column": 2,
                "rows": [
                    {
                        "row": 1,
                        "cells": [
                            {
                                "id": "s1:r1:c1",
                                "coordinate": "A1",
                                "row": 1,
                                "column": 1,
                                "sheet": "采购订单",
                                "text": "品名",
                                "value": "品名",
                                "value_type": "string",
                            },
                            {
                                "id": "s1:r1:c2",
                                "coordinate": "B1",
                                "row": 1,
                                "column": 2,
                                "sheet": "采购订单",
                                "text": "金额",
                                "value": "金额",
                                "value_type": "string",
                            },
                        ],
                    }
                ],
            }
        ],
        "cell_index": {
            "s1:r1:c1": {
                "id": "s1:r1:c1",
                "coordinate": "A1",
                "row": 1,
                "column": 1,
                "sheet": "采购订单",
                "text": "品名",
                "value": "品名",
            },
            "s1:r1:c2": {
                "id": "s1:r1:c2",
                "coordinate": "B1",
                "row": 1,
                "column": 2,
                "sheet": "采购订单",
                "text": "金额",
                "value": "金额",
            },
        },
        "table_candidates": [],
        "key_value_candidates": [],
    }
    monkeypatch.setattr(
        "app.application.etl.llm_assist._complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            data={
                "file_structure": "single_document",
                "summary": "Single purchase order document (采购订单) with a detail table.",
                "documents": [
                    {
                        "document_id": "po-1",
                        "document_type": "purchase_order",
                        "sheet": "采购订单",
                        "title_cell_ids": [],
                        "header_fields": [],
                        "tables": [],
                        "total_amount_cell_id": "",
                        "confidence": 0.95,
                        "requires_review": True,
                        "issues": [
                            "No total amount row present; sum of line amounts would be 157."
                        ],
                    }
                ],
            },
        ),
    )

    result = advise_document_understanding(evidence)

    assert result.data["summary"] == (
        "识别为采购订单，共 1 张单；已定位单据头和 0 个明细表，等待人工确认。"
    )
    assert result.data["documents"][0]["issues"][0]["message"] == (
        "单据中未找到明确的合计金额单元格；按明细金额计算合计为 157，请人工核对。"
    )


def test_llm_mapping_rejects_invented_source_and_target(monkeypatch):
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            data={
                "mappings": [
                    {
                        "source": "不存在列",
                        "target": "name",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                    {
                        "source": "货品",
                        "target": "dangerous_field",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                ]
            },
        ),
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    )

    assert result.data["mappings"] == []


def test_etl_uses_only_current_owner_market_session(monkeypatch):
    captured = {}
    owner_token = bind_etl_llm_owner(42)
    try:
        monkeypatch.setattr(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            lambda: object(),
        )

        def fake_latest_session_market_token(*, user_id):
            captured["user_id"] = user_id
            return "owner-market-token"

        monkeypatch.setattr(
            "app.fastapi_routes.market_account.latest_session_market_token",
            fake_latest_session_market_token,
        )
        from app.application.etl.llm_assist import _active_software_llm

        configured, conversation_service, provider = _active_software_llm()
    finally:
        reset_etl_llm_owner(owner_token)

    assert configured is True
    assert conversation_service is None
    assert isinstance(provider, SessionMarketProvider)
    assert captured["user_id"] == 42


def test_etl_owner_context_resets():
    token = bind_etl_llm_owner(7)
    assert current_etl_llm_owner() == 7
    reset_etl_llm_owner(token)
    assert current_etl_llm_owner() is None


def test_etl_llm_timeout_allows_account_backed_structured_requests(monkeypatch):
    monkeypatch.delenv("FHD_ETL_LLM_TIMEOUT", raising=False)
    assert etl_llm_timeout_seconds() == 30.0

    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "1")
    assert etl_llm_timeout_seconds() == 3.0

    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "120")
    assert etl_llm_timeout_seconds() == 90.0

    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "invalid")
    assert etl_llm_timeout_seconds() == 30.0


def test_large_workbook_uses_compact_prompt_and_longer_document_budget(monkeypatch):
    monkeypatch.delenv("FHD_ETL_LLM_DOCUMENT_TIMEOUT", raising=False)
    sheets = []
    cell_index = {}
    for sheet_index in range(1, 12):
        rows = []
        for row_number in range(1, 31):
            cells = []
            for column in range(1, 9):
                cell_id = f"s{sheet_index}:r{row_number}:c{column}"
                cell = {
                    "id": cell_id,
                    "text": f"值-{sheet_index}-{row_number}-{column}",
                    "value_type": "text",
                }
                cells.append(cell)
                cell_index[cell_id] = cell
            rows.append({"row": row_number, "cells": cells})
        sheets.append(
            {
                "name": f"Sheet{sheet_index}",
                "max_row": 30,
                "max_column": 8,
                "rows": rows,
            }
        )
    evidence = {
        "sheets": sheets,
        "cell_index": cell_index,
        "table_candidates": [],
        "key_value_candidates": [],
    }

    compact = _compact_document_evidence(evidence)
    compact_cells = sum(len(row[1]) for sheet in compact["sheets"] for row in sheet["rows"])

    assert len(compact["sheets"]) == 11
    assert compact_cells <= 960
    assert etl_document_timeout_seconds(evidence) >= 120.0
    assert etl_document_timeout_seconds(evidence) > etl_llm_timeout_seconds()


def test_large_workbook_document_understanding_batches_and_merges(monkeypatch):
    sheets = []
    cell_index = {}
    for sheet_index in range(1, 10):
        sheet_name = f"Sheet{sheet_index}"
        cell_id = f"s{sheet_index}:r1:c1"
        cell = {
            "id": cell_id,
            "sheet": sheet_name,
            "coordinate": "A1",
            "row": 1,
            "column": 1,
            "text": "汇总表",
            "value": "汇总表",
            "value_type": "text",
        }
        sheets.append(
            {
                "name": sheet_name,
                "max_row": 1,
                "max_column": 1,
                "rows": [{"row": 1, "cells": [cell]}],
            }
        )
        cell_index[cell_id] = cell
    evidence = {
        "file_name": "large.xlsx",
        "sheets": sheets,
        "cell_index": cell_index,
        "table_candidates": [],
        "key_value_candidates": [],
    }
    calls = []
    progress_events = []

    def complete(messages, **_kwargs):
        payload = __import__("json").loads(messages[-1]["content"])
        batch_sheets = payload["workbook_evidence"]["sheets"]
        calls.append([sheet["name"] for sheet in batch_sheets])
        return LlmAssistResult(
            used_llm=True,
            model="software-model",
            billing={"request": len(calls)},
            data={
                "file_structure": "one_per_sheet",
                "summary": "批次识别完成",
                "documents": [
                    {
                        "document_id": f"doc-{index}",
                        "document_type": "generic_table",
                        "sheet": sheet["name"],
                        "title_cell_ids": [],
                        "header_fields": [],
                        "tables": [],
                        "total_amount_cell_id": "",
                        "confidence": 0.8,
                        "requires_review": True,
                        "issues": [],
                    }
                    for index, sheet in enumerate(batch_sheets, start=1)
                ],
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)

    result = advise_document_understanding(
        evidence,
        progress_callback=lambda completed, total: progress_events.append((completed, total)),
    )

    assert [len(batch) for batch in calls] == [4, 4, 1]
    assert progress_events == [(1, 3), (2, 3), (3, 3)]
    assert len(result.data["documents"]) == 9
    assert result.data["file_structure"] == "one_per_sheet"
    assert result.billing["batch_count"] == 3


def test_document_understanding_keeps_successful_batches_when_later_batch_degrades(
    monkeypatch,
):
    sheets = []
    cell_index = {}
    for index in range(1, 6):
        cell = {
            "id": f"s{index}:r1:c1",
            "sheet": f"Sheet{index}",
            "coordinate": "A1",
            "row": 1,
            "column": 1,
            "text": "业务表",
            "value": "业务表",
            "value_type": "text",
        }
        sheets.append(
            {
                "name": f"Sheet{index}",
                "max_row": 1,
                "max_column": 1,
                "rows": [{"row": 1, "cells": [cell]}],
            }
        )
        cell_index[cell["id"]] = cell
    evidence = {
        "file_name": "partial.xlsx",
        "sheets": sheets,
        "cell_index": cell_index,
        "table_candidates": [],
        "key_value_candidates": [],
    }
    calls = 0
    progress_events = []

    def complete(messages, **_kwargs):
        nonlocal calls
        calls += 1
        payload = __import__("json").loads(messages[-1]["content"])
        batch_sheets = payload["workbook_evidence"]["sheets"]
        if calls == 2:
            return LlmAssistResult(
                used_llm=True,
                degraded=True,
                degradation_code="ETL_LLM_OUTPUT_INVALID",
            )
        return LlmAssistResult(
            used_llm=True,
            model="software-model",
            data={
                "file_structure": "one_per_sheet",
                "summary": "第一批识别完成",
                "documents": [
                    {
                        "document_id": f"doc-{sheet['name']}",
                        "document_type": "generic_table",
                        "sheet": sheet["name"],
                        "title_cell_ids": [],
                        "header_fields": [],
                        "tables": [],
                        "total_amount_cell_id": "",
                        "confidence": 0.8,
                        "requires_review": True,
                        "issues": [],
                    }
                    for sheet in batch_sheets
                ],
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)

    result = advise_document_understanding(
        evidence,
        progress_callback=lambda completed, total: progress_events.append((completed, total)),
    )

    assert result.degraded is True
    assert result.degradation_code == "ETL_LLM_OUTPUT_INVALID"
    assert [item["sheet"] for item in result.data["documents"]] == [
        "Sheet1",
        "Sheet2",
        "Sheet3",
        "Sheet4",
    ]
    assert progress_events == [(1, 2), (2, 2)]


def test_document_understanding_shares_success_across_linked_previews(monkeypatch):
    evidence_hash = "same-upload-evidence"
    cell = {
        "id": "s1:r1:c1",
        "sheet": "发货单",
        "coordinate": "A1",
        "row": 1,
        "column": 1,
        "text": "发货单",
        "value": "发货单",
        "value_type": "text",
    }
    evidence = {
        "file_name": "发货单.xlsx",
        "evidence_hash": evidence_hash,
        "sheets": [
            {
                "name": "发货单",
                "max_row": 1,
                "max_column": 1,
                "rows": [{"row": 1, "cells": [cell]}],
            }
        ],
        "cell_index": {cell["id"]: cell},
        "table_candidates": [],
        "key_value_candidates": [],
    }
    calls = 0
    first_request_started = threading.Event()
    release_first_request = threading.Event()
    results = []

    def complete(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        first_request_started.set()
        release_first_request.wait(timeout=1.0)
        return LlmAssistResult(
            used_llm=True,
            model="software-model",
            billing={"request": calls},
            data={
                "file_structure": "single_document",
                "summary": "识别完成",
                "documents": [
                    {
                        "document_id": "delivery-1",
                        "document_type": "delivery_note",
                        "sheet": "发货单",
                        "title_cell_ids": [cell["id"]],
                        "header_fields": [],
                        "tables": [],
                        "total_amount_cell_id": "",
                        "confidence": 0.9,
                        "requires_review": True,
                        "issues": [],
                    }
                ],
            },
        )

    monkeypatch.setattr("app.application.etl.llm_assist._complete", complete)

    def advise() -> None:
        owner_token = bind_etl_llm_owner(42)
        try:
            results.append(advise_document_understanding(evidence))
        finally:
            reset_etl_llm_owner(owner_token)

    first = threading.Thread(target=advise)
    second = threading.Thread(target=advise)
    first.start()
    assert first_request_started.wait(timeout=0.5)
    second.start()
    threading.Event().wait(0.03)
    release_first_request.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == 1
    assert len(results) == 2
    assert all(result.model == "software-model" for result in results)
    assert sorted(bool(result.billing.get("reused")) for result in results) == [False, True]


def test_etl_reports_stable_quota_degradation(monkeypatch):
    calls = 0
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )

    def quota_exhausted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("upstream 429 quota exhausted")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        quota_exhausted,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }
    first = advise_field_mappings(**kwargs)
    second = advise_field_mappings(**kwargs)

    assert first.used_llm is True
    assert first.degraded is True
    assert first.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
    # One quota response must end the structured attempt and make every later
    # mapping/region/row advisory phase fall back immediately for this owner.
    assert calls == 1
    assert second.used_llm is False
    assert second.degraded is True
    assert second.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"


def test_etl_llm_timeout_returns_deterministic_fallback_without_repeat(monkeypatch):
    calls = 0
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )
    monkeypatch.setattr(
        "app.application.etl.llm_assist.etl_llm_timeout_seconds",
        lambda: 0.05,
    )

    def slow_complete(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(timeout=1.0)
        return StructuredResult(data={"mappings": []}, attempts=1, repaired=False)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        slow_complete,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }
    started_at = time.monotonic()
    try:
        first = advise_field_mappings(**kwargs)
        elapsed = time.monotonic() - started_at
        second = advise_field_mappings(**kwargs)
    finally:
        release.set()

    assert entered.is_set()
    assert elapsed < 0.25
    assert first.used_llm is True
    assert first.degraded is True
    assert first.degradation_code == "ETL_LLM_UNAVAILABLE"
    assert calls == 1
    assert second.used_llm is False
    assert second.degradation_code == "ETL_LLM_UNAVAILABLE"


def test_owner_circuit_collapses_concurrent_quota_advice(monkeypatch):
    calls = 0
    first_request_started = threading.Event()
    release_first_request = threading.Event()
    results = []
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )

    def quota_exhausted(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        first_request_started.set()
        release_first_request.wait(timeout=1.0)
        raise RuntimeError("upstream 429 quota exhausted")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        quota_exhausted,
    )
    kwargs = {
        "headers": ["货品"],
        "samples": {"货品": ["底漆"]},
        "target_fields": [
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    }

    def advise() -> None:
        results.append(advise_field_mappings(**kwargs))

    first = threading.Thread(target=advise)
    second = threading.Thread(target=advise)
    first.start()
    assert first_request_started.wait(timeout=0.5)
    second.start()
    try:
        # The second preview can reach _complete while the first provider call
        # is pending; it must wait for the owner gate, then see the breaker.
        threading.Event().wait(0.03)
    finally:
        release_first_request.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == 1
    assert len(results) == 2
    assert all(result.degraded for result in results)
    assert {result.degradation_code for result in results} == {"ETL_LLM_QUOTA_EXHAUSTED"}
