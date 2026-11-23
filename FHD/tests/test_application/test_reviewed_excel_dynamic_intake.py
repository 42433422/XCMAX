"""Reviewed tables retain their inferred schema outside the fixed target enum."""

import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.application.elt import llm_assist
from app.application.elt.service_support import load_json
from app.db.models.elt import EltDynamicRow, EltDynamicTable, EltRun, EltRunRow
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_reviewed_excel_intake_confirmation import (
    BASE,
    assert_no_writes,
    review,
)
from tests.test_application.test_reviewed_excel_intake_confirmation import (
    account_session_client as account_session_client,
)
from tests.test_application.test_reviewed_excel_intake_confirmation import (
    intake_store as intake_store,
)
from tests.test_application.test_reviewed_excel_intake_confirmation import (
    rag_service as rag_service,
)
from tests.test_application.test_reviewed_excel_intake_confirmation import (
    review_store as review_store,
)


def _workbook(kind):
    book = Workbook()
    selected = book.active
    selected.title = "所选数据"
    if kind == "ledger":
        headers = ["凭证编号", "记账日期", "借方金额", "摘要"]
        rows = [["V-001", "2026-11-01", 10.5, "所选一"], ["V-002", "2026-11-02", 57.5, "所选二"]]
    elif kind == "recipe":
        headers = ["批次编号", "组分代号", "配比", "搅拌分钟"]
        rows = [["B-001", "甲组分", 0.3, 20], ["B-002", "乙组分", 0.7, 25]]
    elif kind == "duplicate_headers":
        headers = ["凭证编号", "金额", "金额", "金额_2"]
        rows = [["V-001", 12, 34, 56], ["V-002", 78, 90, 12]]
    else:
        headers, rows = ["通知"], [["本周例会改到周五"], ["请参会人员提前准备"]]
    selected.append(headers)
    for row in rows:
        selected.append(row)
    attendance = book.create_sheet("未选考勤")
    attendance.append(["2026年2月考勤表"])
    attendance.append(["姓名", *range(1, 29)])
    attendance.append(["未选张三", "√"])
    shipment = book.create_sheet("未选送货单")
    shipment.append(["送货单"])
    shipment.append(["客户名称", "未选客户"])
    shipment.append(["产品名称", "数量"])
    shipment.append(["未选产品", 2])
    out = BytesIO()
    book.save(out)
    book.close()
    if kind == "duplicate_headers":
        headers = ["凭证编号", "金额", "金额_3", "金额_2"]
    return out.getvalue(), headers, rows


def _model_pipeline(monkeypatch, *, schema_mode="table"):
    from app.infrastructure.llm import structured_output

    calls = []
    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setattr(llm_assist._runtime, "_CIRCUIT_OPEN_UNTIL", {})
    monkeypatch.setattr(
        llm_assist,
        "_active_software_llm",
        lambda *_: (
            (False, None, None)
            if schema_mode == "unavailable" and calls
            else (True, None, object())
        ),
    )
    monkeypatch.setattr(
        llm_assist, "advise_knowledge_import", lambda *_: llm_assist.LlmAssistResult()
    )

    def complete(messages, *, schema, **_kwargs):
        if "target_type" in schema["properties"]:
            calls.append(("target_classify", messages[1]["content"]))
            data = {"target_type": "knowledge", "confidence": 0.95, "reason": "非主数据表"}
        else:
            assert "is_table" in schema["properties"]
            payload = json.loads(messages[1]["content"])
            calls.append(("database", payload))
            headers = payload["headers"]
            data = {
                "is_table": schema_mode == "table",
                "table_name": "模型推断业务表",
                "confidence": 0.93,
                "columns": [
                    {
                        "source": header,
                        "name": header,
                        "type": "number" if index == 2 else "string",
                        "role": "key" if index == 0 else "dimension",
                    }
                    for index, header in enumerate(headers)
                ],
                "dedupe_keys": [headers[0]],
            }
        return SimpleNamespace(model="synthetic", billing={}, data=data)

    monkeypatch.setattr(structured_output, "complete_structured_sync", complete)
    return calls


