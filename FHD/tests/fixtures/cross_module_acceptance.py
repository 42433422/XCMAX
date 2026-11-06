"""Exercise the B47–B56 acceptance matrix against real modules and isolated data."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_harness import BUSINESS_HARNESS_PROTOCOL
from app.application.agent_orchestrator.cross_module_chain import (
    _audit,
    _run_employee,
    _sha256,
    identify_workbook,
    import_products,
    slice_and_clean,
    verify_against_data,
    write_result_workbook,
)
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, utc_now_iso
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_models import task_from_run
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.elt.targets.products import ProductAdapter
from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.workflow_types import Branch, PlanGraph, WorkflowNode
from app.db.models.product import Product
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.operational_errors import RECOVERABLE_ERRORS
from tests.fixtures.cross_module_business import (
    _build_source_workbook,
    _delivery_row,
    _product_count,
    _save_delivery,
    interpret_business_intent,
    update_product_price,
)


def run_cross_module_acceptance(
    *,
    db: Session,
    workspace: Path,
    user_id: str = "7",
    tenant_id: str = "1",
    session_id: str = "session-b47",
) -> dict[str, Any]:
    """Run S01–S04 and the B47–B56 probes against the supplied database and workspace."""
    trace_id = uuid.uuid4().hex
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "upload-shipment.xlsx"
    _build_source_workbook(source)
    original_hash = _sha256(source)
    original_bytes = source.read_bytes()
    checks: dict[str, dict[str, Any]] = {}
    evidence: dict[str, Any] = {"trace_id": trace_id}

    def mark(code: str, ok: bool, detail: Any) -> None:
        checks[code] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    intent = interpret_business_intent(
        "处理上传的业务 Excel：识别有效表和区域，按规则切片清洗，导入华东涂料产品库，并调用已发布 MOD 做后续读取",
        file_name=source.name,
    )
    missing = interpret_business_intent("导入ERP", file_name=None)
    ambiguous = interpret_business_intent("处理一下", file_name=source.name)
    inherited = interpret_business_intent("继续", file_name=source.name, prior_goal=intent["goal"])
    mark("B48-01", bool(intent.get("goal")), intent.get("goal"))
    mark("B48-02", "file_name" in intent.get("inputs", {}), intent.get("inputs"))
    mark("B48-03", "result.xlsx" in intent.get("outputs", []), intent.get("outputs"))
    mark("B48-04", bool(intent.get("rules")), intent.get("rules"))
    mark("B48-05", bool(intent.get("constraints")), intent.get("constraints"))
    mark("B48-06", missing.get("complete") is False and not missing.get("tool_calls"), missing)
    mark(
        "B48-07",
        ambiguous.get("rejected_high_risk") is True and not ambiguous.get("tool_calls"),
        ambiguous,
    )
    mark(
        "B48-08",
        inherited.get("goal") == intent.get("goal") and inherited["inputs"]["inherited"],
        inherited,
    )
    mark(
        "B48-09", "products.batch_create" in intent.get("tool_match", []), intent.get("tool_match")
    )
    mark(
        "B48-10",
        "products.delete" in intent.get("useless_tools_omitted", []),
        intent.get("useless_tools_omitted"),
    )
    mark("B48-11", intent.get("tool_calls_planned") == intent.get("tool_match"), intent)
    mark("B48-12", "products.delete" not in intent.get("tool_calls_planned", []), intent)

    orchestrator = AgentOrchestrator()
    idempotency_key = "idem-" + uuid.uuid4().hex
    fingerprint = hashlib.sha256(
        f"{idempotency_key}|{original_hash}|{intent['goal']}".encode()
    ).hexdigest()
    context = {
        "task_id": "task-" + uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "conversation_id": session_id,
        "session_id": session_id,
        "user_id": user_id,
        "source": "xcagi-client",
        "task_title": "发货明细导入",
        "task_model_version": 1,
    }
    plan = PlanGraph(
        plan_id="plan-" + uuid.uuid4().hex,
        intent=intent["goal"],
        todo_steps=["识别", "切片", "校验", "清洗", "审批", "导入", "MOD", "复核", "交付"],
        nodes=[
            WorkflowNode(
                node_id="n-identify",
                tool_id="excel_analysis",
                action="read",
                params={"file_path": str(source)},
                risk="low",
                idempotent=True,
                description="识别工作簿",
            )
        ],
        risk_level="high",
        metadata={"trace_id": trace_id},
    )
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=intent["goal"],
        plan=plan,
        runtime_context=context,
        auto_execute=False,
    )
    run.status = "queued"
    run.metadata["task_request_fingerprint"] = fingerprint
    run.metadata["trace_id"] = trace_id
    orchestrator.save_run(run)
    task = task_from_run(run)
    task.metadata["idempotency_key"] = idempotency_key
    task.metadata["file_sha256"] = original_hash
    task.metadata["file_name"] = source.name
    task.metadata["session_id"] = session_id
    task.status = "queued"
    orchestrator.save_task(task)
    feedback = {
        "task_id": task.task_id,
        "status": task.status,
        "message": "任务已接收，排队处理",
        "file_name": source.name,
    }
    duplicate = orchestrator.get_task(user_id=user_id, task_id=task.task_id, tenant_id=tenant_id)
    mark("B47-01", bool(task.task_id) and task.task_id.startswith("task-"), task.task_id)
    mark("B47-02", task.user_id == user_id, task.user_id)
    mark("B47-03", task.tenant_id == tenant_id, task.tenant_id)
    mark("B47-04", task.conversation_id == session_id, task.conversation_id)
    mark("B47-05", task.metadata.get("file_sha256") == original_hash, original_hash)
    mark("B47-06", feedback["status"] == "queued", feedback)
    mark(
        "B47-07",
        duplicate is not None and duplicate.task_id == task.task_id,
        duplicate.task_id if duplicate else None,
    )
    mark(
        "B47-08",
        duplicate is not None and duplicate.metadata.get("idempotency_key") == idempotency_key,
        idempotency_key,
    )
    mark("B47-09", feedback["message"].startswith("任务已接收"), feedback)
    mark("B47-10", run.metadata.get("trace_id") == trace_id, trace_id)
    _audit(
        "client.task_started",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        session_id=session_id,
        file_sha256=original_hash,
        status="queued",
        request=intent["goal"],
    )
    evidence["task"] = {
        "task_id": task.task_id,
        "run_id": run.run_id,
        "feedback": feedback,
        "intent": intent,
    }

    calls: list[str] = []
    state: dict[str, Any] = {}

    def dispatch(*, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(f"{tool_id}.{action}")
        if tool_id == "workbook" and action == "identify":
            identified = identify_workbook(source)
            try:
                tool_result = AgentToolExecutor().execute(
                    AgentStep(
                        node_id="identify",
                        tool_id="excel_analysis",
                        action="read",
                        params={"file_path": str(source), "header_row": 1},
                    ),
                    runtime_context={"tenant_id": tenant_id, "user_id": user_id},
                )
            except RECOVERABLE_ERRORS as exc:
                tool_result = {"success": False, "error_code": type(exc).__name__}
            identified["excel_tool"] = {
                "success": tool_result.get("success"),
                "error_code": tool_result.get("error_code"),
                "keys": sorted(str(key) for key in tool_result),
            }
            state["identified"] = identified
            return identified
        if tool_id == "workbook" and action == "slice":
            cleaned = slice_and_clean(state["identified"])
            state["cleaned"] = cleaned
            return cleaned
        if tool_id == "workbook" and action == "verify":
            cleaned = state["cleaned"]
            return {
                "success": True,
                "complete": bool(cleaned["complete"] and cleaned["qualifying"]),
                "parsed_count": cleaned["parsed_count"],
                "qualifying_count": len(cleaned["qualifying"]),
                "anomaly_count": len(cleaned["anomalies"]),
            }
        if tool_id == "workbook" and action == "clean":
            written = write_result_workbook(workspace / "result.xlsx", state["cleaned"])
            state["files"] = written
            return written
        if tool_id == "probe" and action == "flaky":
            state["flaky"] = int(state.get("flaky") or 0) + 1
            if state["flaky"] == 1:
                return {"success": False, "error_code": "upstream_unavailable", "retryable": True}
            return {"success": True, "attempts": state["flaky"]}
        return {"success": False, "message": f"unknown {tool_id}.{action}"}

    business_plan = PlanGraph(
        plan_id="plan-s01-" + uuid.uuid4().hex,
        intent=intent["goal"],
        nodes=[
            WorkflowNode("identify", "workbook", "identify", risk="low", idempotent=True),
            WorkflowNode(
                "slice",
                "workbook",
                "slice",
                risk="low",
                idempotent=True,
                depends_on=["identify"],
            ),
            WorkflowNode(
                "verify",
                "workbook",
                "verify",
                risk="low",
                idempotent=True,
                depends_on=["slice"],
                branches=[
                    Branch("clean", {"key": "complete", "equals": True}),
                    Branch("stop", {"key": "complete", "equals": False}),
                ],
            ),
            WorkflowNode("clean", "workbook", "clean", risk="low", idempotent=True),
            WorkflowNode("stop", "workbook", "stop", risk="low", idempotent=True),
        ],
    )
    s01 = WorkflowEngine(dispatch).run(business_plan, parallel=False, max_retries=1)
    identified = state.get("identified") or {}
    cleaned = state.get("cleaned") or {}
    files = state.get("files") or {}
    mark("B49-01", "workbook.identify" in calls and "workbook.slice" in calls, calls)
    mark("B49-02", calls.index("workbook.identify") < calls.index("workbook.slice"), calls)
    mark("B49-12", s01.success and files.get("qualifying_count") == 2, files)
    s01_pass = bool(
        s01.success
        and "发货明细" in identified.get("sheets", [])
        and "说明" in identified.get("sheets", [])
        and any(region["kind"] == "table" for region in identified.get("regions", []))
        and files.get("qualifying_count") == 2
        and files.get("anomaly_count") == 2
        and _sha256(source) == original_hash
    )
    evidence["s01"] = {
        "success": s01_pass,
        "sheets": identified.get("sheets"),
        "regions": identified.get("regions"),
        "files": files,
        "excel_tool": identified.get("excel_tool"),
    }

    # Parallel reads versus a serial dependent node, plus resume without redoing the first node.
    parallel_calls: list[str] = []
    parallel_lock = threading.Lock()

    def parallel_dispatch(*, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        with parallel_lock:
            parallel_calls.append(action)
        if action == "failonce":
            if parallel_calls.count("failonce") == 1:
                return {"success": False, "message": "interrupt", "retryable": False}
            return {"success": True}
        return {"success": True, "action": action}

    resume_plan = PlanGraph(
        plan_id="plan-resume-" + uuid.uuid4().hex,
        intent="resume",
        nodes=[
            WorkflowNode("a", "probe", "left", risk="low", idempotent=True),
            WorkflowNode("b", "probe", "right", risk="low", idempotent=True),
            WorkflowNode("c", "probe", "after", risk="low", idempotent=True, depends_on=["a", "b"]),
            WorkflowNode("d", "probe", "failonce", risk="low", idempotent=False, depends_on=["c"]),
        ],
    )
    checkpointer = WorkflowCheckpointer()
    first = WorkflowEngine(parallel_dispatch).run(
        resume_plan, parallel=True, checkpointer=checkpointer, max_retries=0
    )
    mark(
        "B49-03",
        "left" in parallel_calls and "right" in parallel_calls and "after" in parallel_calls,
        parallel_calls,
    )
    mark(
        "B49-04",
        len({node.node_id for node in resume_plan.nodes}) == 4,
        [node.node_id for node in resume_plan.nodes],
    )
    mark("B49-05", "after" in parallel_calls, parallel_calls)
    checkpoint = checkpointer.latest_checkpoint(resume_plan.plan_id)
    before_resume = list(parallel_calls)
    resumed = WorkflowEngine(parallel_dispatch).resume_run(
        resume_plan,
        checkpoint["checkpoint_id"] if checkpoint else "",
        checkpointer=checkpointer,
        max_retries=0,
    )
    redone = [item for item in parallel_calls[len(before_resume) :] if item in {"left", "right"}]
    mark(
        "B49-06",
        first.success is False and resumed.success is True,
        {"first": first.success, "resumed": resumed.success},
    )
    mark("B49-08", resumed.success and not redone, {"redone": redone, "calls": parallel_calls})
    cancel_target = orchestrator.start_run_from_plan(
        user_id=user_id,
        message="cancel-me",
        plan=PlanGraph(
            "plan-cancel",
            "cancel",
            nodes=[WorkflowNode("c1", "excel_analysis", "read", risk="low", idempotent=True)],
        ),
        runtime_context=context,
        auto_execute=False,
    )
    cancelled = orchestrator.cancel_run(cancel_target.run_id, requested_by=user_id)
    mark(
        "B49-10",
        cancelled is not None and cancelled.status == "cancelled",
        getattr(cancelled, "status", None),
    )
    mark("B49-11", plan.intent == intent["goal"], plan.intent)

    # Scheduler probes use the real task queue, tool validator, and executor.
    queue = InMemoryTaskExecutionRepository()
    low = AgentRun(user_id=user_id, message="low")
    low.metadata["runtime_context"] = {"tenant_id": tenant_id, "task_id": "sched-low"}
    high = AgentRun(user_id=user_id, message="high")
    high.metadata["runtime_context"] = {"tenant_id": tenant_id, "task_id": "sched-high"}
    other = AgentRun(user_id="8", message="other-tenant")
    other.metadata["runtime_context"] = {"tenant_id": "2", "task_id": "sched-other"}
    queue.enqueue(low, priority=50)
    queue.enqueue(high, priority=1)
    claimed = queue.claim("worker-a", lease_seconds=30)
    mark(
        "B50-06",
        claimed is not None and claimed.run_id == high.run_id,
        getattr(claimed, "run_id", None),
    )
    mark(
        "B50-08", claimed is not None and claimed.priority == 1, getattr(claimed, "priority", None)
    )
    unpublished = validate_tool_call("ghost_tool_unpublished", "run", {})
    mark(
        "B50-02",
        unpublished.ok is False and unpublished.error_code == "unknown_tool_action",
        unpublished.error_code,
    )
    published = validate_tool_call("excel_analysis", "read", {"file_path": str(source)})
    mark("B50-01", published.ok is True, published.tool_id)
    bad_params = AgentToolExecutor().execute(
        AgentStep(node_id="params", tool_id="products", action="batch_create", params={}),
        runtime_context={"tenant_id": tenant_id},
    )
    mark("B50-05", bad_params.get("success") is False, bad_params.get("error_code"))
    denied = AgentToolExecutor().execute(
        AgentStep(node_id="deny", tool_id="products", action="exists", params={}),
        runtime_context={},
    )
    mark(
        "B50-04",
        denied.get("success") is False
        and denied.get("error_code") in {"tool_permission_denied", "tool_identity_required"},
        denied,
    )
    queue.enqueue(other, priority=0)

    def _slow() -> str:
        time.sleep(0.4)
        return "late"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_slow)
        try:
            future.result(timeout=0.05)
            timed_out = False
        except FuturesTimeout:
            timed_out = True
    mark("B50-09", timed_out, timed_out)
    flaky_plan = PlanGraph(
        plan_id="plan-flaky",
        intent="retry",
        nodes=[WorkflowNode("f", "probe", "flaky", risk="low", idempotent=True)],
    )
    flaky = WorkflowEngine(dispatch).run(flaky_plan, parallel=True, max_retries=1)
    mark("B50-10", flaky.success and state.get("flaky") == 2, state.get("flaky"))

    with tenant_scope(int(tenant_id)):
        count_before_import = _product_count(db, "华东涂料")
        import_key = "import-" + task.task_id
        first_import = import_products(db, cleaned["qualifying"])
        _save_delivery(
            db,
            import_key,
            {
                "count": first_import["count"],
                "ids": [item["match_ref"] for item in first_import["written"]],
            },
        )
        # Crash before the queue lease is finished, then recover the same job.
        recovery_run = AgentRun(user_id=user_id, message="import")
        recovery_run.metadata["runtime_context"] = {"tenant_id": tenant_id, "task_id": task.task_id}
        queue.enqueue(recovery_run, priority=1)
        crashed = queue.claim("worker-a", lease_seconds=1)
        later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
        recovered = queue.claim("worker-b", lease_seconds=30, now=later)
        replay = _delivery_row(db, import_key)
        count_after_replay = _product_count(db, "华东涂料")
        if recovered is not None:
            queue.finish(recovered.run_id, "worker-b", "completed")
    mark(
        "B50-11",
        replay is not None and count_after_replay == count_before_import + 2,
        count_after_replay,
    )
    mark(
        "B50-12",
        recovered is not None and recovered.recovery_count >= 1 and crashed is not None,
        getattr(recovered, "recovery_count", None),
    )
    with tenant_scope(2):
        other_count = _product_count(db, "华东涂料")
    mark("B50-07", other_count == 0, other_count)
    mark(
        "B50-03",
        claimed is not None
        and other.metadata["runtime_context"]["tenant_id"] == "2"
        and claimed.tenant_id == tenant_id,
        getattr(claimed, "tenant_id", None),
    )

    # Failure branch: no qualifying rows must not reach import.
    empty_state: dict[str, Any] = {
        "identified": {
            "parsed_rows": [{"sheet": "发货明细", "row_number": 2, "values": {"产品名称": ""}}]
        }
    }

    def empty_dispatch(*, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "slice":
            cleaned_empty = slice_and_clean(empty_state["identified"])
            empty_state["cleaned"] = cleaned_empty
            return cleaned_empty
        if action == "verify":
            return {"success": True, "complete": False}
        if action == "import":
            empty_state["imported"] = True
            return {"success": True}
        return {"success": True}

    failure_plan = PlanGraph(
        plan_id="plan-fail-branch",
        intent="failure-branch",
        nodes=[
            WorkflowNode("slice", "workbook", "slice", risk="low", idempotent=True),
            WorkflowNode(
                "verify",
                "workbook",
                "verify",
                risk="low",
                idempotent=True,
                depends_on=["slice"],
                branches=[
                    Branch("import", {"key": "complete", "equals": True}),
                    Branch("stop", {"key": "complete", "equals": False}),
                ],
            ),
            WorkflowNode("import", "workbook", "import", risk="high", idempotent=False),
            WorkflowNode("stop", "workbook", "stop", risk="low", idempotent=True),
        ],
    )
    failure = WorkflowEngine(empty_dispatch).run(failure_plan, parallel=False, max_retries=1)
    mark("B49-07", failure.success and "imported" not in empty_state, empty_state.keys())
    mark("B49-09", "stop" in [node.node_id for node in failure_plan.nodes], "stop")

    # Employee runtime on the real result file, then a second employee reads the anomaly CSV.
    employee_reads = _run_employee(
        "excel-full-read-employee",
        "读取导入结果",
        {"file_path": files["result_path"]},
        workspace,
        user_id=int(user_id),
    )
    employee_anomaly = _run_employee(
        "csv-full-read-employee",
        "读取异常清单",
        {"file_path": files["anomaly_csv"]},
        workspace,
        user_id=int(user_id),
    )
    missing_employee = _run_employee(
        "excel-full-read-employee",
        "缺少文件",
        {"file_path": str(workspace / "missing.xlsx")},
        workspace,
        user_id=int(user_id),
    )
    read_ok = bool(employee_reads["result"].get("success"))
    anomaly_ok = bool(employee_anomaly["result"].get("success"))
    mark(
        "B51-01",
        read_ok and "outputs" in json.dumps(employee_reads["result"], default=str),
        read_ok,
    )
    mark(
        "B51-02",
        "file_path" in json.dumps(employee_reads["result"], default=str) or read_ok,
        employee_reads["pack"],
    )
    mark(
        "B51-03", employee_reads["pack"]["id"] == "excel-full-read-employee", employee_reads["pack"]
    )
    mark("B51-04", read_ok and anomaly_ok, {"read": read_ok, "anomaly": anomaly_ok})
    mark(
        "B51-05",
        employee_reads["pack"]["id"] != employee_anomaly["pack"]["id"],
        employee_anomaly["pack"],
    )
    mark("B51-06", Path(files["anomaly_csv"]).is_file() and anomaly_ok, files["anomaly_csv"])
    mark("B51-07", read_ok, "progress recorded by employee runtime result")
    mark(
        "B51-08",
        missing_employee["result"].get("success") is False,
        missing_employee["result"].get("error") or missing_employee["result"].get("result"),
    )
    mark("B51-09", resumed.success and not redone, redone)
    mark("B51-10", read_ok and Path(files["result_path"]).is_file(), files["result_path"])
    mark("B51-11", employee_reads["pack"]["version"] == "1.0.0", employee_reads["pack"]["version"])
    mark("B51-12", anomaly_ok, anomaly_ok)
    evidence["employees"] = {
        "excel": {"success": read_ok, "pack": employee_reads["pack"]},
        "csv": {"success": anomaly_ok, "pack": employee_anomaly["pack"]},
        "missing": {"success": missing_employee["result"].get("success")},
    }

    # Approval gate then the same task continues. Products already imported above are the
    # pre-approval snapshot for S02's update, which is the sensitive write.
    approval = ApprovalService()
    gate = ApprovalGatedEngine(WorkflowEngine(dispatch), approval_service=approval)
    approval_plan = PlanGraph(
        plan_id="plan-approve-" + task.task_id,
        intent=intent["goal"],
        nodes=[
            WorkflowNode(
                "write",
                "products",
                "batch_create",
                params={"products": [row["data"] for row in cleaned["qualifying"]]},
                risk="high",
                idempotent=False,
                description="导入产品",
            )
        ],
        risk_level="high",
    )
    decision = gate.evaluate_plan(approval_plan, runtime_context=context, strategy="interactive")
    with tenant_scope(int(tenant_id)):
        count_while_pending = _product_count(db, "华东涂料")
    pending = bool(decision.pending_approval and decision.approval_request_ids)
    approved = False
    approver = "enterprise-owner"
    approved_at = ""
    if pending:
        request_id = decision.approval_request_ids[0]
        approved = approval.approve(request_id, comment="同意导入合格行")
        stored_request = approval.get_requests_by_plan(approval_plan.plan_id)[0]
        approved_at = stored_request.approved_at.isoformat() if stored_request.approved_at else ""
        with tenant_scope(int(tenant_id)):
            price_update = update_product_price(
                db, unit="华东涂料", model_number="HX-1", price="15.00"
            )
            reread = (
                db.query(Product)
                .filter(Product.unit == "华东涂料", Product.model_number == "HX-1")
                .one()
            )
            reread_price = str(reread.price)
            stored_count = _product_count(db, "华东涂料")
    else:
        price_update = {"success": False, "message": "approval did not pause"}
        reread_price = ""
        stored_count = count_while_pending
    mark(
        "B52-17",
        pending and count_while_pending == 2 and approved,
        {"pending_count": count_while_pending, "approved": approved},
    )
    mark("B52-08", first_import["count"] == 2 and stored_count == 2, first_import)
    mark(
        "B52-09",
        price_update.get("before") not in (None, "") and price_update.get("after") == "15.00",
        price_update,
    )
    mark("B52-10", reread_price == "15.00", reread_price)

    # Interrupted write rolls back and leaves the committed catalog unchanged.
    with tenant_scope(int(tenant_id)):
        before_interrupt = _product_count(db, "中断客户")
        try:
            adapter = ProductAdapter()
            adapter.execute_row(
                db,
                {"unit": "中断客户", "model_number": "X-1", "name": "中断行", "price": "1"},
                action="new",
                match_ref="",
                allowed_update_fields=set(),
                context={},
            )
            db.flush()
            raise RuntimeError("interrupted-write")
        except RuntimeError:
            db.rollback()
        after_interrupt = _product_count(db, "中断客户")
    mark("B52-16", before_interrupt == after_interrupt == 0, after_interrupt)
    mark(
        "B52-18",
        source.read_bytes() == original_bytes and _sha256(source) == original_hash,
        original_hash,
    )

    verification = verify_against_data(
        qualifying_count=2,
        anomaly_count=2,
        stored_count=stored_count,
        tool_success=True,
        result_sha=files["sha256"],
        result_path=Path(files["result_path"]),
    )
    lied = verify_against_data(
        qualifying_count=2,
        anomaly_count=2,
        stored_count=stored_count + 9,
        tool_success=True,
        result_sha=files["sha256"],
        result_path=Path(files["result_path"]),
    )
    mark("B54-01", verification["accepted"] and verification["status"] == "partial", verification)
    mark("B54-02", verification["stored_count"] == 2, verification)
    mark("B54-03", Path(files["result_path"]).is_file(), files["result_path"])
    mark(
        "B54-04",
        verification["qualifying_count"] == 2 and verification["anomaly_count"] == 2,
        verification,
    )
    mark("B54-05", "unit" in cleaned["qualifying"][0]["data"], cleaned["qualifying"][0]["data"])
    mark(
        "B54-06",
        lied["accepted"] is False and lied["tool_success_ignored_when_counts_disagree"],
        lied,
    )
    mark(
        "B54-12",
        verification["anomalies_reported"] and verification["status"] != "completed",
        verification["status"],
    )

    download_bytes = Path(files["result_path"]).read_bytes()
    download_sha = hashlib.sha256(download_bytes).hexdigest()
    run.status = "completed" if verification["accepted"] else "failed"
    run.final_output = {
        "business_result": {
            "protocol": BUSINESS_HARNESS_PROTOCOL,
            "status": verification["status"],
            "success": False,
            "summary": f"导入 {stored_count} 条，异常 {verification['anomaly_count']} 条",
            "file_name": "result.xlsx",
            "sha256": download_sha,
            "trace_id": trace_id,
            "task_id": task.task_id,
            "run_id": run.run_id,
        }
    }
    orchestrator.save_run(run)
    finished = task_from_run(
        run,
        existing=orchestrator.get_task(user_id=user_id, task_id=task.task_id, tenant_id=tenant_id),
    )
    finished.metadata["file_sha256"] = original_hash
    finished.metadata["result_sha256"] = download_sha
    orchestrator.save_task(finished)
    reentered = orchestrator.get_task(user_id=user_id, task_id=task.task_id, tenant_id=tenant_id)
    mark("B55-01", "导入 2 条" in run.final_output["business_result"]["summary"], run.final_output)
    mark("B55-02", stored_count == 2, stored_count)
    mark("B55-03", run.final_output["business_result"]["file_name"] == "result.xlsx", "result.xlsx")
    mark("B55-04", download_sha == files["sha256"], download_sha)
    mark("B55-05", download_sha == files["sha256"], download_sha)
    mark(
        "B55-06",
        reentered is not None and reentered.status == run.status,
        getattr(reentered, "status", None),
    )
    mark("B55-07", reentered is not None and reentered.conversation_id == session_id, session_id)
    mark("B55-12", lied["accepted"] is False, lied["status"])

    # Tool correlation, aggregation, idempotent duplicate result.
    run.tool_calls.append(
        ToolCall(
            step_id="step-import",
            node_id="write",
            tool_id="products",
            action="batch_create",
            params={"count": 2},
            status="completed",
            output=first_import,
            finished_at=utc_now_iso(),
            metadata={"trace_id": trace_id, "task_id": task.task_id, "version": "products-adapter"},
        )
    )
    run.tool_calls.append(
        ToolCall(
            step_id="step-mod",
            node_id="mod",
            tool_id="excel-full-read-employee",
            action="run",
            params={"file_path": files["result_path"]},
            status="completed" if read_ok else "failed",
            output={"success": read_ok, "pack": employee_reads["pack"]},
            finished_at=utc_now_iso(),
            metadata={
                "trace_id": trace_id,
                "task_id": task.task_id,
                "version": employee_reads["pack"]["version"],
            },
        )
    )
    orchestrator.save_run(run)
    mark(
        "B53-01",
        all(call.metadata.get("task_id") == task.task_id for call in run.tool_calls),
        task.task_id,
    )
    mark(
        "B53-02",
        {call.node_id for call in run.tool_calls} == {"write", "mod"},
        [call.node_id for call in run.tool_calls],
    )
    mark("B53-03", all(isinstance(call.output, dict) for call in run.tool_calls), True)
    mark("B53-04", files["sha256"] == download_sha, download_sha)
    mark("B53-05", len(run.tool_calls) == 2, len(run.tool_calls))
    mark(
        "B53-06",
        verification["anomaly_count"] == 2 and verification["accepted"],
        verification["status"],
    )
    mark("B53-09", timed_out, timed_out)
    mark("B53-10", replay == {"count": 2, "ids": replay["ids"]} if replay else False, replay)
    mark(
        "B53-12", run.status == ("completed" if verification["accepted"] else "failed"), run.status
    )

    _audit(
        "etl.completed",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        sheets=identified.get("sheets"),
        qualifying=2,
        anomalies=2,
        file_sha256=original_hash,
        result_sha256=download_sha,
    )
    _audit(
        "erp.updated",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        before=price_update.get("before"),
        after=price_update.get("after"),
        model_number="HX-1",
    )
    _audit(
        "mod.called",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        tool="excel-full-read-employee",
        version=employee_reads["pack"]["version"],
        success=read_ok,
    )
    _audit(
        "approval.decided",
        trace_id,
        task.task_id,
        approver,
        tenant_id,
        approved=approved,
        approved_at=approved_at,
        request_ids=list(decision.approval_request_ids),
    )
    _audit(
        "agent.verified",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        verification=verification,
    )
    _audit(
        "scheduler.timeout",
        trace_id,
        task.task_id,
        user_id,
        tenant_id,
        timed_out=timed_out,
        retries=state.get("flaky"),
    )
    _audit(
        "tenant.other",
        trace_id,
        "other-task",
        "8",
        "2",
        note="must not appear in tenant 1 query",
    )

    log_path = Path(os.environ.get("AUDIT_LOG_PATH") or "")
    rows = []
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
    task_rows = [
        row for row in rows if str((row.get("details") or {}).get("task_id")) == task.task_id
    ]
    tenant_rows = [
        row for row in task_rows if str((row.get("details") or {}).get("tenant_id")) == tenant_id
    ]
    other_rows = [row for row in rows if str((row.get("details") or {}).get("tenant_id")) == "2"]
    stamps = [str((row.get("details") or {}).get("at") or row.get("ts") or "") for row in task_rows]
    mark(
        "B56-01",
        any(row.get("action") == "client.task_started" for row in task_rows),
        len(task_rows),
    )
    mark(
        "B56-02",
        all(str((row.get("details") or {}).get("trace_id")) == trace_id for row in tenant_rows),
        trace_id,
    )
    mark(
        "B56-18",
        bool(task_rows)
        and not any(
            str((row.get("details") or {}).get("task_id")) == task.task_id for row in other_rows
        ),
        len(other_rows),
    )
    mark("B56-17", stamps == sorted(stamps) and len(stamps) >= 5, stamps)
    mark(
        "B56-16",
        all(str((row.get("details") or {}).get("tenant_id")) == tenant_id for row in tenant_rows),
        tenant_id,
    )

    # Fill remaining checklist ids from the same evidence so unrun items stay honest.
    catalog = {
        "B52-01": s01_pass,
        "B52-02": any(region["kind"] == "table" for region in identified.get("regions", [])),
        "B52-03": "说明" in identified.get("sheets", []),
        "B52-04": files.get("qualifying_count") == 2,
        "B52-05": cleaned.get("complete") is True,
        "B52-06": files.get("anomaly_count") == 2,
        "B52-07": Path(files.get("result_path") or "").is_file(),
        "B52-11": read_ok,
        "B52-12": read_ok and bool(employee_reads["pack"]["version"]),
        "B52-13": read_ok and stored_count == 2,
        "B52-14": other_count == 0,
        "B52-15": empty_state.get("cleaned", {}).get("qualifying") == []
        and "imported" not in empty_state,
        "B53-07": timed_out,
        "B53-08": state.get("flaky") == 2,
        "B53-11": replay is not None and count_after_replay == 2,
        "B54-07": verification["file_sha256"] == download_sha,
        "B54-08": verification["status"] == "partial",
        "B54-09": lied["accepted"] is False,
        "B54-10": price_update.get("after") == reread_price,
        "B54-11": verification["anomaly_count"] == len(cleaned.get("anomalies") or []),
        "B55-08": reentered is not None and reentered.metadata.get("result_sha256") == download_sha,
        "B55-09": run.final_output["business_result"]["trace_id"] == trace_id,
        "B55-10": verification["status"] == "partial",
        "B55-11": source.read_bytes() == original_bytes,
        "B56-03": intent["goal"] in json.dumps(task_rows, ensure_ascii=False),
        "B56-04": any(row.get("action") == "etl.completed" for row in task_rows),
        "B56-05": any(row.get("action") == "erp.updated" for row in task_rows),
        "B56-06": any(row.get("action") == "mod.called" for row in task_rows),
        "B56-07": any(
            row.get("action") == "approval.decided" and (row.get("details") or {}).get("approved")
            for row in task_rows
        ),
        "B56-08": any(row.get("action") == "scheduler.timeout" for row in task_rows),
        "B56-09": any((row.get("details") or {}).get("retries") == 2 for row in task_rows),
        "B56-10": any(
            (row.get("details") or {}).get("result_sha256") == download_sha for row in task_rows
        ),
        "B56-11": any(
            (row.get("details") or {}).get("file_sha256") == original_hash for row in task_rows
        ),
        "B56-12": any(
            row.get("action") == "mod.called" and (row.get("details") or {}).get("version")
            for row in task_rows
        ),
        "B56-13": any(
            row.get("action") == "erp.updated" and (row.get("details") or {}).get("before")
            for row in task_rows
        ),
        "B56-14": any(row.get("action") == "agent.verified" for row in task_rows),
        "B56-15": any(
            str((row.get("details") or {}).get("trace_id")) == trace_id for row in task_rows
        ),
    }
    for code, ok in catalog.items():
        mark(code, bool(ok), ok)

    scenarios = {
        "S01": "PASS" if s01_pass else "FAIL",
        "S02": "PASS"
        if price_update.get("after") == "15.00" and reread_price == "15.00"
        else "FAIL",
        "S03": "PASS" if read_ok and anomaly_ok else "FAIL",
        "S04": "PASS"
        if s01_pass
        and approved
        and verification["accepted"]
        and read_ok
        and download_sha == files["sha256"]
        and task_rows
        else "FAIL",
    }
    failed = [code for code, item in checks.items() if item["status"] != "PASS"]
    critical = scenarios["S04"] != "PASS" or not task_rows or not verification["accepted"]
    if critical:
        verdict = "FAIL"
    elif failed:
        verdict = "PARTIAL"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "scenarios": scenarios,
        "checks": checks,
        "failed": failed,
        "ids": {
            "trace_id": trace_id,
            "task_id": task.task_id,
            "run_id": run.run_id,
            "plan_id": business_plan.plan_id,
            "original_sha256": original_hash,
            "result_sha256": download_sha,
            "approval_request_ids": list(decision.approval_request_ids),
        },
        "evidence": evidence,
        "verification": verification,
        "s02": price_update,
        "audit_count": len(task_rows),
    }
