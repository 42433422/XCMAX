"""Real Excel, SQLite, workflow, employee, and audit evidence for B47–B56."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
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
    from app.application.agent_orchestrator.cross_module_chain import (
        run_cross_module_acceptance,
    )

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


def test_cross_module_http_submit_approve_download_history(tmp_path, monkeypatch):
    """POST /api/agent/tasks drives the chain; approval and the file come back over HTTP."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator.cross_module_chain import _build_source_workbook
    from app.application.agent_orchestrator.run_repository import (
        InMemoryAgentRunRepository,
        set_agent_run_repository_for_tests,
    )
    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
        set_task_execution_repository_for_tests,
    )
    from app.application.workflow.approval_service import get_approval_service
    from app.db.db_base import Base
    from app.db.models.approval import ApprovalRequest
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
    source = workspace / "upload-shipment.xlsx"
    _build_source_workbook(source)
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
        db.commit()
        user_id = int(user.id)
    finally:
        db.close()

    app = FastAPI()
    app.add_middleware(IndustryContextMiddleware)
    app.include_router(agent_router)
    app.include_router(approval_router)
    app.include_router(audit_router)
    body = {
        "task_id": "task-http-b47",
        "title": "发货明细导入",
        "message": "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入华东涂料产品库，并调用已发布 MOD 做后续读取",
        "tool_id": "products",
        "action": "batch_create",
        "params": {
            "products": [
                {
                    "unit": "华东涂料",
                    "model_number": "HX-1",
                    "name": "内墙底漆",
                    "price": "12.50",
                }
            ],
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
        out = Path("docs/evidence/e2e/cross-module-b47-b56")
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def product_rows() -> list[tuple[str, str]]:
        session = factory()
        try:
            with tenant_scope(1):
                rows = (
                    session.query(Product)
                    .filter(Product.unit == "华东涂料")
                    .order_by(Product.model_number.asc())
                    .all()
                )
                return [(str(row.model_number), str(row.price)) for row in rows]
        finally:
            session.close()

    try:
        with TestClient(app) as client:
            try:
                client.cookies.set("session_id", "sid-http-1")
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
                file_sha = _sha256(
                    Path(
                        str(
                            (metadata.get("runtime_context") or {})
                            .get("cross_module_checkpoint", {})
                            .get("result_path")
                            or workspace / "result.xlsx"
                        )
                    )
                )
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
                    and rows_after_duplicate == []
                    and ("HX-1", "15.00") in rows_after_approve,
                    "3_http_download_sha": download is not None
                    and download.status_code == 200
                    and download_sha
                    and download_sha == file_sha
                    and download.content == Path(workspace / "result.xlsx").read_bytes(),
                    "4_duplicate_submit": second.status_code in {200, 202}
                    and second.json().get("deduplicated") is True
                    and rows_after_duplicate == []
                    and len(rows_after_approve) == 2,
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
                if (workspace / "result-anomalies.csv").is_file():
                    target = Path("docs/evidence/e2e/cross-module-b47-b56")
                    (target / "result-anomalies.csv").write_bytes(
                        (workspace / "result-anomalies.csv").read_bytes()
                    )
                    (target / "result.xlsx").write_bytes((workspace / "result.xlsx").read_bytes())
                    (target / "upload-shipment.xlsx").write_bytes(original_bytes)
                persist(evidence["verdict"])
            except Exception as exc:
                evidence["error"] = f"{type(exc).__name__}: {exc}"
                persist("exception")
                raise
    finally:
        set_task_execution_repository_for_tests(None)
        set_agent_run_repository_for_tests(None)
        engine.dispose()
    assert evidence["verdict"] == "PARTIAL PASS", evidence
    assert all(evidence["http"]["holes"].values()), evidence["http"]
