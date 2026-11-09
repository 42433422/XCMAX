"""Real prepared XLSX runs bind reviewed intake consent to scope and content."""

import json
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.application.elt import auto_ingest_service as ais
from app.application.elt import service_draft, service_execution, service_preview
from app.application.elt.errors import EltError
from app.application.elt.service import EltService
from app.db.db_base import Base
from app.db.models import PurchaseUnit, ShipmentRecord
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.fastapi_routes import reviewed_excel_template as routes
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.path_io import path_utils
from tests.test_application.test_etl_auto_ingest_service import rag_service as rag_service
from tests.test_application.test_etl_preview_task_boundaries import ObservedExecutor
from tests.test_application.test_reviewed_excel_template import (
    account_session_client as account_session_client,
)
from tests.test_application.test_reviewed_excel_template import (
    candidate_form,
)
from tests.test_application.test_reviewed_excel_template import (
    review_store as review_store,
)

BASE = "/api/templates/reviewed-excel"


@pytest.fixture
def intake_store(review_store, rag_service, monkeypatch, account_session_client):
    store = review_store
    Base.metadata.create_all(store.engine)
    store.factory = sessionmaker(bind=store.engine)
    store.service = EltService()
    store.intake = ais.AutoIngestService()
    store.rag = rag_service
    store.starts = []
    store.actor.update(execute=True, mod="erp-test")
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_llm_complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            provider="platform",
            model="mimo-v2.6-flash",
            data={"candidates": [{"clear": [], "reason": "synthetic"} for _ in range(3)]},
        ),
    )
    monkeypatch.setenv("FHD_ETL_LLM", "off")

    def old_parser_must_not_run(*_args, **_kwargs):
        raise AssertionError("旧解析器不能参与所选候选的入库")

    monkeypatch.setattr("app.application.elt.service_preview.parse_file", old_parser_must_not_run)
    monkeypatch.setattr(ais, "get_app_data_dir", lambda: str(store.root))
    monkeypatch.setattr(path_utils, "get_app_data_dir", lambda **_: str(store.root))
    monkeypatch.setattr(ais, "get_auto_ingest_service", lambda: store.intake)
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: store.service)
    monkeypatch.setattr(
        "app.request_active_mod_ctx.get_request_active_mod_id", lambda: store.actor["mod"]
    )
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: store.actor["mod"])
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mod: mod != "denied",
    )

    def execute(_request):
        if not store.actor["execute"]:
            raise HTTPException(status_code=403, detail="执行权限已撤销")
        return SimpleNamespace(
            id=store.actor["id"],
            tenant_id=store.actor["tenant"],
            account_kind="enterprise",
            role="enterprise_owner",
        )

    def start(**kwargs):
        store.starts.append(kwargs)
        with tenant_scope(kwargs["tenant_id"]), store.factory() as db:
            result = store.intake.run(db, **kwargs)
            db.commit()
            return result

    monkeypatch.setattr(routes, "_execute", execute)
    monkeypatch.setattr(store.intake, "start_background", start)
    with ObservedExecutor() as executor:
        store.executor = executor
        for module in (service_preview, service_draft, service_execution):
            monkeypatch.setattr(module, "new_session", store.factory)
            monkeypatch.setattr(module, "EXECUTOR", executor)
        yield store


