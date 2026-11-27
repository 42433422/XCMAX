"""Unmatched files must never block a batch: AI infers the schema or we finish clean."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.application.elt.target_detection import detect_elt_target
from app.application.elt.targets import get_adapter
from app.application.elt.targets.batch import AbnormalAdapter
from app.application.elt.targets.dynamic import DynamicTableAdapter
from app.db import SessionLocal
from app.infrastructure.tenant_scope import tenant_scope


def _csv(tmp_path: Path, name: str, rows: list[str]) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Put test files where owner-scoped ELT reads are allowed."""
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_app_data_dir", lambda **_kwargs: str(tmp_path)
    )
    target = tmp_path / "elt" / "uploads" / "1" / "7"
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_abnormal_adapter_finishes_without_blocking_rows():
    adapter = AbnormalAdapter()
    decision = adapter.preview(None, {"a": "1"}, allowed_update_fields=set(), context={})
    assert decision.action == "skip"
    assert decision.reason == "no_business_table"
    assert [issue["severity"] for issue in decision.issues] == ["info"]
    assert adapter.execute_batch(iter([{"a": "1"}]), {})["executed"] == 0


def test_dynamic_adapter_is_registered():
    assert isinstance(get_adapter("dynamic_table"), DynamicTableAdapter)


def test_unmatched_csv_falls_back_to_ai_schema(upload_dir, monkeypatch):
    monkeypatch.setenv("FHD_ELT_LLM_CLASSIFY_TESTS", "1")
    monkeypatch.setattr("app.application.elt.llm_assist.elt_llm_enabled", lambda: True)
    monkeypatch.setattr(
        "app.application.elt.target_detection._llm_classification",
        lambda _lines: {"target_type": "knowledge", "confidence": 0.9, "reason": "llm:台账"},
    )
    monkeypatch.setattr(
        "app.application.elt.llm_assist.advise_table_schema",
        lambda **_kwargs: _result(
            {
                "is_table": True,
                "table_name": "车间产量台账",
                "confidence": 0.82,
                "columns": [
                    {"source": "车间", "name": "车间", "type": "string", "role": "dimension"},
                    {"source": "投入", "name": "投入", "type": "number", "role": "measure"},
                ],
                "dedupe_keys": ["车间"],
            }
        ),
    )
    source = _csv(
        upload_dir,
        "产量.csv",
        ["车间,班次,投入,产出,备注", "一车间,白班,120,118,正常", "二车间,夜班,98,97,正常"],
    )

    with tenant_scope(1):
        result = detect_elt_target(source, owner_user_id=7)

    assert result["target_type"] == "dynamic_table"
    assert result["dynamic_schema"]["table_name"] == "车间产量台账"
    assert result["dynamic_schema"]["dedupe_keys"] == ["车间"]
    assert result["document_type"] == "ai_inferred_table"


def test_unmatched_csv_finishes_clean_when_schema_unknown(upload_dir, monkeypatch):
    monkeypatch.setenv("FHD_ELT_LLM_CLASSIFY_TESTS", "1")
    monkeypatch.setattr("app.application.elt.llm_assist.elt_llm_enabled", lambda: True)
    monkeypatch.setattr(
        "app.application.elt.target_detection._llm_classification",
        lambda _lines: {"target_type": "knowledge", "confidence": 0.9, "reason": "llm:说明"},
    )
    monkeypatch.setattr(
        "app.application.elt.llm_assist.advise_table_schema",
        lambda **_kwargs: _result(
            {"is_table": False, "table_name": "", "confidence": 0.2, "columns": []}
        ),
    )
    source = _csv(upload_dir, "说明.csv", ["通知", "本周例会改到周五", "请知悉"])

    with tenant_scope(1):
        result = detect_elt_target(source, owner_user_id=7)

    assert result["target_type"] in {"abnormal", "knowledge"}


def test_dynamic_table_candidate_turns_unknown_workbook_into_schema(upload_dir, monkeypatch):
    from openpyxl import Workbook

    from app.application.elt.candidate_table import dynamic_table_candidate

    monkeypatch.setattr("app.application.elt.llm_assist.elt_llm_enabled", lambda: True)
    monkeypatch.setattr(
        "app.application.elt.llm_assist.advise_table_schema",
        lambda **_kwargs: _result(
            {
                "is_table": True,
                "table_name": "生产工单",
                "confidence": 0.8,
                "columns": [
                    {"source": "工单号", "name": "工单号", "type": "string", "role": "key"},
                    {"source": "计划量", "name": "计划量", "type": "number", "role": "measure"},
                ],
                "dedupe_keys": ["工单号"],
            }
        ),
    )
    source = upload_dir / "生产单.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["工单号", "计划量", "状态"])
    sheet.append(["GD-1", 300, "生产中"])
    book.save(source)
    book.close()

    result = dynamic_table_candidate(source)

    assert result is not None
    table, schema = result
    assert len(table.rows) == 1
    assert schema["table_name"] == "生产工单"
    assert schema["dedupe_keys"] == ["工单号"]


