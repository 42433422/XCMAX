from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.db.models  # noqa: F401
from app.application.tutorial_v2.scope import resolve_tutorial_scope
from app.application.tutorial_v2.service import (
    SALES_SENTENCE,
    TutorialServiceError,
    TutorialV2Service,
)
from app.db.base import Base
from app.db.models.accounting import JournalEntry
from app.db.models.agent import AgentRunRecord, AgentTaskExecutionRecord, AgentTaskRecord
from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRecord, ApprovalRequest
from app.db.models.customer import Customer
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.db.models.product import Product
from app.db.models.receivable_allocation import ReceivableAllocation
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.tenant import Tenant
from app.db.models.tutorial import TutorialStepEvidence
from app.db.models.user import User
from app.infrastructure.tenant_scope import tenant_scope


def test_fresh_runtime_bootstrap_creates_tutorial_v2_tables():
    from app.db.init_db import init_tutorial_v2_tables

    engine = create_engine("sqlite+pysqlite:///:memory:")
    init_tutorial_v2_tables(engine)
    assert {
        "tutorial_workspaces",
        "tutorial_runs",
        "tutorial_step_evidence",
    }.issubset(set(sqlalchemy_inspect(engine).get_table_names()))
    init_tutorial_v2_tables(engine)
    engine.dispose()


@pytest.fixture()
def tutorial_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    source = Tenant(code="source", name="正式企业", is_active=True)
    other_source = Tenant(code="source-2", name="另一个企业", is_active=True)
    session.add_all([source, other_source])
    session.flush()
    users = [
        User(
            username="learner-1",
            password="test",
            display_name="学习者一",
            role="owner",
            tenant_id=source.id,
            is_active=True,
        ),
        User(
            username="learner-2",
            password="test",
            display_name="学习者二",
            role="user",
            tenant_id=source.id,
            is_active=True,
        ),
        User(
            username="learner-3",
            password="test",
            display_name="其他企业用户",
            role="owner",
            tenant_id=other_source.id,
            is_active=True,
        ),
    ]
    session.add_all(users)
    session.commit()
    yield session, users
    session.close()
    engine.dispose()


def _request(path: str, method: str, run_id: str) -> Request:
    headers = [(b"cookie", f"xcagi_tutorial_run={run_id}".encode())]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )


def test_each_user_gets_an_independent_shadow_tenant_and_source_data_never_changes(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    with tenant_scope(users[0].tenant_id):
        db.add(Customer(customer_name="正式客户"))
        db.commit()

    run_one = service.start_run(db, users[0], "master-data")
    run_two = service.start_run(db, users[1], "master-data")
    assert run_one.workspace.tutorial_tenant_id != run_two.workspace.tutorial_tenant_id
    assert run_one.workspace.tutorial_tenant_id != users[0].tenant_id

    with tenant_scope(run_one.workspace.tutorial_tenant_id):
        db.add(Customer(customer_name="客户B"))
        db.commit()
        assert [row.customer_name for row in db.query(Customer).all()] == ["客户B"]
    with tenant_scope(run_two.workspace.tutorial_tenant_id):
        assert db.query(Customer).count() == 0
    with tenant_scope(users[0].tenant_id):
        assert [row.customer_name for row in db.query(Customer).all()] == ["正式客户"]


def test_required_steps_verify_server_state_and_repeat_verification_is_idempotent(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    run = service.start_run(db, users[0], "master-data")
    service.enter_run(db, users[0], run.id)

    _run, failed = service.verify_step(
        db,
        users[0],
        run.id,
        "create-customer",
        cookie_run_id=run.id,
    )
    assert failed.status == "failed"
    assert failed.result_code == "customer_not_ready"

    with tenant_scope(run.workspace.tutorial_tenant_id):
        customer = Customer(customer_name="客户B")
        product = Product(name="A 产品", price=Decimal("100"), quantity=100, unit="个")
        db.add_all([customer, product])
        db.commit()
    run, passed = service.verify_step(
        db,
        users[0],
        run.id,
        "create-customer",
        cookie_run_id=run.id,
    )
    attempts = passed.attempt_count
    run, repeated = service.verify_step(
        db,
        users[0],
        run.id,
        "create-customer",
        cookie_run_id=run.id,
    )
    assert repeated.status == "passed"
    assert repeated.attempt_count == attempts
    run, product_evidence = service.verify_step(
        db,
        users[0],
        run.id,
        "create-product",
        cookie_run_id=run.id,
    )
    assert product_evidence.status == "passed"
    assert run.status == "completed"


def test_cookie_scope_validates_owner_course_allowlist_and_expiry_state(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    run = service.start_run(db, users[0], "master-data")

    customer_write = resolve_tutorial_scope(
        db,
        _request("/customers", "POST", run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert customer_write.switched is True
    assert customer_write.tutorial_tenant_id == run.workspace.tutorial_tenant_id

    forbidden = resolve_tutorial_scope(
        db,
        _request("/api/settings", "POST", run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert forbidden.error_code == "tutorial_scope_denied"

    task_run = service.start_run(db, users[0], "task-workspace")
    chat_write = resolve_tutorial_scope(
        db,
        _request("/api/ai/unified_chat", "POST", task_run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert chat_write.switched is True
    assert chat_write.tutorial_tenant_id == task_run.workspace.tutorial_tenant_id

    mod_chat_write = resolve_tutorial_scope(
        db,
        _request("/api/mod/xcagi-planner-bridge/chat/stream", "POST", task_run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert mod_chat_write.switched is True

    invalid_owner = resolve_tutorial_scope(
        db,
        _request("/customers", "GET", run.id),
        user_id=users[1].id,
        source_tenant_id=users[1].tenant_id,
    )
    assert invalid_owner.error_code == "tutorial_cookie_invalid"

    run.last_entered_at = datetime.utcnow() - timedelta(hours=13)
    db.commit()
    timed_out = resolve_tutorial_scope(
        db,
        _request("/customers", "GET", run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert timed_out.error_code == "tutorial_cookie_expired"
    run.last_entered_at = datetime.utcnow()
    run.workspace.status = "pending_cleanup"
    db.commit()
    expired = resolve_tutorial_scope(
        db,
        _request("/customers", "GET", run.id),
        user_id=users[0].id,
        source_tenant_id=users[0].tenant_id,
    )
    assert expired.error_code == "tutorial_cookie_expired"


def test_switching_courses_pauses_previous_and_reset_creates_new_generation(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    first = service.start_run(db, users[0], "master-data")
    with tenant_scope(users[0].tenant_id):
        db.add(Customer(customer_name="正式保留客户"))
        db.commit()
    with tenant_scope(first.workspace.tutorial_tenant_id):
        db.add(Customer(customer_name="待清理教学客户"))
        db.commit()
    second = service.start_run(db, users[0], "data-import")
    db.refresh(first)
    assert first.status == "paused"
    assert second.status == "active"
    assert service.leave_run(db, users[0], second.id).status == "paused"
    assert service.enter_run(db, users[0], second.id).status == "active"

    replacement = service.reset_run(db, users[0], second.id)
    db.refresh(second.workspace)
    assert second.workspace.status == "pending_cleanup"
    assert second.workspace.purge_after is not None
    assert replacement.workspace.generation == second.workspace.generation + 1
    assert replacement.workspace.tutorial_tenant_id != second.workspace.tutorial_tenant_id
    old_tenant_id = second.workspace.tutorial_tenant_id
    second.workspace.purge_after = datetime.utcnow()
    db.commit()
    assert service.purge_expired_workspaces(db, now=datetime.utcnow()) == 1
    with tenant_scope(old_tenant_id):
        assert db.query(Customer).count() == 0
    with tenant_scope(users[0].tenant_id):
        assert [row.customer_name for row in db.query(Customer).all()] == ["正式保留客户"]
    assert (
        db.query(TutorialStepEvidence).filter(TutorialStepEvidence.run_id == first.id).count() > 0
    )


def test_prerequisites_are_fail_closed(tutorial_db):
    db, users = tutorial_db
    with pytest.raises(TutorialServiceError) as caught:
        TutorialV2Service().start_run(db, users[0], "sales-to-cash")
    assert caught.value.code == "prerequisite_incomplete"


def test_task_verifier_requires_persisted_execution_evidence(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    run = service.start_run(db, users[0], "task-workspace")
    now = datetime.utcnow().isoformat()
    task = AgentTaskRecord(
        task_id="tutorial-task-1",
        user_id=str(users[0].id),
        tenant_id=str(run.workspace.tutorial_tenant_id),
        title="查询 A 产品当前库存",
        source="chat",
        task_type="readonly_query",
        status="completed",
        attention_state="result_unread",
        active_run_id="tutorial-run-1",
        attempt=1,
        run_count=1,
        metadata_json=json.dumps({"read_only": True}),
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    _run, missing = service.verify_step(
        db,
        users[0],
        run.id,
        "submit-readonly-query",
        cookie_run_id=run.id,
    )
    assert missing.result_code == "task_evidence_not_ready"
    db.add(
        AgentRunRecord(
            run_id="tutorial-run-1",
            user_id=str(users[0].id),
            status="completed",
            intent="products_query",
            message="查询 A 产品当前库存",
            payload_json=json.dumps(
                {
                    "status": "completed",
                    "steps": [{"status": "completed", "tool_id": "products"}],
                    "tool_calls": [{"status": "completed", "tool_id": "products"}],
                    "final_output": {"products": []},
                }
            ),
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    _run, observed = service.verify_step(
        db,
        users[0],
        run.id,
        "submit-readonly-query",
        cookie_run_id=run.id,
    )
    assert observed.status == "passed"
    assert json.loads(observed.counts_json)["observed_execution_count"] == 1

    # Background-dispatched tasks remain valid evidence as a separate execution mode.
    run_two = service.reset_run(db, users[0], run.id)
    service.enter_run(db, users[0], run_two.id)
    task.tenant_id = str(run_two.workspace.tutorial_tenant_id)
    task.active_run_id = "tutorial-run-2"
    db.commit()
    db.add(
        AgentTaskExecutionRecord(
            run_id="tutorial-run-2",
            task_id=task.task_id,
            user_id=str(users[0].id),
            tenant_id=str(run_two.workspace.tutorial_tenant_id),
            state="finished",
            priority=100,
            available_at=now,
            execution_count=1,
            recovery_count=0,
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
    )
    db.commit()
    _run, passed = service.verify_step(
        db,
        users[0],
        run_two.id,
        "submit-readonly-query",
        cookie_run_id=run_two.id,
    )
    assert passed.status == "passed"
    _run, unread = service.verify_step(
        db,
        users[0],
        run_two.id,
        "inspect-task-evidence",
        cookie_run_id=run_two.id,
    )
    assert unread.result_code == "task_evidence_not_ready"
    task.attention_state = ""
    db.commit()
    finished, viewed = service.verify_step(
        db,
        users[0],
        run_two.id,
        "inspect-task-evidence",
        cookie_run_id=run_two.id,
    )
    assert viewed.status == "passed"
    assert finished.status == "completed"


def test_approval_requests_and_records_are_tenant_scoped(tutorial_db):
    db, users = tutorial_db
    flow = ApprovalFlow(flow_key="tutorial-test", flow_name="共享流程", created_by=users[0].id)
    db.add(flow)
    db.flush()
    node = ApprovalFlowNode(
        flow_id=flow.id,
        node_name="审批",
        node_order=1,
        approver_type="user",
    )
    db.add(node)
    db.commit()
    with tenant_scope(users[0].tenant_id):
        tenant_one = ApprovalRequest(
            request_no="APR-TENANT-1",
            flow_id=flow.id,
            business_type="general",
            applicant_id=users[0].id,
            title="租户一审批",
        )
        db.add(tenant_one)
        db.flush()
        db.add(
            ApprovalRecord(
                request_id=tenant_one.id,
                node_id=node.id,
                approver_id=users[0].id,
                action="approve",
                is_passed=True,
            )
        )
        db.commit()
    with tenant_scope(users[2].tenant_id):
        tenant_two = ApprovalRequest(
            request_no="APR-TENANT-2",
            flow_id=flow.id,
            business_type="general",
            applicant_id=users[2].id,
            title="租户二审批",
        )
        db.add(tenant_two)
        db.flush()
        db.add(
            ApprovalRecord(
                request_id=tenant_two.id,
                node_id=node.id,
                approver_id=users[2].id,
                action="approve",
                is_passed=True,
            )
        )
        db.commit()
        assert [row.request_no for row in db.query(ApprovalRequest).all()] == ["APR-TENANT-2"]
        assert [row.request_id for row in db.query(ApprovalRecord).all()] == [tenant_two.id]
    with tenant_scope(users[0].tenant_id):
        assert [row.request_no for row in db.query(ApprovalRequest).all()] == ["APR-TENANT-1"]
        assert [row.request_id for row in db.query(ApprovalRecord).all()] == [tenant_one.id]


def test_data_import_verifiers_require_preview_rows_and_persisted_mixed_results(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    run = service.start_run(db, users[0], "data-import")
    tenant_id = run.workspace.tutorial_tenant_id
    now = datetime.utcnow()
    with tenant_scope(tenant_id):
        upload = EtlUpload(
            id="tutorial-upload-1",
            owner_user_id=users[0].id,
            file_name="xcagi-tutorial-business-import.xlsx",
            suffix=".xlsx",
            size_bytes=256,
            sha256="a" * 64,
            storage_path="/private/tmp/xcagi-tutorial-business-import.xlsx",
        )
        db.add(upload)
        db.flush()
        etl_run = EtlRun(
            id="tutorial-etl-run-1",
            owner_user_id=users[0].id,
            upload_id=upload.id,
            target_type="customer_product",
            status="preview_ready",
            stage="preview_ready",
            progress=50,
            file_sha256=upload.sha256,
            total_rows=2,
            processed_rows=2,
        )
        db.add(etl_run)
        db.flush()
        success_row = EtlRunRow(
            run_id=etl_run.id,
            owner_user_id=users[0].id,
            source_sheet="教学客户产品",
            source_row=2,
            source_json="{}",
            normalized_json="{}",
            provenance_json="{}",
            validation_json="[]",
            suggested_action="create",
            final_action="create",
            after_json=json.dumps({"customer": "教学客户C", "product": "教学产品C"}),
        )
        error_row = EtlRunRow(
            run_id=etl_run.id,
            owner_user_id=users[0].id,
            source_sheet="教学客户产品",
            source_row=3,
            source_json="{}",
            normalized_json="{}",
            provenance_json="{}",
            validation_json=json.dumps(["invalid_price"]),
            suggested_action="skip",
            final_action="skip",
        )
        db.add_all([success_row, error_row])
        db.commit()

    run, preview = service.verify_step(
        db,
        users[0],
        run.id,
        "import-preview",
        cookie_run_id=run.id,
    )
    assert preview.status == "passed"
    assert json.loads(preview.counts_json) == {
        "preview_row_count": 2,
        "preview_run_count": 1,
    }

    with tenant_scope(tenant_id):
        etl_run.status = "completed"
        etl_run.stage = "completed"
        etl_run.progress = 100
        etl_run.executed_rows = 1
        etl_run.error_rows = 1
        etl_run.executed_at = now
        success_row.execution_status = "success"
        success_row.match_ref = "customer:501|product:601"
        error_row.execution_status = "failed"
        error_row.execution_error_code = "invalid_price"
        db.commit()

    finished, completed = service.verify_step(
        db,
        users[0],
        run.id,
        "import-execute",
        cookie_run_id=run.id,
    )
    assert completed.status == "passed"
    assert finished.status == "completed"
    assert json.loads(completed.counts_json) == {
        "completed_run_count": 1,
        "error_row_count": 1,
        "referenced_row_count": 1,
        "successful_row_count": 1,
    }


def test_sales_closed_loop_verifier_records_counts_and_balanced_vouchers(tutorial_db):
    db, users = tutorial_db
    service = TutorialV2Service()
    master = service.start_run(db, users[0], "master-data")
    tenant_id = master.workspace.tutorial_tenant_id
    with tenant_scope(tenant_id):
        customer = Customer(customer_name="客户B")
        product = Product(name="A 产品", price=100, quantity=100, unit="个")
        db.add_all([customer, product])
        db.commit()
    for step in ("create-customer", "create-product"):
        service.verify_step(db, users[0], master.id, step, cookie_run_id=master.id)
    sales = service.start_run(db, users[0], "sales-to-cash")
    with tenant_scope(tenant_id):
        flow = ApprovalFlow(
            flow_key="tutorial-sales",
            flow_name="教学销售审批",
            created_by=users[0].id,
        )
        db.add(flow)
        db.flush()
        approval = ApprovalRequest(
            request_no="TUTORIAL-SALES-APPROVAL-1",
            flow_id=flow.id,
            business_type="workflow_tool",
            applicant_id=users[0].id,
            title="销售到收款教学审批",
            business_data=json.dumps({"sentence": SALES_SENTENCE}, ensure_ascii=False),
        )
        db.add(approval)
        db.commit()

    sales, waiting = service.verify_step(
        db,
        users[0],
        sales.id,
        "submit-sales-sentence",
        cookie_run_id=sales.id,
    )
    assert waiting.status == "passed"
    assert json.loads(waiting.counts_json) == {
        "allocation_count": 0,
        "inventory": 100,
        "journal_entry_count": 0,
        "pending_approval_count": 1,
        "sales_order_count": 0,
        "sales_order_item_count": 0,
    }

    with tenant_scope(tenant_id):
        approval.status = "approved"
        order = SalesOrder(
            order_no="TUTORIAL-ORDER-1",
            customer_id=customer.id,
            customer_name="客户B",
            state="confirmed",
            status="paid",
            invoice_status="invoiced",
            payment_state="paid",
            total_amount=1000,
            paid_amount=1000,
        )
        db.add(order)
        db.flush()
        db.add(
            SalesOrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name="A 产品",
                quantity=10,
                ordered_quantity=10,
                delivered_quantity=10,
                invoiced_quantity=10,
                unit_price=100,
                amount=1000,
                status="paid",
            )
        )
        product.quantity = 90
        invoice = JournalEntry(
            entry_no="TUTORIAL-INV-1",
            status="posted",
            reference_type="sale",
            reference_id=order.id,
            debit_total=1000,
            credit_total=1000,
        )
        payment = JournalEntry(
            entry_no="TUTORIAL-PAY-1",
            status="posted",
            reference_type="payment",
            reference_id=order.id,
            debit_total=1000,
            credit_total=1000,
        )
        db.add_all([invoice, payment])
        db.flush()
        db.add(
            ReceivableAllocation(
                sales_order_id=order.id,
                journal_entry_id=payment.id,
                amount=1000,
                allocated_amount=1000,
                status="paid",
            )
        )
        db.commit()
    ok, refs, counts = service._closed_loop_result(db, sales)
    assert ok is True
    assert counts == {
        "sales_order_count": 1,
        "sales_order_item_count": 1,
        "inventory": 90,
        "allocation_count": 1,
        "journal_entry_count": 2,
        "invoice_voucher_count": 1,
        "payment_voucher_count": 1,
        "balanced_journal_entry_count": 2,
    }
    assert {item["type"] for item in refs} >= {
        "sales_order",
        "sales_order_item",
        "receivable_allocation",
        "journal_entry",
    }
    finished, closed = service.verify_step(
        db,
        users[0],
        sales.id,
        "approve-sales-request",
        cookie_run_id=sales.id,
    )
    assert closed.status == "passed"
    assert finished.status == "completed"


def test_public_api_uses_named_dtos_and_httponly_run_cookie(tutorial_db):
    db, users = tutorial_db
    from app.db.session import get_db_dependency
    from app.fastapi_routes.tutorial_v2 import router
    from app.infrastructure.auth.dependencies import get_logged_in_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_logged_in_user] = lambda: users[0]

    def _db_override():
        yield db

    app.dependency_overrides[get_db_dependency] = _db_override
    client = TestClient(app)
    course_response = client.get("/api/tutorial/v2/courses")
    assert course_response.status_code == 200
    courses = course_response.json()["data"]
    assert [item["id"] for item in courses] == [
        "task-workspace",
        "master-data",
        "sales-to-cash",
        "data-import",
        "evidence-trace",
    ]
    assert set(courses[0]["steps"][0]) >= {
        "goal",
        "instruction",
        "success_criteria",
        "why",
        "hint",
        "evidence",
    }

    started = client.post("/api/tutorial/v2/runs", json={"course_id": "master-data"})
    run_id = started.json()["data"]["id"]
    entered = client.post(f"/api/tutorial/v2/runs/{run_id}/enter")
    assert entered.status_code == 200
    cookie = entered.headers["set-cookie"]
    assert "xcagi_tutorial_run=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    workbook = client.get("/api/tutorial/v2/assets/business-import.xlsx")
    assert workbook.status_code == 200
    assert workbook.content.startswith(b"PK")
    assert workbook.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    with pytest.raises(TutorialServiceError) as forbidden_report:
        TutorialV2Service().reports(db, users[1])
    assert forbidden_report.value.code == "tutorial_report_forbidden"
    assert TutorialV2Service().reports(db, users[0])