def review(store):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "客户"
    sheet.append(["客户名称", "电话"])
    sheet.append(["确认客户甲", "13000000001"])
    sheet.append(["确认客户乙", "13000000002"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    response = store.client.post(
        f"{BASE}/preview",
        files={"file": ("客户.xlsx", stream.getvalue())},
        data=candidate_form(store.client, stream.getvalue()),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "review_id": data["review_id"],
        "proposal_version": data["proposal"]["version"],
        "candidate_id": data["proposal"]["candidates"][0]["id"],
        "selections": json.dumps(data["proposal"]["candidates"][0]["clear"]),
        "name": "已确认客户",
        "composer_note": "核对客户数据",
    }


def prepare(store):
    data = review(store)
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 200, response.text
    plan = response.json()["intake"]
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        business = store.service.get_run(db, run_id=plan["run_id"], owner_user_id=7)
    assert business["status"] == "preview_ready", business
    return (
        {
            **data,
            "private_intake": "true",
            "intake_run_id": plan["run_id"],
            "preview_revision": business["preview_revision"],
        },
        plan,
        business,
    )


def assert_no_writes(store):
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 0
    assert store.rag.status(dataset_id="office-docking", tenant_id="1")["documents"] == []
    assert store.starts == []


def test_auto_ingest_start_failure_keeps_safe_diagnostics_and_saved_receipt(
    intake_store, monkeypatch, caplog
):
    store = intake_store
    data, _plan, _business = prepare(store)

    def failed_start(**_):
        raise RuntimeError("synthetic-private-cell-and-provider-credential")

    monkeypatch.setattr(store.intake, "start_background", failed_start)
    result = store.client.post(f"{BASE}/save", data=data)
    assert result.status_code == 200
    failure = result.json()["auto_ingest"]
    assert failure["error"] == "auto_ingest_failed" and failure["stage"] == "save"
    assert failure["request_id"] in caplog.text
    assert "synthetic-private-cell" not in caplog.text + result.text
    replay = store.client.post(f"{BASE}/save", data=data).json()
    assert replay["replayed"] and replay["auto_ingest"] == failure


def test_exact_prepared_run_ingests_the_selected_candidate(intake_store, monkeypatch):
    store = intake_store
    data, plan, business = prepare(store)
    assert plan["target_type"] == "customers"
    assert plan["knowledge"]["documents"] == 1
    assert business["summary"]["new"] == 2
    assert_no_writes(store)
    with store.factory() as db:
        before = (db.query(EltRun).count(), db.query(EltUpload).count())
        prepared = Path(db.get(EltUpload, plan["upload_id"]).storage_path).read_bytes()
        staged = db.get(EltUpload, plan["upload_id"])
        assert plan["candidate_sha256"] == staged.sha256
        assert plan["source_sha256"] != "" and staged.sha256
        assert Path(staged.storage_path).read_bytes() == prepared

    clean_calls = {"n": 0}
    real_clean = routes.clean_workbook

    def counting_clean(*args, **kwargs):
        clean_calls["n"] += 1
        return real_clean(*args, **kwargs)

    monkeypatch.setattr(routes, "clean_workbook", counting_clean)
    release = Event()
    store.executor.submit(release.wait, 10)
    try:
        saved = store.client.post(f"{BASE}/save", data=data)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["auto_ingest"].get("error") is None, result
        assert result["auto_ingest"]["status"] == "running"
        assert result["auto_ingest"]["business_progress"]["pct"] < 100
    finally:
        release.set()
    store.executor.futures[-1].result(timeout=10)
    assert clean_calls["n"] >= 1  # template file uses cleaned copy on save
    receipt = store.intake.get_batch(
        tenant_id=1, owner_user_id=7, batch_id=result["auto_ingest"]["batch_id"]
    )
    assert receipt["status"] == "applied"
    assert receipt["business_progress"]["pct"] == 100
    assert len(store.starts) == 1
    assert store.starts[0]["prepared_plan"]["run_id"] == plan["run_id"]
    assert store.starts[0]["prepared_plan"]["preview_revision"] == data["preview_revision"]
    # Ingest reuses the staged candidate workbook from preview.
    assert Path(store.starts[0]["source_path"]).read_bytes() == prepared
    replay = store.client.post(f"{BASE}/save", data=data)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert len(store.starts) == 1
    with tenant_scope(1), store.factory() as db:
        assert (db.query(EltRun).count(), db.query(EltUpload).count()) == before
        assert db.query(PurchaseUnit).count() == 2
        assert db.get(EltRun, plan["run_id"]).status == "completed"
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
    assert len(store.rag.status(dataset_id="office-docking", tenant_id="1")["documents"]) == 1


def test_selected_candidate_clears_are_not_recovered_from_original(intake_store, monkeypatch):
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    store = intake_store
    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_llm_complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            provider="platform",
            model="synthetic",
            data={
                "candidates": [
                    {
                        "clear": [{"sheet": "客户", "cell": cell} for cell in ("B2", "A3", "B3")],
                        "reason": "Remove one record and one private field",
                    }
                    for _ in range(3)
                ]
            },
        ),
    )
    data, plan, business = prepare(store)
    assert business["summary"]["new"] == 1
    assert plan["candidate_sha256"] != plan["source_sha256"]
    saved = store.client.post(f"{BASE}/save", data=data)
    assert saved.status_code == 200, saved.text
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        customer = db.query(PurchaseUnit).one()
        assert customer.unit_name == "确认客户甲"
        assert not customer.contact_phone
        assert db.get(EltRun, plan["run_id"]).status == "completed"