@pytest.mark.parametrize("kind", ["ledger", "recipe", "duplicate_headers"])
def test_fixed_enum_knowledge_still_previews_and_confirms_structured_rows(
    intake_store, monkeypatch, kind
):
    store = intake_store
    body, headers, rows = _workbook(kind)
    if kind == "ledger":

        def cleared_candidate(messages, *_args, **_kwargs):
            audit = messages[0]["content"].startswith("Independently audit")
            return llm_assist.LlmAssistResult(
                used_llm=True,
                provider="platform",
                model="synthetic",
                data=(
                    {"clear": [], "reason": "synthetic audit"}
                    if audit
                    else {
                        "candidates": [
                            {"clear": [{"sheet": "所选数据", "cell": "C2"}], "reason": "已清理字段"}
                            for _ in range(3)
                        ]
                    }
                ),
            )

        monkeypatch.setattr(
            "app.application.reviewed_excel_template._template_llm_complete", cleared_candidate
        )
    data = review(store, body)
    calls = _model_pipeline(monkeypatch)
    monkeypatch.setattr("app.application.elt.service.SessionLocal", store.factory)
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 200, response.text
    plan = response.json()["intake"]
    assert plan["target_type"] == "dynamic_table"
    assert plan["detection"]["reason"] == "ai_table_schema"
    assert plan["detection"]["llm_lane"] == "database"
    assert [(item["lane"], item["status"]) for item in plan["model_calls"]] == [
        ("target_classify", "answered"),
        ("database", "answered"),
    ]
    assert [lane for lane, _ in calls] == ["target_classify", "database"]
    schema_input = calls[1][1]
    assert schema_input["headers"] == headers
    assert "未选张三" not in json.dumps(calls, ensure_ascii=False)
    assert "未选产品" not in json.dumps(calls, ensure_ascii=False)
    if kind == "ledger":
        assert "10.5" not in schema_input["samples"]["借方金额"]
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        business = store.service.get_run(db, run_id=plan["run_id"], owner_user_id=7)
        draft = load_json(db.get(EltRun, plan["run_id"]).draft_json, {})
        assert draft["dynamic_schema"]["headers"] == headers
        assert draft["dynamic_schema"]["columns"][2]["type"] == "number"
        assert db.query(EltDynamicTable).count() == db.query(EltDynamicRow).count() == 0
        if kind == "duplicate_headers":
            from app.application.elt.errors import EltConflict
            from app.application.elt.preview_confirmation import verify_preview
            from app.application.elt.service_support import dump_json

            source = db.query(EltRunRow).filter_by(run_id=plan["run_id"]).first()
            assert load_json(source.source_json, {}) == dict(zip(headers, rows[0], strict=True))
            provenance = load_json(source.provenance_json, {})
            assert provenance["columns"] == dict(zip(headers, range(1, 5), strict=True))
            assert provenance["original_headers"] == {
                "凭证编号": "凭证编号",
                "金额": "金额",
                "金额_3": "金额",
                "金额_2": "金额_2",
            }
            assert provenance["header_rows"] == {"start": 1, "end": 1}
            # Either formerly colliding value is part of the reviewed content.
            for column in ("金额", "金额_3"):
                normalized = load_json(source.normalized_json, {})
                assert str(normalized[column]) == str(rows[0][headers.index(column)])
                normalized[column] = -100
                source.normalized_json = dump_json(normalized)
                with pytest.raises(EltConflict) as changed:
                    verify_preview(db, db.get(EltRun, plan["run_id"]), business["preview_revision"])
                assert changed.value.code == "ELT_PREVIEW_CHANGED"
                db.rollback()
    assert business["status"] == "preview_ready" and business["summary"]["new"] == 2
    assert_no_writes(store)

    save_data = {
        **data,
        "private_intake": "true",
        "intake_run_id": plan["run_id"],
        "preview_revision": business["preview_revision"],
    }
    stale = store.client.post(f"{BASE}/save", data={**save_data, "preview_revision": "stale"})
    assert stale.status_code == 409
    saved = store.client.post(f"{BASE}/save", data=save_data)
    assert saved.status_code == 200, saved.text
    batch = saved.json()["auto_ingest"]
    assert batch["status"] == "awaiting_approval"
    with tenant_scope(1), store.factory() as db:
        assert db.query(EltDynamicRow).count() == 0
    store.intake.release_approved_batch(batch_id=batch["batch_id"], tenant_id=1)
    store.executor.futures[-1].result(timeout=10)
    receipt = store.intake.get_batch(tenant_id=1, owner_user_id=7, batch_id=batch["batch_id"])
    assert receipt["status"] == "applied", receipt
    replay = store.client.post(f"{BASE}/save", data=save_data)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    with tenant_scope(1), store.factory() as db:
        table = db.query(EltDynamicTable).one()
        assert table.tenant_id == 1 and table.owner_user_id == 7
        assert load_json(table.headers_json, []) == headers
        stored = db.query(EltDynamicRow).order_by(EltDynamicRow.source_row).all()
        assert len(stored) == 2
        payloads = [load_json(item.payload_json, {}) for item in stored]
        assert [item[headers[0]] for item in payloads] == [row[0] for row in rows]
        assert str(payloads[1][headers[2]]) == str(rows[1][2])
        if kind == "duplicate_headers":
            assert [[str(payload[key]) for key in headers] for payload in payloads] == [
                [str(value) for value in row] for row in rows
            ]
        if kind == "ledger":
            assert payloads[0].get(headers[2]) in (None, "")
        assert {(item.tenant_id, item.owner_user_id, item.run_id) for item in stored} == {
            (1, 7, plan["run_id"])
        }
        preview_rows = db.query(EltRunRow).filter_by(run_id=plan["run_id"]).all()
        assert {item.source_sheet for item in preview_rows} == {"所选数据"}
    assert len(store.starts) == 1


