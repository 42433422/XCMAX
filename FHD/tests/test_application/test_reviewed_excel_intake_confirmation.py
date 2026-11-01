"""Real prepared XLSX runs bind reviewed intake consent to scope and content."""

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
from app.db.models import PurchaseUnit
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.fastapi_routes import reviewed_excel_template as routes
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.path_io import path_utils
from tests.test_application.test_etl_auto_ingest_service import rag_service as rag_service
from tests.test_application.test_etl_preview_task_boundaries import ObservedExecutor
from tests.test_application.test_reviewed_excel_template import review_store as review_store

BASE = "/api/templates/reviewed-excel"


@pytest.fixture
def intake_store(review_store, rag_service, monkeypatch):
    store = review_store
    Base.metadata.create_all(store.engine)
    store.factory = sessionmaker(bind=store.engine)
    store.service = EltService()
    store.intake = ais.AutoIngestService()
    store.rag = rag_service
    store.starts = []
    store.actor.update(execute=True, mod="erp-test")
    monkeypatch.setenv("FHD_ETL_LLM", "off")
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
        data={"expected_actor": "1:7"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "review_id": data["review_id"],
        "proposal_version": data["proposal"]["version"],
        "candidate_id": "preserve",
        "selections": "[]",
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


def test_exact_prepared_run_is_confirmed_once_without_recleaning(intake_store, monkeypatch):
    store = intake_store
    data, plan, business = prepare(store)
    assert plan["target_type"] == "customers"
    assert plan["knowledge"]["documents"] == 1
    assert business["summary"]["new"] == 2
    assert_no_writes(store)
    with store.factory() as db:
        before = (db.query(EltRun).count(), db.query(EltUpload).count())
        prepared = Path(db.get(EltUpload, plan["upload_id"]).storage_path).read_bytes()

    def no_reclean(*args, **kwargs):
        raise AssertionError("confirmed candidate must reuse the staged bytes")

    monkeypatch.setattr(routes, "clean_workbook", no_reclean)
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
    receipt = store.intake.get_batch(
        tenant_id=1, owner_user_id=7, batch_id=result["auto_ingest"]["batch_id"]
    )
    assert receipt["status"] == "applied"
    assert receipt["business_progress"]["pct"] == 100
    assert len(store.starts) == 1
    assert store.starts[0]["prepared_plan"]["run_id"] == plan["run_id"]
    assert store.starts[0]["prepared_plan"]["preview_revision"] == data["preview_revision"]
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
            Path(db.get(EltUpload, plan["upload_id"]).storage_path).write_bytes(b"changed")
        elif change == "source_bytes":
            review_run = db.get(EltRun, data["review_id"])
            Path(db.get(EltUpload, review_run.upload_id).storage_path).write_bytes(b"changed")
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
    store.actor[field] = value
    response = store.client.post(f"{BASE}/intake-preview", data=data)
    assert response.status_code == 403
    assert_no_writes(store)
    with store.factory() as db:
        assert db.query(EltRun).count() == 1
        assert db.query(EltUpload).count() == 1


def test_private_intake_requires_preview_and_unscoped_attendance_is_refused(intake_store):
    store = intake_store
    data = review(store)
    response = store.client.post(f"{BASE}/save", data={**data, "private_intake": "true"})
    assert response.status_code == 409
    response = store.client.post(f"{BASE}/intake-preview", data={**data, "composer_note": "考勤"})
    assert response.status_code == 409 and "业务空间" in response.text
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