def test_knowledge_changed_since_preview_requires_new_consent(intake_store):
    store = intake_store
    data, _, _ = prepare(store)
    with tenant_scope(1):
        store.intake._ingest_knowledge(
            text="先前由其他任务写入的内容",
            source_key=data["name"],
            run_id="different-job",
            owner_user_id=7,
            content_hash="other-content",
            note="",
            tenant_id=1,
        )
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == 409
    assert store.starts == []
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 0
    assert len(store.rag.status(dataset_id="office-docking", tenant_id="1")["documents"]) == 1


def test_receipt_refresh_preserves_concurrent_withdrawal_and_mod_visibility(
    intake_store, monkeypatch
):
    store = intake_store
    data, _, _ = prepare(store)
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == 200, response.text
    batch_id = response.json()["auto_ingest"]["batch_id"]
    store.executor.futures[-1].result(timeout=10)
    get_run = store.service.get_run

    def concurrent_withdrawal(*args, **kwargs):
        run = get_run(*args, **kwargs)
        ais._patch_batch(1, batch_id, status="withdrawn")
        return run

    monkeypatch.setattr(store.service, "get_run", concurrent_withdrawal)
    assert (
        store.intake.get_batch(tenant_id=1, owner_user_id=7, batch_id=batch_id)["status"]
        == "withdrawn"
    )
    assert store.intake.list_batches(tenant_id=1, owner_user_id=7)[0]["status"] == "withdrawn"
    store.actor["mod"] = "other-mod"
    assert store.intake.get_batch(tenant_id=1, owner_user_id=7, batch_id=batch_id) is None
    assert store.intake.list_batches(tenant_id=1, owner_user_id=7) == []
    with store.factory() as db, pytest.raises(EltError) as error:
        store.intake.withdraw(db, tenant_id=1, owner_user_id=7, batch_id=batch_id)
    assert error.value.status_code == 403
    assert len(store.rag.status(dataset_id="office-docking", tenant_id="1")["documents"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("intake_run_id", "other-run"),
        ("proposal_version", "stale"),
        ("candidate_id", "other-candidate"),
        ("name", "更名"),
        ("composer_note", "整理要求已变化"),
        ("selections", '[{"sheet":"客户","cell":"A2"}]'),
        ("preview_revision", "stale"),
    ],
)
def test_changed_consent_is_rejected(intake_store, field, value):
    data, _, _ = prepare(intake_store)
    response = intake_store.client.post(f"{BASE}/save", data={**data, field: value})
    assert response.status_code == 409, response.text
    assert_no_writes(intake_store)


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("id", 8, 404),
        ("tenant", 2, 404),
        ("mod", "different-mod", 409),
        ("mod", "denied", 403),
        ("execute", False, 403),
    ],
)
def test_scope_or_permission_changed_after_preview_is_rejected(intake_store, field, value, status):
    data, _, _ = prepare(intake_store)
    intake_store.actor[field] = value
    response = intake_store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == status, response.text
    assert_no_writes(intake_store)


