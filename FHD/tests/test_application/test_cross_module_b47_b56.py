"""Real Excel, SQLite, workflow, employee, and audit evidence for B47–B56."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.db_base import Base
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def acceptance_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'business.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    with factory() as db:
        yield db, tmp_path / "workspace", audit_path
    engine.dispose()


def test_cross_module_business_chain_s01_through_s04(acceptance_db):
    from tests.fixtures.cross_module_acceptance import run_cross_module_acceptance

    db, workspace, audit_path = acceptance_db
    with tenant_scope(1):
        report = run_cross_module_acceptance(
            db=db,
            workspace=workspace,
            user_id="7",
            tenant_id="1",
            session_id="session-b47",
        )
    assert audit_path.is_file()
    assert report["scenarios"]["S04"] == "PASS", report["failed"]
    assert report["verdict"] == "PASS", report["failed"]
    assert report["ids"]["task_id"]
    assert report["ids"]["trace_id"]
    assert report["verification"]["stored_count"] == 2
    assert report["verification"]["status"] == "partial"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("source_mode", ["workspace", "owned_upload"])
@pytest.mark.parametrize(
    "valid_rows",
    [
        [
            ["西南材料", "SW-42", "防护涂层", "10kg", "17.65"],
            ["东海配件", "DH-5", "密封组件", "5件", "63.20"],
        ],
        [
            ["北方电气", "NB-77", "继电器", "220V", "0.10"],
            ["北方电气", "NB-78", "断路器", "380V", "45.05"],
        ],
    ],
)
def test_cross_module_http_submit_approve_download_history(
    tmp_path, monkeypatch, valid_rows, source_mode
):
    """POST /api/agent/tasks drives the chain; approval and the file come back over HTTP."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
        set_task_execution_repository_for_tests,
    )
    from app.application.elt.service_uploads import UploadServiceMixin
    from app.application.workflow.approval_service import get_approval_service
    from app.db.db_base import Base
    from app.db.models.approval import ApprovalRequest
    from app.db.models.elt import EltUpload
    from app.db.models.product import Product
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User
    from app.fastapi_routes.approval import router as approval_router
    from app.fastapi_routes.domains.admin_audit.admin_audit_routes import (
        router as audit_router,
    )
    from app.fastapi_routes.domains.agent.agent_routes import router as agent_router
    from app.middleware.industry_context import IndustryContextMiddleware
    from app.utils.time import utc_now_naive
    from tests.fixtures.cross_module_business import _build_source_workbook

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    set_agent_run_repository_for_tests(InMemoryAgentRunRepository())
    set_task_execution_repository_for_tests(InMemoryTaskExecutionRepository())
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(workspace))
    source = workspace / "upload-shipment.xlsx"
    _build_source_workbook(
        source,
        rows=[
            *valid_rows,
            ["异常客户", "BAD", "", "1件", "9"],
            ["异常客户", "NEG", "负价样品", "1件", "-3"],
            ["合计", "", "", "", ""],
        ],
    )
    expected_products = [
        {
            "unit": row[0],
            "model_number": row[1],
            "name": row[2],
            "specification": row[3],
            "price": row[4],
        }
        for row in valid_rows
    ]
    preserved = ("华东涂料", "HX-1", "99.00")
    expected_rows = sorted([preserved, *((row[0], row[1], row[4]) for row in valid_rows)])
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    original_sha = _sha256(source)
    original_bytes = source.read_bytes()
    db = factory()
    try:
        user = User(
            username="b47-owner",
            password="not-a-secret",
            display_name="b47-owner",
            role="admin",
            is_active=True,
            tenant_id=1,
            tier="enterprise",
        )
        db.add(user)
        db.flush()
        expires = utc_now_naive() + timedelta(days=1)
        db.add(
            UserSession(
                session_id="sid-http-1",
                user_id=user.id,
                expires_at=expires,
                tenant_id=1,
                account_kind="enterprise",
            )
        )
        db.add(
            UserSession(
                session_id="sid-http-2",
                user_id=user.id,
                expires_at=expires,
                tenant_id=1,
                account_kind="enterprise",
            )
        )
        db.add(
            Product(
                tenant_id=1,
                unit=preserved[0],
                model_number=preserved[1],
                name="已有产品",
                price=preserved[2],
            )
        )
        db.add(
            Product(
                tenant_id=2,
                unit=valid_rows[0][0],
                model_number=valid_rows[0][1],
                name="其他租户产品",
                price="88.00",
            )
        )
        db.commit()
        user_id = int(user.id)
    finally:
        db.close()

    def owned_upload(tenant_id: int, owner_user_id: int) -> Path:
        with factory.begin() as db, tenant_scope(tenant_id):
            saved = UploadServiceMixin().save_upload(
                db,
                owner_user_id=owner_user_id,
                file_name="business.xlsx",
                content_type=None,
                stream=BytesIO(original_bytes),
            )
            return Path(db.get(EltUpload, saved["upload_id"]).storage_path)

    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(original_bytes)
    forbidden_sources = [outside, owned_upload(1, user_id + 1), owned_upload(2, user_id)]
    if source_mode == "owned_upload":
        source = owned_upload(1, user_id)

    app = FastAPI()
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(agent_router)
    app.include_router(approval_router)
    app.include_router(audit_router)
    body = {
        "task_id": "task-http-b47",
        "title": "发货明细导入",
        "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入产品库，并调用已发布 MOD 做后续读取",
        "tool_id": "products",
        "action": "batch_create",
        "params": {
            "products": expected_products,
            "file_path": str(source),
        },
        "runtime_context": {"conversation_id": "session-b47", "session_id": "session-b47"},
    }
    evidence: dict = {
        "verdict": "FAIL",
        "scenarios": {"S01": "FAIL", "S02": "FAIL", "S03": "FAIL", "S04": "FAIL"},
        "http": {},
        "checks": {},
        "failed": [],
    }

    def persist(note: str) -> None:
        evidence["note"] = note
        out = evidence_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def product_rows() -> list[tuple[str, str, str]]:
        session = factory()
        try:
            with tenant_scope(1):
                rows = (
                    session.query(Product)
                    .filter(Product.tenant_id == 1)
                    .order_by(Product.unit.asc(), Product.model_number.asc())
                    .all()
                )
                return [(str(row.unit), str(row.model_number), str(row.price)) for row in rows]
        finally:
            session.close()

    try:
        with TestClient(app) as client:
            try:
                client.cookies.set("session_id", "sid-http-1")
                for index, forbidden in enumerate(forbidden_sources):
                    denied_body = deepcopy(body)
                    denied_body["task_id"] = f"task-http-forbidden-{index}"
                    denied_body["params"]["file_path"] = str(forbidden)
                    denied = client.post("/api/agent/tasks", json=denied_body)
                    assert denied.status_code == 400, denied.text
                    assert product_rows() == [preserved]
                first = client.post("/api/agent/tasks", json=body)
                second = client.post("/api/agent/tasks", json=body)
                evidence["http"]["submit"] = {
                    "status": first.status_code,
                    "deduplicated": first.json().get("deduplicated"),
                    "status_text": ((first.json().get("data") or {}).get("status")),
                }
                evidence["http"]["duplicate"] = {
                    "status": second.status_code,
                    "deduplicated": second.json().get("deduplicated"),
                    "run_id": ((second.json().get("data") or {}).get("run_id")),
                }
                rows_after_duplicate = product_rows()
                evidence["http"]["rows_after_duplicate_submit"] = rows_after_duplicate
                created = first.json()
                run = (created.get("data") or {}) if first.status_code < 500 else {}
                metadata = run.get("metadata") or {}
                approval_db_id = metadata.get("approval_request_db_id")
                task_id = ((run.get("metadata") or {}).get("runtime_context") or {}).get(
                    "task_id"
                ) or body["task_id"]
                trace_id = metadata.get("trace_id")
                session = factory()
                try:
                    stored = (
                        session.get(ApprovalRequest, int(approval_db_id))
                        if approval_db_id
                        else None
                    )
                    stored_status = None if stored is None else str(stored.status)
                    stored_snapshot = bool(
                        stored
                        and stored.business_data
                        and "durable_workflow_snapshot" in stored.business_data
                    )
                    request_no = None if stored is None else str(stored.request_no)
                finally:
                    session.close()
                from app.application.agent_orchestrator.cross_module_chain import (
                    resume_cross_module_http,
                )
                from app.application.workflow.approval_persistence import (
                    load_workflow_snapshot_for_execution,
                )

                with tenant_scope(1):
                    snapshot = load_workflow_snapshot_for_execution(str(request_no))
                    assert snapshot is not None
                    assert snapshot["plan"].nodes[0].params["products"] == expected_products
                    for corrupt in ("params", "checkpoint", "actor"):
                        changed = deepcopy(snapshot)
                        if corrupt == "params":
                            changed["plan"].nodes[0].params["products"][0]["price"] = "999.00"
                        elif corrupt == "checkpoint":
                            changed["runtime_context"]["cross_module_checkpoint"]["qualifying"][0][
                                "price"
                            ] = "999.00"
                        else:
                            changed["runtime_context"]["user_id"] = str(user_id + 1)
                        rejected = resume_cross_module_http(
                            changed, request_id=str(request_no), loaded_from_storage=True
                        )
                        assert rejected["success"] is False
                assert product_rows() == [preserved]
                service = get_approval_service()
                service._pending_requests.clear()
                service._pending_workflows.clear()
                service._request_metadata.clear()
                memory_cleared = (
                    service.get_pending_request(str(metadata.get("approval_request_id") or ""))
                    is None
                )
                approved = client.post(
                    f"/api/approval/requests/{approval_db_id}/approve",
                    json={"opinion": "同意导入合格行"},
                )
                evidence["http"]["approve"] = {
                    "status": approved.status_code,
                    "success": (approved.json() or {}).get("success"),
                    "stored_status_before": stored_status,
                    "snapshot_in_db_before": stored_snapshot,
                    "memory_cleared_before": memory_cleared,
                    "request_no": request_no,
                }
                rows_after_approve = product_rows()
                evidence["http"]["rows_after_approve"] = rows_after_approve
                session = factory()
                try:
                    stored_after = (
                        session.get(ApprovalRequest, int(approval_db_id))
                        if approval_db_id
                        else None
                    )
                    status_after = None if stored_after is None else str(stored_after.status)
                finally:
                    session.close()
                evidence["http"]["approval_status_after"] = status_after
                task_view = client.get(f"/api/agent/tasks/{task_id}")
                run_id = str(
                    (task_view.json().get("data") or {}).get("active_run_id")
                    or run.get("run_id")
                    or ""
                )
                run_view = client.get(f"/api/agent/runs/{run_id}") if run_id else None
                artifacts = []
                if run_view is not None and run_view.status_code == 200:
                    artifacts = (run_view.json().get("data") or {}).get("artifacts") or []
                download = None
                if artifacts:
                    download = client.get(str(artifacts[0].get("uri") or ""))
                download_sha = (
                    hashlib.sha256(download.content).hexdigest() if download is not None else ""
                )
                result_file = Path(
                    str(
                        (metadata.get("runtime_context") or {})
                        .get("cross_module_checkpoint", {})
                        .get("result_path")
                        or workspace / "result.xlsx"
                    )
                )
                file_sha = _sha256(result_file)
                evidence["http"]["download"] = {
                    "status": None if download is None else download.status_code,
                    "sha256": download_sha,
                    "file_sha256": file_sha,
                    "bytes": 0 if download is None else len(download.content),
                }
                history = TestClient(app)
                history.cookies.set("session_id", "sid-http-2")
                history_task = history.get(f"/api/agent/tasks/{task_id}")
                history_audit = history.get("/api/admin/audit-logs?limit=50")
                history_file = (
                    history.get(str(artifacts[0].get("uri") or "")) if artifacts else None
                )
                evidence["http"]["history"] = {
                    "task_status": history_task.status_code,
                    "audit_status": history_audit.status_code,
                    "file_status": None if history_file is None else history_file.status_code,
                    "task_id": task_id,
                    "trace_id": trace_id,
                }
                business = {}
                if run_view is not None and run_view.status_code == 200:
                    business = ((run_view.json().get("data") or {}).get("final_output") or {}).get(
                        "business_result"
                    ) or {}
                source_unchanged = (
                    source.read_bytes() == original_bytes and _sha256(source) == original_sha
                )
                holes = {
                    "1_http_entry": first.status_code == 202 and bool(task_id),
                    "2_persisted_approval": bool(stored_snapshot)
                    and memory_cleared
                    and approved.status_code == 200
                    and status_after == "approved"
                    and rows_after_duplicate == [preserved]
                    and rows_after_approve == expected_rows,
                    "3_http_download_sha": download is not None
                    and download.status_code == 200
                    and download_sha
                    and download_sha == file_sha
                    and download.content == result_file.read_bytes(),
                    "4_duplicate_submit": second.status_code in {200, 202}
                    and second.json().get("deduplicated") is True
                    and rows_after_duplicate == [preserved]
                    and rows_after_approve == expected_rows,
                    "5_second_session": history_task.status_code == 200
                    and task_id in history_task.text
                    and history_audit.status_code == 200
                    and str(trace_id) in history_audit.text
                    and history_file is not None
                    and history_file.status_code == 200
                    and history_file.content == (download.content if download is not None else b""),
                }
                evidence["http"]["holes"] = holes
                evidence["ids"] = {
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "approval_request_db_id": approval_db_id,
                    "request_no": request_no,
                    "original_sha256": original_sha,
                    "result_sha256": download_sha,
                }
                evidence["verification"] = {
                    "status": business.get("status"),
                    "success": business.get("success"),
                    "summary": business.get("summary"),
                    "stored_rows": rows_after_approve,
                    "source_unchanged": source_unchanged,
                    "anomalies_reported": "异常" in str(business.get("summary") or ""),
                }
                evidence["scenarios"] = {
                    "S01": "PASS" if holes["1_http_entry"] else "FAIL",
                    "S02": "PASS" if holes["2_persisted_approval"] else "FAIL",
                    "S03": "PASS"
                    if holes["3_http_download_sha"] and business.get("employee_success")
                    else "FAIL",
                    "S04": "PASS"
                    if source_unchanged
                    and business.get("status") == "partial"
                    and business.get("success") is False
                    else "FAIL",
                }
                evidence["checks"] = {
                    "HTTP-01": {
                        "status": "PASS" if holes["1_http_entry"] else "FAIL",
                        "detail": first.status_code,
                    },
                    "HTTP-02": {
                        "status": "PASS" if holes["2_persisted_approval"] else "FAIL",
                        "detail": status_after,
                    },
                    "HTTP-03": {
                        "status": "PASS" if holes["3_http_download_sha"] else "FAIL",
                        "detail": download_sha,
                    },
                    "HTTP-04": {
                        "status": "PASS" if holes["4_duplicate_submit"] else "FAIL",
                        "detail": second.status_code,
                    },
                    "HTTP-05": {
                        "status": "PASS" if holes["5_second_session"] else "FAIL",
                        "detail": evidence["http"]["history"],
                    },
                    "S04-original-unchanged": {
                        "status": "PASS" if source_unchanged else "FAIL",
                        "detail": original_sha,
                    },
                    "S04-partial-anomalies": {
                        "status": "PASS" if evidence["scenarios"]["S04"] == "PASS" else "FAIL",
                        "detail": business.get("summary"),
                    },
                    "B47-B56-harness": {
                        "status": "NOT TESTED",
                        "detail": "Previous matrix was only run_cross_module_acceptance. Not marked PASS on this HTTP path.",
                    },
                }
                evidence["failed"] = [
                    key for key, item in evidence["checks"].items() if item["status"] == "FAIL"
                ]
                evidence["verdict"] = (
                    "PARTIAL PASS"
                    if holes and all(holes.values()) and evidence["scenarios"]["S04"] == "PASS"
                    else "FAIL"
                )
                anomaly_file = result_file.with_name(result_file.stem + "-anomalies.csv")
                if anomaly_file.is_file():
                    (evidence_dir / "result-anomalies.csv").write_bytes(anomaly_file.read_bytes())
                    (evidence_dir / "result.xlsx").write_bytes(result_file.read_bytes())
                    (evidence_dir / "upload-shipment.xlsx").write_bytes(original_bytes)
                with factory() as other_db, tenant_scope(2):
                    assert str(other_db.query(Product).one().price) == "88.00"
            finally:
                failure = sys.exception()
                if failure is not None:
                    evidence["error"] = f"{type(failure).__name__}: {failure}"
                persist("exception" if failure is not None else evidence["verdict"])
    finally:
        set_task_execution_repository_for_tests(None)
        set_agent_run_repository_for_tests(None)
        engine.dispose()
    assert evidence["verdict"] == "PARTIAL PASS", evidence
    assert all(evidence["http"]["holes"].values()), evidence["http"]