def test_dynamic_adapter_writes_dedupes_and_rolls_back(tmp_path):
    from app.application.elt.service_support import dump_json

    run_id = "run-dynamic-1"
    owner_user_id = 7
    with tenant_scope(1):
        db = SessionLocal()
        try:
            db.add(_upload(owner_user_id))
            db.flush()
            db.add(
                _run(
                    run_id,
                    owner_user_id,
                    draft=dump_json(
                        {
                            "field_mappings": [
                                {"source": "车间", "target": "车间", "transforms": []},
                                {"source": "投入", "target": "投入", "transforms": []},
                            ],
                            "dynamic_schema": {
                                "table_name": "车间产量台账",
                                "columns": [],
                                "dedupe_keys": ["车间"],
                            },
                        }
                    ),
                )
            )
            db.commit()
        finally:
            db.close()

        adapter = DynamicTableAdapter()
        context = {"run_id": run_id, "owner_user_id": owner_user_id, "file_name": "产量.csv"}
        rows = [{"车间": "一车间", "投入": 120}, {"车间": "二车间", "投入": 98}]

        first = adapter.execute_batch(iter(rows), context)
        second = adapter.execute_batch(iter(rows), context)

        assert first["executed"] == 2
        assert second["executed"] == 0
        assert second["receipt"]["duplicates"] == 2

        deleted = adapter.rollback_batch(context, first["receipt"])
        assert deleted == 2


def _result(payload: dict):
    from app.application.elt.llm_assist import LlmAssistResult

    return LlmAssistResult(used_llm=True, data=payload)


def _run(run_id: str, owner_user_id: int, *, draft: str):
    from app.db.models.elt import EltRun

    return EltRun(
        id=run_id,
        tenant_id=1,
        owner_user_id=owner_user_id,
        upload_id="upload-dynamic-1",
        target_type="dynamic_table",
        status="preview_ready",
        stage="preview_ready",
        file_sha256="b" * 64,
        created_at=datetime.now(UTC),
        draft_json=draft,
    )


def _upload(owner_user_id: int):
    from app.db.models.elt import EltUpload

    return EltUpload(
        id="upload-dynamic-1",
        tenant_id=1,
        owner_user_id=owner_user_id,
        file_name="产量.csv",
        suffix=".csv",
        size_bytes=1,
        sha256="b" * 64,
        storage_path="/tmp/产量.csv",
        expires_at=datetime.now(UTC),
    )


def test_target_model_precedes_high_confidence_rule(monkeypatch):
    from app.application.elt import target_detection as detection

    rule = {
        "target_type": "products",
        "confidence": 0.95,
        "reason": "product_headers",
        "sheet_name": "rule-sheet",
    }
    monkeypatch.setattr(
        detection, "_llm_classification",
        lambda _lines: {"target_type": "customers", "confidence": 0.9},
    )
    result = detection._escalate(rule, ["source"])
    assert result["target_type"] == "customers"
    assert result["decision_source"] == "model"
    assert result["rule_candidate"]["sheet_name"] == "rule-sheet"
    assert "sheet_name" not in result
    monkeypatch.setattr(detection, "_llm_classification", lambda _lines: None)
    fallback = detection._escalate(rule, ["source"])
    assert fallback["target_type"] == "products"
    assert fallback["decision_source"] == "rule_fallback"


def test_uncertain_model_does_not_reactivate_rule(monkeypatch):
    from app.application.elt import target_detection as detection

    monkeypatch.setattr(
        detection, "_llm_classification",
        lambda _lines: {"target_type": "abnormal", "confidence": 0.4},
    )
    monkeypatch.setattr(detection, "_infer_dynamic_schema", lambda _rows: None)
    result = detection._escalate(
        {"target_type": "products", "confidence": 0.98}, ["source"],
    )
    assert result["target_type"] == "abnormal"
    assert result["needs_review"] is True
    assert result["confirmed"] is False


def test_model_mapping_can_replace_rule_and_exposes_unresolved(monkeypatch):
    from app.application.elt import mapping_assist
    from app.application.elt.parser_types import ParsedDataset, ParsedRow

    dataset = ParsedDataset(
        headers=["A", "B"],
        rows=[ParsedRow("Sheet1", 2, {"A": "one", "B": "two"})],
        source_features={},
    )
    adapter = get_adapter("customers")
    targets = [field.key for field in adapter.fields]
    rule = [
        {"target": targets[0], "source": "A", "confidence": 1.0, "transforms": []},
        {"target": targets[1], "source": "B", "confidence": 1.0, "transforms": []},
    ]
    monkeypatch.setattr(
        mapping_assist,
        "advise_field_mappings",
        lambda **_kwargs: _result({
            "mappings": [{
                "source": "B", "target": targets[0], "confidence": 0.95, "transform": "trim",
            }],
        }),
    )
    mapped, meta = mapping_assist.enhance_mappings_with_llm(dataset, adapter, rule)
    assert mapped[0]["source"] == "B"
    assert mapped[1]["source"] == ""
    assert meta["unmapped_targets"] == [targets[1]]
    assert meta["unmapped_sources"] == ["A"]
    assert dataset.rows[0].values == {"A": "one", "B": "two"}
    assert rule[0]["source"] == "A"


def test_dynamic_dedupe_requires_complete_unique_composite():
    from app.application.elt.targets.dynamic import _usable_dedupe_keys

    rows = [{"customer": "A", "line": 1}, {"customer": "A", "line": 2}]
    headers = ["customer", "line"]
    assert _usable_dedupe_keys(["customer"], headers, rows) == []
    assert _usable_dedupe_keys(["customer", "line"], headers, rows) == headers
    assert _usable_dedupe_keys(["line"], headers, [{"line": 1}, {}]) == []
    assert _usable_dedupe_keys(["line", "missing"], headers, rows) == []