@pytest.mark.parametrize("field,value,status", [("execute", False, 403), ("mod", "other-mod", 409)])
def test_write_boundary_rechecks_execute_permission_and_frozen_mod(
    intake_store, monkeypatch, field, value, status
):
    store = intake_store
    data, _, _ = prepare(store)
    original = routes._recheck

    def changed_identity(request, expected):
        original(request, expected)
        store.actor[field] = value

    monkeypatch.setattr(routes, "_recheck", changed_identity)
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == status, response.text
    assert_no_writes(store)
    with store.factory() as db:
        assert db.get(EltRun, data["review_id"]).status == "template_review_ready"


@pytest.mark.parametrize(
    "change", ["run_owner", "run_tenant", "target", "sha", "bytes", "source_bytes", "row"]
)
def test_staged_run_tampering_is_rejected(intake_store, change):
    store = intake_store
    data, plan, _ = prepare(store)
    with store.factory() as db:
        run = db.get(EltRun, plan["run_id"])
        if change == "run_owner":
            run.owner_user_id = 8
        elif change == "run_tenant":
            run.tenant_id = 2
        elif change == "target":
            run.target_type = "products"
        elif change == "sha":
            run.file_sha256 = "0" * 64
        elif change == "bytes":
            stored = Path(db.get(EltUpload, plan["upload_id"]).storage_path)
            stored.chmod(0o600)
            stored.write_bytes(b"changed")
        elif change == "source_bytes":
            review_run = db.get(EltRun, data["review_id"])
            stored = Path(db.get(EltUpload, review_run.upload_id).storage_path)
            stored.chmod(0o600)
            stored.write_bytes(b"changed")
        else:
            db.query(EltRunRow).filter(EltRunRow.run_id == run.id).first().normalized_json = "{}"
        db.commit()
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == 409, response.text
    assert_no_writes(store)


@pytest.mark.parametrize("field,value", [("execute", False), ("mod", "denied")])
def test_intake_preparation_requires_execute_and_mod_permission(intake_store, field, value):
    store = intake_store
    data = review(store)
    with store.factory() as db:
        before = (db.query(EltRun).count(), db.query(EltUpload).count())
    store.actor[field] = value
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 403
    assert_no_writes(store)
    with store.factory() as db:
        assert (db.query(EltRun).count(), db.query(EltUpload).count()) == before


def test_private_intake_requires_preview_and_unscoped_attendance_is_refused(intake_store):
    store = intake_store
    data = review(store)
    response = store.client.post(f"{BASE}/save", data={**data, "private_intake": "true"})
    assert response.status_code == 409
    response = store.client.post(f"{BASE}/intake-preview", data={**data, "composer_note": "考勤"})
    assert response.status_code == 200, response.text
    assert response.json()["intake"]["target_type"] == "customers"
    assert_no_writes(store)


def test_unknown_template_commit_receipt_cannot_replay_intake(intake_store, monkeypatch):
    from app.legacy.routes import document_templates_compat

    store = intake_store
    data, _, _ = prepare(store)
    actual = document_templates_compat.run_archive_template_create

    def lost_receipt(payload):
        result, code = actual(payload)
        assert result["success"] and code == 200
        raise RuntimeError("synthetic receipt loss")

    monkeypatch.setattr(document_templates_compat, "run_archive_template_create", lost_receipt)
    client = TestClient(store.client.app, raise_server_exceptions=False)
    client.cookies.update(store.client.cookies)
    assert client.post(f"{BASE}/save", data=data).status_code == 500
    assert client.post(f"{BASE}/save", data=data).status_code == 409
    assert store.starts == []
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
    assert store.rag.status(dataset_id="office-docking", tenant_id="1")["documents"] == []


