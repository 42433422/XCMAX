"""E01–E30 closed-loop acceptance against the product executor and SQLite.

Isolated file database and export directory. The 2026-11-06 evidence file is
not an input and is not rewritten. This run writes a new retest record and
judges each item from this execution only.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator, _runtime_dependencies
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.employee_runtime.executor import execute_employee_task_local
from app.db.models.purchase_unit import PurchaseUnit
from app.domain.task_lifecycle.adapters import canonicalize
from tests.fixtures.employee_closed_loop import (
    _HISTORY,
    _ITEMS,
    Acceptance,
    ClosedLoopRun,
    _customer_row,
    _grade,
    _note_runtime,
    _now,
    _orders,
    _retest_evidence_path,
    _seed_order,
    _seed_sales_customer,
    _sha256,
    _units,
    judge_async_export,
    judge_cancel,
    judge_restart,
    judge_tool_timeout,
    resolve_retry_task_id,
)
from tests.fixtures.employee_customer_authorization import (
    verify_customer_authorization_and_recovery,
)


@pytest.fixture(scope="module")
def closed_loop_run():
    run = ClosedLoopRun()
    try:
        _execute_closed_loop(run.open_resources())
        yield run
    finally:
        run.close()


@pytest.fixture()
def loop(closed_loop_run: ClosedLoopRun) -> Acceptance:
    return closed_loop_run.require()


def _execute_closed_loop(loop: Acceptance) -> None:
    engine = loop.engine
    with Session(engine) as db:
        db.add(
            PurchaseUnit(
                unit_name="闭环指定客户甲",
                contact_person="张三",
                contact_phone="13800000001",
                address="上海市浦东新区",
                tenant_id=11,
                is_active=True,
            )
        )
        db.commit()
        customer_id = int(
            db.execute(
                select(PurchaseUnit.id).execution_options(skip_tenant_filter=True)
            ).scalar_one()
        )
    _seed_sales_customer(engine, customer_id, "闭环指定客户甲", "上海市浦东新区", 11)
    today = datetime.now().replace(microsecond=0)
    old = today - timedelta(days=40)
    first_order = _seed_order(
        engine,
        order_no="SO-E02-OLD",
        customer_id=customer_id,
        customer_name="闭环指定客户甲",
        status="confirmed",
        tenant_id=11,
        created_at=old,
    )
    low_id = _seed_order(
        engine,
        order_no="SO-E02-A",
        customer_id=customer_id,
        customer_name="闭环指定客户甲",
        status="confirmed",
        tenant_id=11,
        created_at=today,
    )
    high_id = _seed_order(
        engine,
        order_no="SO-E02-B",
        customer_id=customer_id,
        customer_name="闭环指定客户甲",
        status="confirmed",
        tenant_id=11,
        created_at=today,
    )
    _seed_order(
        engine,
        order_no="SO-E02-OTHER",
        customer_id=customer_id,
        customer_name="闭环指定客户甲",
        status="quote",
        tenant_id=11,
        created_at=today,
    )

    found = loop.call(
        "customers",
        "query",
        {"keyword": "闭环指定客户甲"},
        loop.context("e01", employee_id="employee-a"),
    )
    rows = [row for row in _units(engine) if row["customer_name"] == "闭环指定客户甲"]
    data = found.get("data") or []
    match = data[0] if data else {}
    e01_ok = (
        found.get("success") is True
        and match.get("id") == customer_id
        and match.get("contact_phone") == rows[0]["contact_phone"]
        and len(data) == len(rows)
    )
    loop.settle(
        "E01",
        "PASS" if e01_ok else "FAIL",
        f"task e01 customers.query id={match.get('id')} db={rows}",
        task_id="e01",
    )

    filtered = loop.call(
        "sales",
        "query",
        {
            "region": "浦东",
            "status": "confirmed",
            "start_date": today.date().isoformat(),
            "end_date": today.date().isoformat(),
            "page": 1,
            "per_page": 1,
        },
        loop.context("e02"),
    )
    page = filtered.get("data") or []
    e02_ok = (
        filtered.get("success") is True
        and filtered.get("page") == 1
        and filtered.get("per_page") == 1
        and len(page) == 1
        and page[0]["id"] == high_id
        and all(row["id"] != first_order for row in page)
        and page[0]["id"] != low_id
    )
    loop.settle(
        "E02",
        "PASS" if e02_ok else "FAIL",
        f"task e02 page={filtered.get('page')} first_id={page[0]['id'] if page else None} expected={high_id}",
        task_id="e02",
    )

    from app.application.agent_orchestrator.param_references import resolve_references

    problems: list[str] = []
    linked = resolve_references(
        {"customer_id": "{{find_customer.data.id}}"},
        {"find_customer": found},
        problems,
    )
    orders = loop.call(
        "sales",
        "query",
        {"customer_id": linked.get("customer_id"), "page": 1, "per_page": 20},
        loop.context("e03", parent_task_id="e01"),
    )
    order_ids = {row["id"] for row in orders.get("data") or []}
    db_ids = {row["id"] for row in _orders(engine) if row["customer_id"] == customer_id}
    e03_ok = not problems and linked.get("customer_id") == customer_id and order_ids == db_ids
    loop.settle(
        "E03",
        "PASS" if e03_ok else "FAIL",
        f"task e03 linked={linked.get('customer_id')} problems={problems} tool={sorted(order_ids)} db={sorted(db_ids)}",
        task_id="e03",
    )

    exported = loop.call(
        "customers",
        "export",
        {"keyword": "闭环指定客户甲"},
        loop.context("e04"),
    )
    export_path = Path(str(exported.get("file_path") or ""))
    e04_ok = False
    digest = ""
    if exported.get("success") is True and export_path.is_file():
        book = load_workbook(export_path)
        sheet = book.active
        header = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        body = list(sheet.iter_rows(min_row=2, values_only=True))
        digest = _sha256(export_path)
        e04_ok = header == ["ID", "客户名称", "联系人", "电话", "地址"] and len(body) == len(
            [row for row in _units(engine) if "闭环指定客户甲" in row["customer_name"]]
        )
        book.close()
    loop.settle(
        "E04",
        "PASS" if e04_ok else "FAIL",
        f"task e04 file={export_path.name if export_path.is_file() else exported.get('message')} sha256={digest}",
        task_id="e04",
        artifact_hash=digest,
    )
    from tests.fixtures.customer_export_task import run_customer_export_task

    export_proof = run_customer_export_task(
        loop.tmp,
        context=loop.context("e05"),
        expected_ids={
            row["id"] for row in _units(engine) if "闭环指定客户甲" in row["customer_name"]
        },
    )
    e05_verdict = judge_async_export(
        export_proof["entries"],
        phases=export_proof["phases"],
        file_ready=export_proof["file_ready"],
    )
    loop.settle(
        "E05",
        e05_verdict,
        f"task e05 run={export_proof['run_id']} phases={sorted(export_proof['phases'])} file_ready={export_proof['file_ready']} error={export_proof['error']}",
        task_id="e05",
        run_id=export_proof["run_id"],
        artifact_hash=_sha256(Path(export_proof["file_path"]))
        if export_proof["file_ready"]
        else "",
    )

    created = loop.call(
        "customers",
        "create",
        {
            "unit_name": "闭环新建客户乙",
            "contact_person": "李四",
            "contact_phone": "13800000006",
            "contact_address": "杭州市西湖区",
        },
        loop.context("e06"),
    )
    created_row = next(
        (row for row in _units(engine) if row["customer_name"] == "闭环新建客户乙"), None
    )
    e06_ok = (
        created.get("success") is True
        and created_row is not None
        and created_row["contact_phone"] == "13800000006"
        and created_row["tenant_id"] == 11
    )
    loop.settle(
        "E06",
        "PASS" if e06_ok else "FAIL",
        f"task e06 tool={created.get('success')} db={created_row}",
        task_id="e06",
    )

    target_id = int(created_row["id"]) if created_row else 0
    before = next(row for row in _units(engine) if row["id"] == target_id) if target_id else {}
    updated = loop.call(
        "customers",
        "update",
        {"id": target_id, "contact_phone": "13800000007"},
        loop.context("e07"),
    )
    after = next((row for row in _units(engine) if row["id"] == target_id), {})
    e07_ok = (
        updated.get("success") is True
        and before
        and after.get("contact_phone") == "13800000007"
        and after.get("customer_name") == before.get("customer_name")
        and after.get("contact_person") == before.get("contact_person")
        and after.get("contact_address") == before.get("contact_address")
    )
    loop.settle(
        "E07",
        "PASS" if e07_ok else "FAIL",
        f"task e07 before={before.get('contact_phone')} after={after.get('contact_phone')} name_unchanged={after.get('customer_name') == before.get('customer_name')}",
        task_id="e07",
    )

    before_count = len(_units(engine))
    missing = loop.call("customers", "create", {}, loop.context("e08-missing"))
    mid_count = len(_units(engine))
    supplied = loop.call(
        "customers",
        "create",
        {"unit_name": "闭环补参客户丙", "contact_phone": "13800000008"},
        loop.context("e08"),
    )
    supplied_row = next(
        (row for row in _units(engine) if row["customer_name"] == "闭环补参客户丙"), None
    )
    e08_ok = (
        missing.get("success") is not True
        and missing.get("error_code") == "schema_validation_failed"
        and mid_count == before_count
        and supplied.get("success") is True
        and supplied_row is not None
    )
    loop.settle(
        "E08",
        "PASS" if e08_ok else "FAIL",
        f"task e08 missing={missing.get('error_code')} count {before_count}->{mid_count} created={supplied_row is not None}",
        task_id="e08",
    )

    paused_run = AgentRun(
        user_id="11",
        message="create customer needs approval",
        status="queued",
        steps=[
            AgentStep(
                node_id="create-customer",
                tool_id="customers",
                action="create",
                params={"unit_name": "闭环待审批客户丁"},
                risk="medium",
                idempotent=False,
            )
        ],
    )
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    paused_run.metadata["plan"] = plan_to_dict(
        PlanGraph(
            plan_id=paused_run.run_id,
            intent="customer_create",
            nodes=[
                WorkflowNode(
                    node_id="create-customer",
                    tool_id="customers",
                    action="create",
                    params={"unit_name": "闭环待审批客户丁"},
                    risk="medium",
                    idempotent=False,
                )
            ],
        )
    )
    paused_run.metadata["runtime_context"] = loop.context(paused_run.run_id)
    before_approval = len(_units(engine))
    gate = AgentOrchestrator(
        repository=InMemoryAgentRunRepository(), dependencies=_runtime_dependencies()
    )
    gate._execute_ready_steps(paused_run, runtime_context=paused_run.metadata["runtime_context"])
    canonical = canonicalize("agent", paused_run.status)
    e09_ok = (
        canonical == "waiting_approval"
        and len(_units(engine)) == before_approval
        and paused_run.steps[0].status == "waiting_user"
    )
    loop.settle(
        "E09",
        "PASS" if e09_ok else "FAIL",
        f"task {paused_run.run_id} status={paused_run.status} canonical={canonical} rows {before_approval}->{len(_units(engine))}",
        task_id=paused_run.run_id,
    )

    approved_before = len(_units(engine))
    gate._execute_ready_steps(
        paused_run,
        runtime_context=paused_run.metadata["runtime_context"],
        approved_step_id=paused_run.steps[0].step_id,
    )
    approved_row = next(
        (row for row in _units(engine) if row["customer_name"] == "闭环待审批客户丁"), None
    )
    e10_ok = (
        paused_run.run_id
        and approved_row is not None
        and len(_units(engine)) == approved_before + 1
        and paused_run.steps[0].params.get("unit_name") == "闭环待审批客户丁"
    )
    loop.chain.append(
        {
            "at": _now(),
            "task_id": paused_run.run_id,
            "parent_task_id": "",
            "child_task_id": "",
            "tool_call_id": paused_run.steps[0].step_id,
            "employee_id": "employee-a",
            "tool_id": "customers",
            "tool_version": "2",
            "tenant_id": "11",
            "idempotency_key": "",
            "approval_id": paused_run.steps[0].step_id,
            "request": paused_run.steps[0].params,
            "response": paused_run.steps[0].output,
            "execution_status": paused_run.steps[0].status,
            "database_before": {"count": approved_before},
            "database_after": {"count": len(_units(engine))},
            "artifact_hash": "",
            "audit_log": None,
        }
    )
    loop.settle(
        "E10",
        "PASS" if e10_ok else "FAIL",
        f"task {paused_run.run_id} step={paused_run.steps[0].status} db={approved_row}",
        task_id=paused_run.run_id,
    )

    from app.application.agent_orchestrator.task_execution_repository import (
        InMemoryTaskExecutionRepository,
    )
    from app.domain.task_lifecycle.control import TaskLifecycleError

    queue = InMemoryTaskExecutionRepository(approval_timeout_seconds=1)
    rejected = AgentRun(user_id="11", message="reject me", status="queued")
    rejected.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(rejected)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(rejected.run_id, "boss")
    queue.resolve_approval(rejected.run_id, "reject", "boss")
    bypass_result = loop.call(
        "customers",
        "create",
        {"unit_name": "闭环驳回不应写入"},
        loop.context(rejected.run_id, approval_id="rejected"),
    )
    bypass = any(row["customer_name"] == "闭环驳回不应写入" for row in _units(engine))
    e11_ok = (
        queue.get(rejected.run_id).state == "rejected"
        and not bypass
        and bypass_result.get("success") is not True
    )
    loop.settle(
        "E11",
        "PASS" if e11_ok else "FAIL",
        f"task {rejected.run_id} state={queue.get(rejected.run_id).state} executor_bypassed_approval={bypass}",
        task_id=rejected.run_id,
    )

    expired = AgentRun(user_id="11", message="expire", status="queued")
    expired.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(expired)
    assert queue.claim("worker", lease_seconds=30) is not None
    paused = queue.request_approval(expired.run_id, "boss")
    moment = datetime.fromisoformat(paused.updated_at.replace("Z", "+00:00"))
    assert (
        queue.claim("worker", lease_seconds=5, now=(moment + timedelta(seconds=2)).isoformat())
        is None
    )
    assert queue.get(expired.run_id).state == "rejected"
    resumed = queue.resolve_approval(expired.run_id, "approve", "boss")
    e12_ok = resumed is None and queue.get(expired.run_id).last_error_code == "approval_timeout"
    loop.settle(
        "E12",
        "PASS" if e12_ok else "FAIL",
        f"task {expired.run_id} state={queue.get(expired.run_id).state} code={queue.get(expired.run_id).last_error_code} resumed={resumed}",
        task_id=expired.run_id,
    )

    stranger = AgentRun(user_id="11", message="stranger", status="queued")
    stranger.metadata["runtime_context"] = {"tenant_id": "11"}
    queue.enqueue(stranger)
    assert queue.claim("worker", lease_seconds=30) is not None
    queue.request_approval(stranger.run_id, "boss")
    denied = False
    try:
        queue.resolve_approval(stranger.run_id, "approve", "intruder")
    except TaskLifecycleError:
        denied = True
    e13_ok = denied and queue.get(stranger.run_id).state == "waiting_approval"
    loop.settle(
        "E13",
        "PASS" if e13_ok else "FAIL",
        f"task {stranger.run_id} server_rejected={denied} state={queue.get(stranger.run_id).state}",
        task_id=stranger.run_id,
    )

    from app.application.agent_orchestrator.approval_grant import (
        ApprovalGrantError,
        issue_approval_grant,
    )
    from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.db.models.agent_approval import AgentApprovalConsumption

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    AgentApprovalConsumption.__table__.create(engine, checkfirst=True)
    runs = SQLAlchemyAgentRunRepository(session_factory=factory)
    sql_queue = SQLAlchemyTaskExecutionRepository(session_factory=factory)
    durable = AgentRun(
        user_id="11",
        message="approve once",
        status="waiting_user",
        steps=[
            AgentStep(
                node_id="once",
                tool_id="customers",
                action="create",
                params={"unit_name": "闭环幂等审批客户戊"},
                status="waiting_user",
            )
        ],
    )
    durable.metadata["runtime_context"] = loop.context(durable.run_id)
    runs.save(durable)
    token = issue_approval_grant(durable, principal_id="boss")["grant"]
    approve_and_enqueue(
        runs,
        sql_queue,
        run_id=durable.run_id,
        token=token,
        principal_id="boss",
        runtime_context=durable.metadata["runtime_context"],
    )
    duplicate_blocked = False
    try:
        approve_and_enqueue(
            runs,
            sql_queue,
            run_id=durable.run_id,
            token=token,
            principal_id="boss",
            runtime_context=durable.metadata["runtime_context"],
        )
    except ApprovalGrantError:
        duplicate_blocked = True
    once = loop.call(
        "customers",
        "create",
        {"unit_name": "闭环幂等审批客户戊"},
        loop.context(durable.run_id, approval_id=durable.steps[0].step_id),
    )
    pent_rows = [row for row in _units(engine) if row["customer_name"] == "闭环幂等审批客户戊"]
    with Session(engine) as db:
        consumed = len(
            db.execute(select(AgentApprovalConsumption).execution_options(skip_tenant_filter=True))
            .scalars()
            .all()
        )
    e14_ok = (
        duplicate_blocked and once.get("success") is True and len(pent_rows) == 1 and consumed == 1
    )
    loop.settle(
        "E14",
        "PASS" if e14_ok else "FAIL",
        f"task {durable.run_id} duplicate_blocked={duplicate_blocked} rows={len(pent_rows)} approvals={consumed}",
        task_id=durable.run_id,
    )

    verify_customer_authorization_and_recovery(loop)

    workspace = loop.tmp / "handoff"
    workspace.mkdir()
    for employee_id in ("employee-a", "employee-b"):
        folder = workspace / "employees"
        folder.mkdir(exist_ok=True)
        (folder / f"{employee_id}.json").write_text(
            json.dumps(
                {"employee_id": employee_id, "tenant_id": "11", "available": True},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    started = execute_employee_task_local(
        "employee-a",
        "查询本月客户订单，分析销售，生成 Excel，并给出业务摘要",
        {
            "continuity_action": "start",
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            "goal": "查询本月客户订单，分析销售，生成 Excel，并给出业务摘要",
            "steps": [
                {"tool": "list_customers", "params": {"filters": {"keyword": "闭环指定客户甲"}}}
            ],
        },
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=loop.context("e25-start"),
    )
    parent_id = str(started.get("task_id") or "")
    _note_runtime(loop, started, task_id=parent_id, action="start")
    handed = execute_employee_task_local(
        "employee-a",
        "交给员工乙",
        {
            "continuity_action": "handoff",
            "workspace_root": str(workspace),
            "tenant_id": "11",
            "user_id": "11",
            "task_id": parent_id,
            "target_employee": "employee-b",
            "permissions": ["sales.query", "customers.query"],
            "delegated_tool": "customers",
            "delegated_action": "query",
            "delegated_params": {"keyword": "闭环指定客户甲"},
            "effect": {"goal": started.get("task", {}).get("goal")},
        },
        user_id=11,
        workspace_root=str(workspace),
        runtime_context=loop.context(parent_id),
    )
    handoff = handed.get("handoff") or {}
    _note_runtime(loop, handed, task_id=parent_id, action="handoff")
    e25_ok = (
        handoff.get("status") == "succeeded"
        and handoff.get("goal")
        and handoff.get("target_employee") == "employee-b"
    )
    loop.settle(
        "E25",
        "PASS" if e25_ok else "FAIL",
        f"parent {parent_id} handoff_status={handoff.get('status')} error={handoff.get('error_code') or handed.get('error_code')}",
        task_id=parent_id,
    )
    from tests.fixtures.employee_business_chain import run_business_chain

    for item, fail_last in (("E26", False), ("E27", True)):
        proof = run_business_chain(loop.tmp / item.lower(), fail_last_hop=fail_last)
        task_id = proof["task_id"]
        if fail_last:
            _note_runtime(loop, proof["first_result"], task_id=task_id, action="chain_failed_hop")
        _note_runtime(
            loop, proof["result"], task_id=task_id, action="retry_handoff" if fail_last else "chain"
        )
        for receipt in proof["receipts"]:
            result = receipt["result"]
            output = result["final_output"]["node_outputs"]["handoff-work"]
            calls = result["final_output"].get("tool_calls") or []
            loop.chain.append(
                {
                    "at": _now(),
                    "task_id": task_id,
                    "parent_task_id": task_id,
                    "child_task_id": receipt["child_task_id"],
                    "tool_call_id": str(calls[0].get("call_id") or "") if calls else "",
                    "employee_id": receipt["employee_id"],
                    "tool_id": result["tool_id"],
                    "tool_version": "2",
                    "action": result["action"],
                    "tenant_id": receipt["tenant_id"],
                    "idempotency_key": "",
                    "approval_id": "",
                    "request": result["params"],
                    "response": output,
                    "execution_status": receipt["execution_status"],
                    "database_before": {},
                    "database_after": {},
                    "artifact_hash": proof["artifacts"][0]["sha256"]
                    if result["action"] == "export" and proof["artifacts"]
                    else "",
                    "audit_log": output.get("audit"),
                }
            )
        passed = proof["complete"] and (not fail_last or proof["recovered"])
        loop.settle(
            item,
            "PASS" if passed else "FAIL",
            f"task {task_id} workers={len(proof['receipts'])} xlsx={len(proof['artifacts'])} recovered={proof['recovered']} error={proof['error'] or 'none'}",
            task_id=task_id,
            child_task_ids=[row["child_task_id"] for row in proof["receipts"]],
            artifacts=proof["artifacts"],
            sales_summary=proof["summary"],
        )

    from tests.fixtures.employee_execution_faults import (
        observe_scheduler_restart,
        observe_tool_timeout,
    )

    timeout = observe_tool_timeout(loop.tmp, loop.context("e28"))
    e28_verdict = judge_tool_timeout(
        **{
            key: timeout[key]
            for key in ("process_started", "process_exited", "resources_released", "task_state")
        }
    )
    if timeout["output"].get("retryable") is not False:
        e28_verdict = "FAIL"
    loop.chain.append(
        {
            "at": _now(),
            "task_id": timeout["task_id"],
            "parent_task_id": "",
            "child_task_id": "",
            "tool_call_id": timeout["tool_call_id"],
            "employee_id": "employee-a",
            "tool_id": "customers",
            "tool_version": "2",
            "action": "query",
            "tenant_id": "11",
            "idempotency_key": "",
            "approval_id": "",
            "request": {"timeout_seconds": 8},
            "response": timeout,
            "execution_status": timeout["task_state"],
            "database_before": {},
            "database_after": {},
            "artifact_hash": "",
            "audit_log": None,
        }
    )
    loop.settle(
        "E28",
        e28_verdict,
        f"task {timeout['task_id']} started={timeout['process_started']} "
        f"exited={timeout['process_exited']} resources_released={timeout['resources_released']} "
        f"product_status={timeout['task_state']} pids={timeout['pids']}",
        task_id=timeout["task_id"],
    )

    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.customer_creation_receipt import CUSTOMER_CREATE_RECEIPTS
    from app.domain.task_lifecycle.control import SessionBook

    cancel_queue = SQLAlchemyTaskExecutionRepository(
        session_factory=sessionmaker(bind=engine, expire_on_commit=False)
    )
    cancelled_states = []
    for label in ("queued", "running", "waiting_approval"):
        run = AgentRun(user_id="11", message=label, status="queued")
        run.metadata["runtime_context"] = {"tenant_id": "11"}
        run.metadata["task_context"] = {"task_id": run.run_id}
        cancel_queue.enqueue(run)
        if label != "queued":
            assert cancel_queue.claim("worker", lease_seconds=30, run_id=run.run_id) is not None
        if label == "waiting_approval":
            cancel_queue.request_approval(run.run_id, "boss")
        moved = cancel_queue.transition(run.run_id, "cancelled")
        cancelled_states.append((label, None if moved is None else moved.state))
        assert cancel_queue.claim("after-cancel", lease_seconds=30, run_id=run.run_id) is None

    committed_run = AgentRun(user_id="11", message="已提交客户后取消剩余步骤", status="queued")
    cancelled_id = committed_run.run_id
    committed_context = loop.context(
        cancelled_id, run_id=cancelled_id, idempotency_key=f"e29:{cancelled_id}"
    )
    committed_run.metadata.update(
        runtime_context=committed_context, task_context={"task_id": cancelled_id}
    )
    cancel_queue.enqueue(committed_run)
    assert cancel_queue.claim("worker", lease_seconds=30, run_id=cancelled_id) is not None
    committed_name = "闭环已提交不可当取消"
    committed_params = {"unit_name": committed_name, "contact_phone": "13800000029"}
    committed = loop.call("customers", "create", committed_params, committed_context)
    assert committed.get("success") is True
    assert cancel_queue.transition(cancelled_id, "cancelled") is not None
    scope = permissions.idempotency_scope_key(
        committed_context, "customers", "create", committed_params
    )
    with Session(engine) as db:
        receipt_customer_id = (
            SessionBook(db).get(CUSTOMER_CREATE_RECEIPTS, "11", scope).get("customer_id")
        )
    final = cancel_queue.get(cancelled_id)
    task_state = "" if final is None else str(final.state)
    db_row = _customer_row(engine, committed_name)
    e29_verdict = judge_cancel(
        task_id=cancelled_id,
        task_state=task_state,
        db_row=db_row,
        receipt_customer_id=receipt_customer_id,
    )
    if (
        any(state != "cancelled" for _, state in cancelled_states)
        or committed.get("id") != receipt_customer_id
    ):
        e29_verdict = "FAIL"
    loop.settle(
        "E29",
        e29_verdict,
        (
            f"task {cancelled_id} state={task_state} "
            f"db_id={None if db_row is None else db_row.get('id')} "
            f"receipt_customer_id={receipt_customer_id} transitions={cancelled_states}"
        ),
        task_id=cancelled_id,
    )

    restart = observe_scheduler_restart(engine, loop.tmp, loop.context("e30"))
    e30_verdict = judge_restart(
        **{
            key: restart[key]
            for key in ("repository_kind", "restored_state", "tool_status", "replayed")
        }
    )
    loop.chain.append(
        {
            "at": _now(),
            "task_id": restart["task_id"],
            "run_id": restart["run_id"],
            "parent_task_id": "",
            "child_task_id": "",
            "tool_call_id": restart["tool_call_id"],
            "employee_id": "employee-a",
            "tool_id": "customers",
            "tool_version": "2",
            "action": "create",
            "tenant_id": "11",
            "request": {"fault": "scheduler_after_commit"},
            "response": restart,
            "execution_status": restart["recovery_state"],
            "database_after": {"customer_id": restart["customer_id"]},
        }
    )
    loop.settle(
        "E30",
        e30_verdict,
        (
            f"task {restart['task_id']} sql_state={restart['restored_state']} "
            f"tool_status={restart['tool_status']} replayed={restart['replayed']} "
            f"recovery={restart['recovery_error']}"
        ),
        task_id=restart["task_id"],
    )

    grade = _grade(loop.items)
    payload = {
        "recorded_at": _now(),
        "timezone": "Asia/Shanghai",
        "grade": grade["grade"],
        "special_acceptance": grade["special_acceptance"],
        "passed": grade["passed"],
        "chain_count": len(loop.chain),
        "items": [loop.items[key] for key in _ITEMS],
        "chain": loop.chain,
        "note": "live retest; does not replace the 2026-11-06 evidence file",
        "history": str(_HISTORY),
    }
    path = _retest_evidence_path()
    if path.resolve() == _HISTORY.resolve():
        raise RuntimeError("retest path must not be the 2026-11-06 evidence file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    loop.evidence_path = path


def test_closed_loop_record_is_this_run(loop: Acceptance) -> None:
    assert loop.evidence_path is not None
    assert loop.evidence_path.is_file()
    assert loop.evidence_path.resolve() != _HISTORY.resolve()
    written = json.loads(loop.evidence_path.read_text(encoding="utf-8"))
    assert list(loop.items) == _ITEMS
    assert [item["id"] for item in written["items"]] == _ITEMS
    assert "sticky_failure" not in json.dumps(written["items"])
    for entry in loop.chain:
        assert not str(entry.get("task_id") or "").startswith("chain-")
    for item in written["items"]:
        assert item["verdict"] in {"PASS", "FAIL", "NOT-IMPLEMENTED"}
        assert item["summary"]


@pytest.mark.parametrize("item_id", _ITEMS)
def test_closed_loop_item_live_pass(loop: Acceptance, item_id: str) -> None:
    item = loop.items[item_id]
    assert item["verdict"] == "PASS", item["summary"]


def test_sync_export_is_not_async_completed() -> None:
    entries = [{"name": "customers.export", "async": False, "detail": "sync file write"}]
    verdict = judge_async_export(
        entries, phases={"queued", "running", "completed"}, file_ready=True
    )
    assert verdict == "NOT-IMPLEMENTED"
    ready = judge_async_export(
        [{"name": "customers.export_job", "async": True}],
        phases={"queued", "running", "completed"},
        file_ready=True,
    )
    assert ready == "PASS"
    assert (
        judge_async_export(
            [{"name": "customers.export_job", "async": True}],
            phases={"completed"},
            file_ready=True,
        )
        == "FAIL"
    )


def test_e28_timeout_before_start_is_not_success() -> None:
    early = judge_tool_timeout(
        process_started=False,
        process_exited=False,
        resources_released=False,
        task_state="timeout",
    )
    assert early == "FAIL"
    still_running = judge_tool_timeout(
        process_started=True,
        process_exited=False,
        resources_released=False,
        task_state="timeout",
    )
    assert still_running == "FAIL"
    unknown = judge_tool_timeout(
        process_started=True,
        process_exited=True,
        resources_released=True,
        task_state="tool_timeout_unknown",
    )
    assert unknown == "FAIL"
    assert (
        judge_tool_timeout(
            process_started=True,
            process_exited=True,
            resources_released=True,
            task_state="timed_out",
        )
        == "PASS"
    )


def test_e29_json_name_search_is_not_verification() -> None:
    name = "闭环已提交不可当取消"
    blob = json.dumps(
        {"cancelled_states": [["queued", "cancelled"]], "name": name}, ensure_ascii=False
    )
    assert name in blob
    row = {"id": 7, "customer_name": name}
    assert (
        judge_cancel(task_id="run-1", task_state="cancelled", db_row=row, receipt_customer_id=blob)
        == "FAIL"
    )
    assert (
        judge_cancel(task_id="run-1", task_state="cancelled", db_row=row, receipt_customer_id=name)
        == "FAIL"
    )
    assert (
        judge_cancel(task_id="run-1", task_state="cancelled", db_row=row, receipt_customer_id=None)
        == "FAIL"
    )
    assert (
        judge_cancel(task_id="", task_state="cancelled", db_row=row, receipt_customer_id=7)
        == "FAIL"
    )
    assert (
        judge_cancel(task_id="run-1", task_state="cancelled", db_row=row, receipt_customer_id=7)
        == "PASS"
    )


def test_e30_memory_repository_is_not_restore() -> None:
    assert (
        judge_restart(
            repository_kind="memory",
            restored_state="running",
            tool_status="recovering",
            replayed=False,
        )
        == "FAIL"
    )
    assert (
        judge_restart(repository_kind="sql", restored_state=None, tool_status=None, replayed=False)
        == "FAIL"
    )
    assert (
        judge_restart(
            repository_kind="sql",
            restored_state="running",
            tool_status="recovering",
            replayed=True,
        )
        == "FAIL"
    )
    assert (
        judge_restart(
            repository_kind="sql",
            restored_state="running",
            tool_status="recovering",
            replayed=False,
        )
        == "PASS"
    )


def test_retry_task_id_comes_from_idempotency_scope() -> None:
    assert (
        resolve_retry_task_id(invoked="e19", scope_key="11:e19:customers:create:e19-same-key")
        == "e19"
    )
    assert (
        resolve_retry_task_id(invoked="e19", scope_key="11:e20:customers:create:e19-same-key")
        == "e20"
    )


def test_live_run_rejects_use_after_teardown() -> None:
    run = ClosedLoopRun()
    book = run.open_resources()
    assert book.tmp.is_dir()
    assert run.require() is book
    held = book.tmp
    run.close()
    with pytest.raises(RuntimeError, match="after fixture teardown"):
        run.require()
    assert not held.exists()
