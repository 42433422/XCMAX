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