@pytest.mark.parametrize("change,status", [("owner", 404), ("tenant", 404), ("expired", 410)])
def test_prepared_upload_record_must_still_be_owned_and_live(intake_store, change, status):
    from datetime import UTC, datetime, timedelta

    store = intake_store
    data, plan, _ = prepare(store)
    with tenant_scope(1), store.factory() as db:
        upload = db.get(EltUpload, plan["upload_id"])
        if change == "owner":
            upload.owner_user_id = 8
        elif change == "tenant":
            upload.tenant_id = 2
        else:
            upload.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == status, response.text
    assert_no_writes(store)


def _delivery_note_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "送货单"
    sheet["A1"] = "送货单"
    sheet["A2"] = "客户名称"
    sheet["B2"] = "演示客户乙"
    sheet["C2"] = "单据日期"
    sheet["D2"] = "2026-11-07"
    sheet["A3"] = "产品名称"
    sheet["B3"] = "数量"
    sheet["C3"] = "单价"
    sheet["D3"] = "金额"
    sheet["E3"] = "规格"
    sheet["F3"] = "备注"
    sheet["A4"] = "演示物料-螺母"
    sheet["B4"] = 5
    sheet["C4"] = 6.5
    sheet["D4"] = 32.5
    sheet["E4"] = "M10"
    sheet["F4"] = "实机复测"
    sheet["A5"] = "演示物料-弹垫"
    sheet["B5"] = 2
    sheet["C5"] = 3
    sheet["D5"] = 6
    sheet["E5"] = "M10"
    sheet["F5"] = "实机复测"
    sheet["A6"] = "合计"
    sheet["B6"] = 7
    sheet["D6"] = 38.5
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_spaced_delivery_headers_use_the_sheet_name_as_customer():
    from openpyxl import Workbook

    from app.application.elt.candidate_table import read_delivery_note_business

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "演示客户甲"
    sheet["A1"] = "演示公司送货单"
    sheet["A3"] = "产 品 型 号"
    sheet["B3"] = "产 品 名 称"
    sheet["C3"] = "数量/件"
    sheet["D3"] = "数量/KG"
    sheet["E3"] = "单价/元"
    sheet["F3"] = "金额/元"
    sheet["A4"] = "FG-1"
    sheet["B4"] = "演示色漆"
    sheet["C4"] = 4
    sheet["D4"] = "=C4*2"
    sheet["E4"] = 18
    sheet["F4"] = "=C4*E4"
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    dataset = read_delivery_note_business(stream.getvalue())
    assert dataset is not None
    assert len(dataset.rows) == 1
    assert dataset.rows[0].values["购买单位"] == "演示客户甲"
    assert dataset.rows[0].values["产品名称"] == "演示色漆"
    assert dataset.rows[0].values["数量"] == 4
    assert not str(dataset.rows[0].values.get("金额") or "").startswith("=")


def test_shipment_ledger_borrows_unique_customer_sheet_and_reads_all_blocks():
    from openpyxl import Workbook

    from app.application.elt.candidate_table import read_delivery_note_business

    workbook = Workbook()
    named = workbook.active
    named.title = "贾总"
    named["A1"] = "送货单"
    named["A2"] = "产品名称"
    named["B2"] = "数量"
    named["A3"] = "色漆A"
    named["B3"] = 2
    ledger = workbook.create_sheet("26出货")
    ledger["A1"] = "日期"
    ledger["B1"] = "产品名称"
    ledger["C1"] = "数量"
    ledger["A2"] = "1"
    ledger["B2"] = "色漆B"
    ledger["C2"] = 3
    ledger["A4"] = "日期"
    ledger["B4"] = "产品名称"
    ledger["C4"] = "数量"
    ledger["A5"] = "2"
    ledger["B5"] = "色漆C"
    ledger["C5"] = 5
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    dataset = read_delivery_note_business(stream.getvalue())
    assert dataset is not None
    by_sheet = {}
    for row in dataset.rows:
        by_sheet.setdefault(row.sheet, []).append(row.values["产品名称"])
        assert row.values["购买单位"] == "贾总"
    assert by_sheet["贾总"] == ["色漆A"]
    assert by_sheet["26出货"] == ["色漆B", "色漆C"]