def test_selected_candidate_preserves_values_under_unnamed_columns():
    from app.application.elt.candidate_table import read_candidate_table

    book = Workbook()
    book.active.append(["凭证编号", "金额", None])
    book.active.append(["V-001", 12, "原备注"])
    stream = BytesIO()
    book.save(stream)
    book.close()
    dataset = read_candidate_table(stream.getvalue())
    assert dataset.rows[0].values == {"凭证编号": "V-001", "金额": 12, "未命名列3": "原备注"}
    assert dataset.rows[0].provenance["original_headers"]["未命名列3"] == ""
    assert dataset.rows[0].provenance["columns"]["未命名列3"] == 3


@pytest.mark.parametrize("schema_mode", ["not_table", "unavailable", "prose"])
def test_knowledge_text_fallback_remains_available(intake_store, monkeypatch, schema_mode):
    store = intake_store
    body, _, _ = _workbook("prose" if schema_mode == "prose" else "ledger")
    data = review(store, body)
    calls = _model_pipeline(monkeypatch, schema_mode=schema_mode)
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 200, response.text
    plan = response.json()["intake"]
    assert plan["target_type"] == "knowledge"
    assert [lane for lane, _ in calls] == (
        ["target_classify", "database"] if schema_mode == "not_table" else ["target_classify"]
    )
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        assert db.query(EltDynamicTable).count() == db.query(EltDynamicRow).count() == 0
    assert_no_writes(store)


def test_revoked_execution_permission_precedes_all_intake_model_calls(intake_store, monkeypatch):
    store = intake_store
    body, _, _ = _workbook("ledger")
    data = review(store, body)
    calls = _model_pipeline(monkeypatch)
    store.actor["execute"] = False
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 403
    assert calls == []
    assert_no_writes(store)
