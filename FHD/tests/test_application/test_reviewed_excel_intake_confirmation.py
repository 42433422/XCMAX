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
from tests.test_application.test_elt_auto_ingest_service import rag_service as rag_service
from tests.test_application.test_elt_preview_task_boundaries import ObservedExecutor
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

    def candidate_model(messages, *_args, **_kwargs):
        data = (
            {"clear": [], "reason": "synthetic audit"}
            if messages[0]["content"].startswith("Independently audit")
            else {"candidates": [{"clear": [], "reason": "synthetic"} for _ in range(3)]}
        )
        return LlmAssistResult(
            used_llm=True, provider="platform", model="mimo-v2.6-flash", data=data
        )

    monkeypatch.setattr(
        "app.application.reviewed_excel_template._template_llm_complete",
        candidate_model,
    )
    monkeypatch.setenv("FHD_ELT_LLM", "off")

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

    def launch(stored):
        store.starts.append(stored)
        with tenant_scope(stored["tenant_id"]), store.factory() as db:
            result = store.intake.run(
                db,
                owner_user_id=stored["owner_user_id"],
                tenant_id=stored["tenant_id"],
                source_path=stored["source_path"],
                file_name=stored.get("file_name") or "",
                template_id=stored.get("template_id") or "",
                review_id=stored.get("review_id") or "",
                classification_id=stored.get("classification_id") or "",
                composer_note=stored.get("composer_note") or "",
                labels=stored.get("labels"),
                batch_id=stored.get("batch_id"),
                prepared_plan=stored.get("prepared_plan"),
                owned_upload_user_id=stored.get("owner_user_id"),
            )
            db.commit()
            return result

    monkeypatch.setattr(routes, "_execute", execute)
    monkeypatch.setattr(store.intake, "_launch_worker", launch)
    from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest
    from app.db.models.user import User

    Base.metadata.create_all(
        store.engine,
        tables=[
            User.__table__,
            ApprovalFlow.__table__,
            ApprovalFlowNode.__table__,
            ApprovalRequest.__table__,
        ],
    )
    with store.factory() as db:
        if db.get(User, 7) is None:
            db.add(
                User(
                    id=7,
                    username="owner-7",
                    password="x",
                    display_name="owner",
                    is_active=True,
                    tenant_id=1,
                )
            )
            db.commit()
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

    monkeypatch.setattr("app.application.elt.docking_approval.submit_docking_write", failed_start)
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
        assert result["auto_ingest"]["status"] == "awaiting_approval"
        assert store.starts == []
        with store.factory() as db:
            assert db.query(PurchaseUnit).count() == 0
        released = store.intake.release_approved_batch(
            batch_id=result["auto_ingest"]["batch_id"], tenant_id=1
        )
        assert released["status"] == "running"
        assert released["business_progress"]["pct"] < 100
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
        lambda messages, *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            provider="platform",
            model="synthetic",
            data={"clear": [], "reason": "synthetic audit"}
            if messages[0]["content"].startswith("Independently audit")
            else {
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
    store.intake.release_approved_batch(
        batch_id=saved.json()["auto_ingest"]["batch_id"], tenant_id=1
    )
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
    # Keep this case on the deferred read path; polling completion has its own
    # concurrent-withdrawal regression in test_pr3124_safety_boundaries.
    ingest_business = store.intake._ingest_business

    def defer_receipt(*args, **kwargs):
        return ingest_business(*args, **{**kwargs, "poll_seconds": 0})

    monkeypatch.setattr(store.intake, "_ingest_business", defer_receipt)
    data, _, _ = prepare(store)
    response = store.client.post(f"{BASE}/save", data=data)
    assert response.status_code == 200, response.text
    batch_id = response.json()["auto_ingest"]["batch_id"]
    assert response.json()["auto_ingest"]["status"] == "awaiting_approval"
    store.intake.release_approved_batch(batch_id=batch_id, tenant_id=1)
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
        from app.application.elt.llm_session_provider import current_elt_llm_owner
        from app.application.elt_login_authorization import current_model_session_id

        seen["business"] = text
        seen["owner"] = current_elt_llm_owner()
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
    monkeypatch.setenv("FHD_ELT_LLM", "on")
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
    store.intake.release_approved_batch(
        batch_id=saved.json()["auto_ingest"]["batch_id"], tenant_id=1
    )
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

    with patch("app.application.elt.llm_session_provider.current_elt_llm_owner", return_value=7):
        assert llm_assist._circuit_key() == "owner:7"
        assert llm_assist._circuit_key("database") == "owner:7:database"
        assert llm_assist._circuit_key("knowledge") == "owner:7:knowledge"
        assert llm_assist._circuit_key("template") == "owner:7:template"


def test_database_model_rows_keep_incomplete_rows_for_review():
    from app.application.elt.candidate_table import dataset_from_business_rows

    dataset = dataset_from_business_rows(
        [
            {
                "product_name": "合成货品甲",
                "quantity": "2",
                "source_sheet": "表",
                "source_row": "2",
            },
            {
                "purchase_unit": "合成客户",
                "product_name": "合成货品乙",
                "quantity": "",
                "source_sheet": "表",
                "source_row": "3",
            },
            {"purchase_unit": "合成客户", "quantity": "4", "source_sheet": "表", "source_row": "4"},
        ]
    )
    assert dataset is not None and [row.row_number for row in dataset.rows] == [2, 3, 4]
    assert [row.provenance["validation_issues"][0]["field"] for row in dataset.rows] == [
        "purchase_unit",
        "quantity",
        "product_name",
    ]
    assert all(
        row.provenance["validation_issues"][0]["severity"] == "error" for row in dataset.rows
    )


def test_incomplete_model_rows_are_visible_as_errors_in_preview(intake_store):
    from app.application.elt.candidate_table import dataset_from_business_rows

    dataset = dataset_from_business_rows(
        [
            {
                "product_name": "合成货品甲",
                "quantity": "2",
                "source_sheet": "表",
                "source_row": "2",
            },
            {
                "purchase_unit": "合成客户",
                "product_name": "合成货品乙",
                "quantity": "3",
                "source_sheet": "表",
                "source_row": "3",
            },
        ]
    )
    store = intake_store
    with tenant_scope(1), store.factory() as db:
        upload = store.service.save_upload(
            db,
            owner_user_id=7,
            file_name="合成.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            stream=BytesIO(_delivery_note_bytes()),
        )
        db.commit()
        preview = store.service.create_preview(
            db,
            owner_user_id=7,
            upload_id=upload["upload_id"],
            target_type="shipment_records",
            source_dataset=dataset,
        )
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        result = store.service.get_run(db, run_id=preview["id"], owner_user_id=7)
    assert result["status"] == "preview_ready"
    assert result["total_rows"] == 2
    assert result["summary"]["error"] == 1 and result["summary"]["new"] == 1
    assert result["summary"]["executed"] == 0


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


def test_same_archive_with_different_model_summaries_deduplicates_by_source(
    intake_store, monkeypatch, tmp_path
):
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    monkeypatch.setenv("FHD_ELT_LLM", "on")
    summaries = iter(["合成摘要甲", "合成摘要乙", "合成摘要丙"])
    monkeypatch.setattr(
        "app.application.elt.llm_assist.advise_knowledge_import",
        lambda _: LlmAssistResult(used_llm=True, data={"content": next(summaries)}),
    )
    intake = intake_store.intake
    source = "# sheet:合成\nR2 | 合成货品 | 2"

    def plan(name, note=""):
        return intake.knowledge_plan(
            path=tmp_path / "unused.xlsx",
            file_name=name,
            note=note,
            owner_user_id=7,
            source_text=source,
        )

    with tenant_scope(1):
        first = plan("模板甲")
        second = plan("模板乙")
        assert first["action"] == second["action"] == "new"
        receipt = intake._ingest_knowledge(
            text=first["content"],
            source_key="模板甲",
            run_id="synthetic-run",
            owner_user_id=7,
            content_hash="unused",
            note="",
            tenant_id=1,
            expected_plan=first,
        )
        with pytest.raises(EltError) as same_run:
            intake._ingest_knowledge(
                text=first["content"],
                source_key="模板甲",
                run_id="synthetic-run",
                owner_user_id=7,
                content_hash="unused",
                note="",
                tenant_id=1,
                expected_plan=first,
            )
        assert same_run.value.code == "ELT_PREVIEW_STALE"
        assert second["source_fingerprint"] == first["source_fingerprint"]
        duplicate = intake._ingest_knowledge(
            text=second["content"],
            source_key="模板乙",
            run_id="synthetic-second",
            owner_user_id=7,
            content_hash="unused",
            note="",
            tenant_id=1,
            expected_plan=second,
        )
        assert duplicate["action"] == "skip" and duplicate["match_ref"] == receipt["match_ref"]
        legacy = {key: value for key, value in second.items() if key != "source_fingerprint"}
        assert (
            intake._ingest_knowledge(
                text=second["content"],
                source_key="旧模板",
                run_id="synthetic-legacy",
                owner_user_id=7,
                content_hash="unused",
                note="",
                tenant_id=1,
                expected_plan=legacy,
            )["action"]
            == "skip"
        )
        assert receipt["match_ref"]
        changed_note = plan("模板丙", "不同整理要求")
        assert changed_note["source_fingerprint"] != first["source_fingerprint"]
        assert changed_note["action"] == "new"


def test_knowledge_line_calls_its_own_model(intake_store, monkeypatch, tmp_path):
    from app.application.elt.llm_assist_runtime import LlmAssistResult

    seen = {}

    def knowledge(text):
        seen["text"] = text
        return LlmAssistResult(
            used_llm=True, data={"title": "送货单", "content": "演示客户乙 螺母 5"}
        )

    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setattr("app.application.elt.llm_assist.elt_llm_enabled", lambda: True)
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

    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setattr("app.application.elt.llm_assist.elt_llm_enabled", lambda: True)
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


def test_template_save_does_not_wait_for_intake_and_saved_selection_can_preview(intake_store):
    store = intake_store
    data = review(store)
    response = store.client.post(
        f"{BASE}/save", data={**data, "private_intake": "true", "template_only": "true"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["template_id"]
    assert store.starts == []
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
    result = store.client.post(f"{BASE}/intake-preview", data=data)
    assert result.status_code == 200, result.text
    status = store.client.get(f"{BASE}/reviews/{data['review_id']}/intake-status")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "created"
    assert status.json()["intake"]["run_id"] == result.json()["intake"]["run_id"]
    repeated = store.client.post(f"{BASE}/intake-preview", data=data)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["replayed"] is True
    assert repeated.json()["intake"]["run_id"] == result.json()["intake"]["run_id"]
    stale = store.client.post(
        f"{BASE}/intake-preview",
        data={
            **data,
            "selections": "[]" if data["selections"] != "[]" else '[{"sheet":"客户","cell":"A1"}]',
        },
    )

    assert stale.status_code == 409


def test_intake_releases_upload_writer_before_reading_archived_workbook(intake_store, monkeypatch):
    store = intake_store
    data = review(store)
    original = ais.workbook_text
    writes = []

    def read_after_other_writer(body):
        # A different preview can write while this worker prepares model input.
        # A flushed but uncommitted upload would hold SQLite's only writer.
        with store.factory() as db:
            db.execute(text("UPDATE elt_uploads SET file_name = file_name WHERE owner_user_id = 7"))
            db.commit()
        writes.append(True)
        return original(body)

    monkeypatch.setattr(ais, "workbook_text", read_after_other_writer)
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 200, response.text
    assert writes


def test_inflight_intake_claim_prevents_duplicate_preview(intake_store):
    from app.application.elt.service_support import dump_json, load_json, utcnow
    from app.application.reviewed_excel_review_store import _run

    store = intake_store
    data = review(store)
    with tenant_scope(1), store.factory() as db:
        run = _run(db, data["review_id"], 1, 7)
        state = load_json(run.draft_json, {})
        state["intake_attempt"] = {
            "id": "other-worker",
            "status": "running",
            "started_at": utcnow().isoformat(),
        }
        run.draft_json = dump_json(state)
        db.commit()
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 409
    assert "请勿重复提交" in response.text
    status = store.client.get(f"{BASE}/reviews/{data['review_id']}/intake-status")
    assert status.status_code == 200 and status.json()["status"] == "running"
    assert store.client.post(f"{BASE}/reviews/{data['review_id']}/intake-retry").status_code == 409
    with tenant_scope(1), store.factory() as db:
        run = _run(db, data["review_id"], 1, 7)
        assert load_json(run.draft_json, {})["intake_attempt"]["id"] == "other-worker"


def test_intake_persists_model_request_before_call(intake_store, monkeypatch):
    from types import SimpleNamespace

    from app.application.elt import llm_assist
    from app.application.elt.service_support import load_json
    from app.application.reviewed_excel_audit import current_call_id
    from app.application.reviewed_excel_review_store import _run
    from app.infrastructure.llm import structured_output

    store = intake_store
    data = review(store)
    seen = []
    monkeypatch.setenv("FHD_ELT_LLM", "on")
    monkeypatch.setattr(llm_assist, "elt_llm_enabled", lambda: True)
    monkeypatch.setattr(llm_assist, "_active_software_llm", lambda *_: (True, None, object()))
    monkeypatch.setattr(
        llm_assist, "advise_knowledge_import", lambda *_: llm_assist.LlmAssistResult()
    )

    def complete(*args, **kwargs):
        with tenant_scope(1), store.factory() as db:
            state = load_json(_run(db, data["review_id"], 1, 7).draft_json, {})
            seen.append((current_call_id(), state["intake_attempt"]["model_calls"][-1]))
        return SimpleNamespace(model="synthetic", billing={}, data={"rows": []})

    monkeypatch.setattr(structured_output, "complete_structured_sync", complete)
    result = store.client.post(f"{BASE}/intake-preview", data=data)
    assert result.status_code == 200, result.text
    assert seen and seen[0][0] == seen[0][1]["call_id"]
    assert seen[0][1]["status"] == "sent"
    assert result.json()["intake"]["model_calls"][0]["status"] == "answered"


def test_long_batched_intake_is_not_marked_unknown_after_ten_minutes():
    from datetime import timedelta

    from app.application.elt.service_support import utcnow

    started = (utcnow() - timedelta(minutes=11)).isoformat()
    assert (
        routes._intake_attempt_status({"status": "running", "started_at": started})
        == "outcome_unknown"
    )
    assert (
        routes._intake_attempt_status(
            {"status": "running", "started_at": started, "max_duration_seconds": 1800}
        )
        == "running"
    )


def test_old_intake_claim_is_unknown_without_resubmitting(intake_store):
    from datetime import timedelta

    from app.application.elt.service_support import dump_json, load_json, utcnow
    from app.application.reviewed_excel_review_store import _run

    store = intake_store
    data = review(store)
    with tenant_scope(1), store.factory() as db:
        run = _run(db, data["review_id"], 1, 7)
        state = load_json(run.draft_json, {})
        state["intake_attempt"] = {
            "id": "old",
            "status": "running",
            "started_at": (utcnow() - timedelta(minutes=11)).isoformat(),
        }
        run.draft_json = dump_json(state)
        db.commit()
    status = store.client.get(f"{BASE}/reviews/{data['review_id']}/intake-status")
    assert status.status_code == 200 and status.json()["status"] == "outcome_unknown"
    assert store.client.post(f"{BASE}/intake-preview", data=data).status_code == 409
    response = store.client.post(f"{BASE}/reviews/{data['review_id']}/intake-retry")
    assert response.status_code == 200
    with tenant_scope(1), store.factory() as db:
        state = load_json(_run(db, data["review_id"], 1, 7).draft_json, {})
        assert "intake_attempt" not in state
        assert state["intake_attempt_history"][-1]["id"] == "old"


@pytest.mark.parametrize("reuse_existing", [False, True])
def test_saved_template_continues_to_approval_once_without_duplicate_template(
    intake_store, monkeypatch, reuse_existing
):
    from app.application import reviewed_excel_template_blocks as blocks
    from app.db.models.approval import ApprovalRequest

    store = intake_store
    monkeypatch.setattr(blocks, "get_app_data_dir", lambda: str(store.root))
    existing = None
    if reuse_existing:
        initial = review(store)
        created = store.client.post(
            f"{BASE}/save", data={**initial, "private_intake": "true", "template_only": "true"}
        )
        assert created.status_code == 200, created.text
        assert created.json()["reused"] is False
        existing = created.json()["template_id"]
    data = review(store)
    if reuse_existing:
        assert data["review_id"] != initial["review_id"]
    template_request = {**data, "private_intake": "true", "template_only": "true"}
    saved = store.client.post(f"{BASE}/save", data=template_request)
    assert saved.status_code == 200, saved.text
    assert saved.json()["reused"] is reuse_existing
    if reuse_existing:
        assert saved.json()["template_id"] == existing
    template_replay = store.client.post(f"{BASE}/save", data=template_request)
    assert template_replay.status_code == 200, template_replay.text
    assert template_replay.json()["replayed"]
    assert template_replay.json()["reused"] is reuse_existing
    preview = store.client.post(f"{BASE}/intake-preview", data=data)
    assert preview.status_code == 200, preview.text
    plan = preview.json()["intake"]
    store.executor.futures[-1].result(timeout=10)
    with tenant_scope(1), store.factory() as db:
        run = store.service.get_run(db, run_id=plan["run_id"], owner_user_id=7)
        prepared_path = Path(db.get(EltUpload, plan["upload_id"]).storage_path)
        prepared = prepared_path.read_bytes()
        template_path = Path(
            db.execute(text("SELECT original_file_path FROM templates")).scalar_one()
        )
        template_body = template_path.read_bytes()
        assert prepared_path != template_path
    submit = {
        **data,
        "private_intake": "true",
        "intake_run_id": plan["run_id"],
        "preview_revision": run["preview_revision"],
    }
    result = store.client.post(f"{BASE}/save", data=submit)
    assert result.status_code == 200, result.text
    assert result.json()["template_id"] == saved.json()["template_id"]
    assert result.json()["reused"] is reuse_existing
    assert result.json()["auto_ingest"]["status"] == "awaiting_approval"
    again = store.client.post(f"{BASE}/save", data=submit)
    assert again.status_code == 200, again.text
    assert again.json()["replayed"]
    assert again.json()["template_id"] == saved.json()["template_id"]
    assert again.json()["reused"] is reuse_existing
    assert again.json()["auto_ingest"] == result.json()["auto_ingest"]
    with store.factory() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
        assert db.query(ApprovalRequest).count() == 1
        assert db.query(PurchaseUnit).count() == 0
        receipt = json.loads(db.get(EltRun, data["review_id"]).receipt_json)
        assert receipt["reused"] is reuse_existing
        assert receipt["request_key"] != receipt["intake_request_key"]
    assert list(template_path.parent.glob("*.xlsx")) == [template_path]
    assert template_path.read_bytes() == template_body
    assert prepared_path.read_bytes() == prepared
    batch = ais._load_ledger(1)["batches"][result.json()["auto_ingest"]["batch_id"]]
    assert batch["source_path"] == str(prepared_path)
    assert batch["prepared_plan"]["run_id"] == plan["run_id"]
    assert store.starts == []
    changed = store.client.post(f"{BASE}/save", data={**submit, "candidate_id": "wrong-candidate"})
    assert changed.status_code == 409


@pytest.mark.parametrize("fault", ["revision", "permission", "mod", "candidate"])
def test_saved_template_continuation_rejects_changed_scope(intake_store, fault):
    store = intake_store
    data, plan, business = prepare(store)
    template = {
        key: value
        for key, value in data.items()
        if key not in {"intake_run_id", "preview_revision"}
    }
    saved = store.client.post(f"{BASE}/save", data={**template, "template_only": "true"})
    assert saved.status_code == 200
    if fault == "revision":
        data["preview_revision"] = "stale"
    elif fault == "permission":
        store.actor["execute"] = False
    elif fault == "mod":
        store.actor["mod"] = "different"
    else:
        data["candidate_id"] = "different"
    result = store.client.post(f"{BASE}/save", data=data)
    assert result.status_code in (403, 409), result.text
    assert store.starts == []
    with store.factory() as db:
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
        assert db.query(PurchaseUnit).count() == 0


def test_saved_template_lost_submission_is_not_sent_twice(intake_store, monkeypatch):
    store = intake_store
    data, _plan, _business = prepare(store)
    template = {
        key: value
        for key, value in data.items()
        if key not in {"intake_run_id", "preview_revision"}
    }
    assert (
        store.client.post(f"{BASE}/save", data={**template, "template_only": "true"}).status_code
        == 200
    )
    calls = []

    def unknown(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("synthetic lost response")

    monkeypatch.setattr("app.application.elt.docking_approval.submit_docking_write", unknown)
    first = store.client.post(f"{BASE}/save", data=data)
    again = store.client.post(f"{BASE}/save", data=data)
    assert first.status_code == again.status_code == 200
    assert again.json()["replayed"]
    assert len(calls) == 1


def test_direct_intake_save_cannot_be_reopened_as_a_template_continuation(
    intake_store, monkeypatch
):
    store = intake_store
    data, _plan, _business = prepare(store)
    calls = []

    def submit(**kwargs):
        calls.append(kwargs)
        return {"success": True, "status": "awaiting_approval", "batch_id": "single-batch"}

    monkeypatch.setattr("app.application.elt.docking_approval.submit_docking_write", submit)
    assert store.client.post(f"{BASE}/save", data=data).status_code == 200
    changed = store.client.post(f"{BASE}/save", data={**data, "valid_rows_only": "true"})
    assert changed.status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize("field,value,status", [("execute", False, 403), ("mod", "other-mod", 409)])
def test_saved_continuation_rechecks_permission_at_write_boundary(
    intake_store, monkeypatch, field, value, status
):
    store = intake_store
    data, _plan, _business = prepare(store)
    template = {
        key: value
        for key, value in data.items()
        if key not in {"intake_run_id", "preview_revision"}
    }
    assert (
        store.client.post(f"{BASE}/save", data={**template, "template_only": "true"}).status_code
        == 200
    )
    original = routes._recheck

    def changed(request, expected):
        original(request, expected)
        store.actor[field] = value

    monkeypatch.setattr(routes, "_recheck", changed)
    result = store.client.post(f"{BASE}/save", data=data)
    assert result.status_code == status, result.text
    assert store.starts == []
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1


@pytest.mark.parametrize("phase", ["before_claim", "during_validation"])
def test_saved_continuation_serializes_classification_version(intake_store, monkeypatch, phase):
    import sqlite3
    from unittest.mock import Mock

    from app.application.elt.service_support import load_json

    store = intake_store
    data, _plan, _business = prepare(store)
    template = {
        key: value
        for key, value in data.items()
        if key not in {"intake_run_id", "preview_revision"}
    }
    assert (
        store.client.post(f"{BASE}/save", data={**template, "template_only": "true"}).status_code
        == 200
    )
    with store.factory() as db:
        saved = db.get(EltRun, data["review_id"])
        classification_id = load_json(saved.summary_json, {})["selected_region"][
            "classification_id"
        ]
        original = db.get(EltRun, classification_id).draft_json
    changed = load_json(original, {})
    changed["versions"][-1]["version"] = "concurrent-classification-version"
    blocked = []

    def mutate_classification():
        with sqlite3.connect(store.engine.url.database, timeout=0) as other:
            try:
                other.execute(
                    "UPDATE elt_runs SET draft_json = ? WHERE id = ?",
                    (json.dumps(changed), classification_id),
                )
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc)
                blocked.append(True)
            else:
                blocked.append(False)

    if phase == "before_claim":
        original_recheck = routes._recheck

        def recheck(request, expected):
            original_recheck(request, expected)
            mutate_classification()

        monkeypatch.setattr(routes, "_recheck", recheck)
    else:
        original_validate = store.intake.validate_prepared
        calls = 0

        def validate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                mutate_classification()
            return original_validate(*args, **kwargs)

        monkeypatch.setattr(store.intake, "validate_prepared", validate)
    submit = Mock(return_value={"success": True, "status": "awaiting_approval", "batch_id": "once"})
    monkeypatch.setattr("app.application.elt.docking_approval.submit_docking_write", submit)
    result = store.client.post(f"{BASE}/save", data=data)
    assert result.status_code == (409 if phase == "before_claim" else 200), result.text
    assert blocked == [phase == "during_validation"]
    assert submit.call_count == (0 if phase == "before_claim" else 1)
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert db.execute(text("SELECT count(*) FROM templates")).scalar_one() == 1
        assert db.get(EltRun, classification_id).status == "classification_ready"
        receipt = load_json(db.get(EltRun, data["review_id"]).receipt_json, {})
        assert bool(receipt.get("intake_request_key")) == (phase == "during_validation")