def test_degraded_header_label_is_not_master_data():
    from app.application.elt.targets.helpers import degraded_header_master

    degraded = {
        "degraded": True,
        "degradation_code": "ELT_LLM_UNAVAILABLE",
        "used_llm": False,
    }
    assert degraded_header_master(degraded, {"customer_name": "产品名称"})
    assert not degraded_header_master(
        {"degraded": False, "used_llm": True}, {"customer_name": "产品名称"}
    )
    assert not degraded_header_master(degraded, {"customer_name": "演示客户乙"})


def test_header_label_customer_preview_does_not_insert(intake_store):
    from app.application.elt.targets.customers import CustomerAdapter

    with tenant_scope(1), intake_store.factory() as db:
        decision = CustomerAdapter().preview(
            db,
            {"customer_name": "产品名称"},
            allowed_update_fields=set(),
            context={},
        )
    assert decision.action == "error"
    assert decision.reason == "header_label_not_master_data"


def test_delivery_note_writes_item_rows_not_the_header(intake_store, monkeypatch):
    """A banner-only template still imports item rows from the archived original."""
    import hashlib

    from app.application.elt import candidate_table
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    store = intake_store
    cleared = [{"sheet": "送货单", "cell": cell} for cell in ("A1", "B2", "C2", "D2")]
    seen = {}

    def business(text):
        from app.application.elt.llm_session_provider import current_etl_llm_owner
        from app.application.elt_login_authorization import current_model_session_id

        seen["business"] = text
        seen["owner"] = current_etl_llm_owner()
        seen["session"] = current_model_session_id(7)
        return LlmAssistResult(
            used_llm=True,
            data={
                "rows": [
                    {
                        "customer_name": "演示客户乙",
                        "product_name": "演示物料-螺母",
                        "quantity": "5",
                        "source_sheet": "送货单",
                        "source_row": "3",
                    },
                    {
                        "customer_name": "演示客户乙",
                        "product_name": "演示物料-弹垫",
                        "quantity": "2",
                        "source_sheet": "送货单",
                        "source_row": "4",
                    },
                ]
            },
        )

    def knowledge(text):
        seen["knowledge"] = text
        return LlmAssistResult(used_llm=True, data={"title": "送货单", "content": text})

    real_delivery = candidate_table.read_delivery_note_business

    def delivery(source):
        seen["source_sha"] = hashlib.sha256(source).hexdigest()
        return real_delivery(source)

    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_llm_complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            provider="platform",
            model="synthetic",
            data={
                "candidates": [{"clear": cleared, "reason": "blank the lines"} for _ in range(3)]
            },
        ),
    )
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr("app.application.elt.llm_assist.advise_business_import", business)
    monkeypatch.setattr("app.application.elt.llm_assist.advise_knowledge_import", knowledge)
    monkeypatch.setattr(candidate_table, "read_delivery_note_business", delivery)
    body = _delivery_note_bytes()
    classified = store.client.post(
        "/api/templates/reviewed-excel/classify",
        files={"files": ("送货单.xlsx", body)},
        data={"expected_actor": "1:7"},
    )
    assert classified.status_code == 200, classified.text
    result = classified.json()["files"][0]
    # The rule partition overlaps the banner and the item table on the header row.
    # Separate them the way a person confirms one delivery note.
    labels = []
    for sheet in result["sheets"]:
        for region in sheet["regions"]:
            area = region["range"]
            if area == "A1:D3":
                area = "A1:D2"
            labels.append(
                {
                    "sheet": sheet["sheet"],
                    "original_range": region["range"],
                    "range": area,
                    "labels": ["delivery"],
                }
            )
    confirmed = store.client.post(
        f"/api/templates/reviewed-excel/classifications/{result['classification_id']}/confirm",
        data={"version": result["version"], "labels_json": json.dumps(labels)},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    regions = confirmed_body["sheets"][0]["regions"]
    banner = next((region for region in regions if region["range"] == "A1:D2"), regions[0])
    form = {
        "expected_actor": "1:7",
        "use_login_notice": "true",
        "classification_id": result["classification_id"],
        "classification_version": confirmed_body["version"],
        "region_sheet": confirmed_body["sheets"][0]["sheet"],
        "region_range": banner["range"],
    }
    response = store.client.post(
        f"{BASE}/preview",
        files={"file": ("送货单.xlsx", body)},
        data=form,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    proposal = payload["proposal"]
    candidate = next(item for item in proposal["candidates"] if item["clear"])
    data = {
        "review_id": payload["review_id"],
        "proposal_version": proposal["version"],
        "candidate_id": candidate["id"],
        "selections": json.dumps(candidate["clear"]),
        "name": "送货单",
        "composer_note": "",
    }
    preview = store.client.post(f"{BASE}/intake-preview", data=data)
    assert preview.status_code == 200, preview.text
    plan = preview.json()["intake"]
    assert plan["target_type"] == "shipment_records"
    assert seen["source_sha"] == result["sha256"]
    assert "演示物料-螺母" in seen["business"]
    assert "演示物料-弹垫" in seen["knowledge"]
    assert seen["owner"] == 7
    assert seen["session"] == "synthetic-session"
    assert plan["detection"]["used_llm"] is True
    assert plan["detection"]["degraded"] is False
    assert plan["detection"]["llm_lane"] == "database"
    assert plan["knowledge"]["used_llm"] is True
    assert plan["knowledge"]["lane"] == "knowledge"
    with tenant_scope(1), store.factory() as db:
        review_run = db.get(EltRun, payload["review_id"])
    assert review_run.file_sha256 != result["sha256"]
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        business = store.service.get_run(db, run_id=plan["run_id"], owner_user_id=7)
    assert business["status"] == "preview_ready", business
    assert business["summary"]["new"] == 2
    assert business["details"]["entities"] == {
        "customers": 0,
        "purchase_units": 1,
        "products": 2,
        "records": 2,
    }
    saved = store.client.post(
        f"{BASE}/save",
        data={
            **data,
            "private_intake": "true",
            "intake_run_id": plan["run_id"],
            "preview_revision": business["preview_revision"],
        },
    )
    assert saved.status_code == 200, saved.text
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        units = [row.unit_name for row in db.query(PurchaseUnit).all()]
        shipments = db.query(ShipmentRecord).order_by(ShipmentRecord.id).all()
        saved_run = store.service.get_run(db, run_id=plan["run_id"], owner_user_id=7)
    assert saved_run["receipt"]["entities"]["records"] == 2
    assert units == ["演示客户乙"]
    assert [(row.purchase_unit, row.product_name, row.quantity_tins) for row in shipments] == [
        ("演示客户乙", "演示物料-螺母", 5),
        ("演示客户乙", "演示物料-弹垫", 2),
    ]


def test_import_lanes_do_not_share_a_circuit(monkeypatch):
    from unittest.mock import patch

    from app.application.elt import llm_assist

    with patch("app.application.elt.llm_session_provider.current_etl_llm_owner", return_value=7):
        assert llm_assist._circuit_key() == "owner:7"
        assert llm_assist._circuit_key("database") == "owner:7:database"
        assert llm_assist._circuit_key("knowledge") == "owner:7:knowledge"
        assert llm_assist._circuit_key("template") == "owner:7:template"


def test_database_model_rows_drop_header_labels():
    from app.application.elt.candidate_table import dataset_from_business_rows

    dataset = dataset_from_business_rows(
        [
            {"purchase_unit": "产品名称", "product_name": "数量", "quantity": "1"},
            {
                "customer_name": "演示客户乙",
                "product_name": "演示物料-螺母",
                "quantity": "5",
                "unit_price": "6.5",
                "amount": "32.5",
            },
        ]
    )
    assert dataset is not None
    assert len(dataset.rows) == 1
    assert dataset.rows[0].sheet == ""
    assert dataset.rows[0].provenance["location"] == "unlocated"
    assert dataset.rows[0].values["购买单位"] == "演示客户乙"
    assert dataset.rows[0].values["产品名称"] == "演示物料-螺母"
    located = dataset_from_business_rows(
        [
            {
                "customer_name": "演示客户乙",
                "product_name": "演示物料-螺母",
                "quantity": "5",
                "source_sheet": "送货单",
                "source_row": "4",
                "source_range": "A4:D4",
            }
        ]
    )
    assert located is not None
    assert located.rows[0].sheet == "送货单"
    assert located.rows[0].row_number == 4
    assert located.rows[0].provenance["location"] == "model"


def test_knowledge_line_calls_its_own_model(intake_store, monkeypatch, tmp_path):
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    seen = {}

    def knowledge(text):
        seen["text"] = text
        return LlmAssistResult(
            used_llm=True, data={"title": "送货单", "content": "演示客户乙 螺母 5"}
        )

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr("app.application.elt.llm_assist.etl_llm_enabled", lambda: True)
    monkeypatch.setattr("app.application.elt.llm_assist.advise_knowledge_import", knowledge)
    with tenant_scope(1):
        plan = intake_store.intake.knowledge_plan(
            path=tmp_path / "missing.xlsx",
            file_name="送货单",
            note="",
            owner_user_id=7,
            source_text="送货单\n客户名称 演示客户乙",
        )
    assert seen["text"].startswith("送货单")
    assert plan["lane"] == "knowledge"
    assert plan["used_llm"] is True
    assert plan["degraded"] is False
    assert "螺母" in plan["content"]
    assert "演示客户乙" in plan["content"]
    assert plan["model_applied"] is True


def test_unwritten_rows_stay_in_the_knowledge_document():
    from app.application.elt.auto_ingest_service import knowledge_document_keeps_unwritten_rows

    kept = knowledge_document_keeps_unwritten_rows("整理摘要", "桶数 -1")
    assert kept.startswith("整理摘要")
    assert "桶数 -1" in kept
    assert knowledge_document_keeps_unwritten_rows("", "归档原文") == "归档原文"
    assert (
        knowledge_document_keeps_unwritten_rows("归档原文已含明细", "归档原文")
        == "归档原文已含明细"
    )


def test_knowledge_plan_uses_archived_text_when_the_model_fails(
    intake_store, monkeypatch, tmp_path
):
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    def knowledge(_text):
        return LlmAssistResult(used_llm=True, degraded=True, degradation_code="ELT_LLM_UNAVAILABLE")

    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr("app.application.elt.llm_assist.etl_llm_enabled", lambda: True)
    monkeypatch.setattr("app.application.elt.llm_assist.advise_knowledge_import", knowledge)
    with tenant_scope(1):
        plan = intake_store.intake.knowledge_plan(
            path=tmp_path / "missing.xlsx",
            file_name="国圣化工",
            note="",
            owner_user_id=7,
            source_text="送货单\n客户 国圣 白浆 2",
        )
    assert plan["documents"] == 1
    assert plan["degraded"] is True
    assert plan["degradation_code"] == "ELT_LLM_UNAVAILABLE"
    assert plan["model_applied"] is False
    assert plan["action"] in {"new", "update", "skip"}
    assert "国圣" in plan["content"]
