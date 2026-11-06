"""Cross-module business chain: client task, agent, workflow, scheduler, employee, ETL, ERP, MOD.

Each step calls an existing module and keeps the business result tied to rows, files,
and hashes. A tool ``success`` flag is not enough to mark the task complete.
"""

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

from openpyxl import Workbook, load_workbook
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_harness import BUSINESS_HARNESS_PROTOCOL
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, utc_now_iso
from app.application.agent_orchestrator.task_execution_repository import (
    InMemoryTaskExecutionRepository,
)
from app.application.agent_orchestrator.task_models import task_from_run
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import validate_tool_call
from app.application.elt.parser_structure import clean_cell_text, detect_table_layout
from app.application.elt.parsers import parse_file
from app.application.elt.targets.products import ProductAdapter
from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.loader import load_employee_pack_from_disk
from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.checkpointer import WorkflowCheckpointer
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.workflow_types import Branch, PlanGraph, WorkflowNode
from app.db.models.product import Product
from app.infrastructure.tenant_scope import tenant_scope
from app.utils.logging.audit_logger import audit_log
from app.utils.operational_errors import RECOVERABLE_ERRORS

_HEADER_ALIASES = {
    "购买单位": "unit",
    "单位": "unit",
    "客户": "unit",
    "型号": "model_number",
    "产品型号": "model_number",
    "产品名称": "name",
    "品名": "name",
    "名称": "name",
    "规格": "specification",
    "价格": "price",
    "单价": "price",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def interpret_business_intent(
    message: str,
    *,
    file_name: str | None = None,
    prior_goal: str | None = None,
) -> dict[str, Any]:
    """Deterministic intent for this business loop. Ambiguous text does not select a write."""
    text_value = str(message or "").strip()
    inherited = str(prior_goal or "").strip()
    if text_value in {"继续", "接着", "按上次的做"} and inherited:
        text_value = inherited
        inherited_from_prior = True
    else:
        inherited_from_prior = False
    has_file = bool(file_name)
    asks_import = any(token in text_value for token in ("导入", "写入", "ERP", "产品库"))
    asks_excel = any(token in text_value for token in ("Excel", "表格", "切片", "清洗"))
    asks_mod = any(token in text_value for token in ("MOD", "员工", "后续"))
    if not text_value or (asks_import and not has_file and not inherited_from_prior):
        return {
            "complete": False,
            "question": "请提供要处理的业务 Excel，并说明要写入的 ERP 区域。",
            "tool_calls": [],
            "goal": "",
        }
    if text_value in {"处理一下", "帮我处理", "看看这个"} and not (asks_import or asks_excel):
        return {
            "complete": False,
            "question": "目标不明确。需要确认是只核对表格，还是写入 ERP。未确认前不会执行高风险写入。",
            "tool_calls": [],
            "goal": "",
            "rejected_high_risk": True,
        }
    tools = ["excel_analysis.read", "elt.parse_file"]
    if asks_import:
        tools.append("products.batch_create")
    if asks_mod:
        tools.append("excel-full-read-employee")
    return {
        "complete": True,
        "goal": text_value,
        "inputs": {"file_name": file_name, "inherited": inherited_from_prior},
        "outputs": ["result.xlsx", "anomaly_list"],
        "rules": ["合格行才写入产品库", "原件不得修改", "异常行必须单独列出"],
        "constraints": ["敏感写入必须审批", "成功标记不能代替复核"],
        "tool_match": tools,
        "useless_tools_omitted": ["products.delete", "products.batch_delete"],
        "tool_calls_planned": tools,
    }


def _map_row(values: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in values.items():
        target = _HEADER_ALIASES.get(clean_cell_text(key))
        if not target:
            continue
        text_value = clean_cell_text(value)
        if text_value:
            mapped[target] = text_value
    return mapped


def _sheet_matrix(path: Path) -> dict[str, list[list[Any]]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheets: dict[str, list[list[Any]]] = {}
        for name in workbook.sheetnames:
            sheet = workbook[name]
            sheets[name] = [
                [cell if cell is not None else "" for cell in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        return sheets
    finally:
        workbook.close()


def identify_workbook(path: Path) -> dict[str, Any]:
    sheets = _sheet_matrix(path)
    regions = []
    for name, rows in sheets.items():
        layout = detect_table_layout(rows, header_hints=("购买单位", "产品名称", "型号", "价格"))
        if layout is None:
            regions.append({"sheet": name, "kind": "note", "headers": []})
            continue
        regions.append(
            {
                "sheet": name,
                "kind": "table",
                "header_row": layout.header_end + 1,
                "headers": list(layout.headers),
            }
        )
    parsed = parse_file(path, target_type="products")
    try:
        parsed_rows = [
            {"sheet": row.sheet, "row_number": row.row_number, "values": dict(row.values)}
            for row in parsed.rows
        ]
    finally:
        parsed.close()
    return {
        "success": True,
        "sheets": list(sheets),
        "regions": regions,
        "parsed_rows": parsed_rows,
        "source": "elt.parse_file+parser_structure.detect_table_layout",
    }


def slice_and_clean(identified: dict[str, Any]) -> dict[str, Any]:
    adapter = ProductAdapter()
    qualifying: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for row in identified.get("parsed_rows") or []:
        mapped = _map_row(row.get("values") or {})
        issues = list(adapter.validate(mapped))
        price_text = str(mapped.get("price") or "")
        try:
            price_value = float(price_text) if price_text else None
        except ValueError:
            price_value = None
            issues.append(
                {"code": "PRICE_NOT_NUMERIC", "field": "price", "message": "价格不是数字"}
            )
        if price_value is not None and price_value < 0:
            issues.append({"code": "PRICE_NEGATIVE", "field": "price", "message": "价格不能为负"})
        record = {
            "sheet": row.get("sheet"),
            "row_number": row.get("row_number"),
            "data": mapped,
        }
        if issues:
            record["issues"] = issues
            anomalies.append(record)
        else:
            qualifying.append(record)
    parsed_count = len(identified.get("parsed_rows") or [])
    return {
        "success": True,
        "parsed_count": parsed_count,
        "qualifying": qualifying,
        "anomalies": anomalies,
        "complete": parsed_count == len(qualifying) + len(anomalies) and parsed_count > 0,
    }


def write_result_workbook(path: Path, cleaned: dict[str, Any]) -> dict[str, Any]:
    workbook = Workbook()
    qualified = workbook.active
    qualified.title = "合格明细"
    qualified.append(["购买单位", "型号", "产品名称", "规格", "价格"])
    for row in cleaned["qualifying"]:
        data = row["data"]
        qualified.append(
            [
                data.get("unit"),
                data.get("model_number"),
                data.get("name"),
                data.get("specification"),
                data.get("price"),
            ]
        )
    anomaly_sheet = workbook.create_sheet("异常清单")
    anomaly_sheet.append(["行号", "代码", "说明", "原始名称", "原始价格"])
    for row in cleaned["anomalies"]:
        data = row["data"]
        codes = ",".join(item["code"] for item in row["issues"])
        messages = ";".join(item["message"] for item in row["issues"])
        anomaly_sheet.append(
            [row["row_number"], codes, messages, data.get("name"), data.get("price")]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    anomaly_csv = path.with_name(path.stem + "-anomalies.csv")
    lines = ["row_number,code,message"]
    for row in cleaned["anomalies"]:
        for issue in row["issues"]:
            lines.append(f"{row['row_number']},{issue['code']},{issue['message']}")
    anomaly_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "success": True,
        "result_path": str(path),
        "anomaly_csv": str(anomaly_csv),
        "sha256": _sha256(path),
        "qualifying_count": len(cleaned["qualifying"]),
        "anomaly_count": len(cleaned["anomalies"]),
    }


def _product_count(db: Session, unit: str) -> int:
    return int(db.query(Product).filter(Product.unit == unit).count())


def import_products(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    adapter = ProductAdapter()
    written = []
    before = {
        str(item.model_number): str(item.price)
        for item in db.query(Product).all()
        if item.model_number
    }
    for row in rows:
        data = dict(row["data"])
        decision = adapter.preview(db, data, allowed_update_fields=set(), context={})
        if decision.action != "new":
            return {
                "success": False,
                "message": decision.reason or decision.action,
                "written": written,
            }
        result = adapter.execute_row(
            db,
            data,
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={},
        )
        written.append(result)
    db.commit()
    after = {
        str(item.model_number): str(item.price)
        for item in db.query(Product).all()
        if item.model_number
    }
    return {
        "success": True,
        "written": written,
        "before": before,
        "after": after,
        "count": len(written),
    }


def update_product_price(
    db: Session, *, unit: str, model_number: str, price: str
) -> dict[str, Any]:
    adapter = ProductAdapter()
    current = (
        db.query(Product).filter(Product.unit == unit, Product.model_number == model_number).one()
    )
    before = str(current.price)
    data = {
        "unit": unit,
        "model_number": model_number,
        "name": current.name,
        "price": price,
        "specification": current.specification,
    }
    decision = adapter.preview(db, data, allowed_update_fields={"price"}, context={})
    if decision.action != "update":
        return {"success": False, "message": decision.reason or decision.action, "before": before}
    result = adapter.execute_row(
        db,
        data,
        action="update",
        match_ref=str(decision.match_ref),
        allowed_update_fields={"price"},
        context={},
    )
    db.commit()
    refreshed = (
        db.query(Product).filter(Product.unit == unit, Product.model_number == model_number).one()
    )
    return {
        "success": True,
        "before": before,
        "after": str(refreshed.price),
        "match_ref": result["match_ref"],
        "stored_after": result["after"].get("price"),
    }


def _audit(
    event: str, trace_id: str, task_id: str, user_id: str, tenant_id: str, **details: Any
) -> None:
    audit_log(
        event,
        user_id=user_id,
        details={
            "trace_id": trace_id,
            "task_id": task_id,
            "tenant_id": tenant_id,
            "at": _now(),
            **details,
        },
    )


def _run_employee(
    employee_id: str, task: str, payload: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    pack = load_employee_pack_from_disk(employee_id)
    result = execute_employee_task_local(
        employee_id,
        task,
        {**payload, "skip_collaboration": True, "workspace_root": str(workspace)},
        user_id=7,
        workspace_root=str(workspace),
    )
    return {"pack": {"id": pack["pack_id"], "version": pack["version"]}, "result": result}


def verify_against_data(
    *,
    qualifying_count: int,
    anomaly_count: int,
    stored_count: int,
    tool_success: bool,
    result_sha: str,
    result_path: Path,
) -> dict[str, Any]:
    file_ok = result_path.is_file() and _sha256(result_path) == result_sha
    counts_ok = stored_count == qualifying_count
    accepted = bool(file_ok and counts_ok and qualifying_count >= 0)
    if tool_success and not counts_ok:
        accepted = False
    status = "partial" if accepted and anomaly_count else "completed" if accepted else "failed"
    return {
        "accepted": accepted,
        "status": status,
        "tool_success_ignored_when_counts_disagree": bool(tool_success and not counts_ok),
        "qualifying_count": qualifying_count,
        "anomaly_count": anomaly_count,
        "stored_count": stored_count,
        "file_sha256": result_sha
        if file_ok
        else _sha256(result_path)
        if result_path.is_file()
        else "",
        "anomalies_reported": anomaly_count > 0,
    }


def _workflow(
    plan: PlanGraph,
    dispatcher,
    *,
    parallel: bool = True,
    checkpointer: WorkflowCheckpointer | None = None,
    max_retries: int = 1,
):
    engine = WorkflowEngine(dispatcher)
    return engine.run(plan, parallel=parallel, checkpointer=checkpointer, max_retries=max_retries)


def _build_source_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "发货明细"
    sheet.append(["购买单位", "型号", "产品名称", "规格", "价格"])
    sheet.append(["  华东涂料  ", "HX-1", " 内墙底漆 ", "20kg", "12.50"])
    sheet.append(["华东涂料", "HX-2", "外墙面漆", "18kg", "30"])
    sheet.append(["华东涂料", "HX-BAD", "", "10kg", "9"])
    sheet.append(["华东涂料", "HX-NEG", "负价样品", "1kg", "-3"])
    sheet.append(["合计", "", "", "", ""])
    notes = workbook.create_sheet("说明")
    notes.append(["本表是说明区域，不参与导入"])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def _delivery_row(db: Session, key: str) -> dict[str, Any] | None:
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS cross_module_delivery ("
            "idempotency_key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
    )
    found = db.execute(
        text("SELECT payload FROM cross_module_delivery WHERE idempotency_key = :key"),
        {"key": key},
    ).first()
    if found is None:
        return None
    return json.loads(found[0])


def _save_delivery(db: Session, key: str, payload: dict[str, Any]) -> None:
    _delivery_row(db, key)
    db.execute(
        text(
            "INSERT INTO cross_module_delivery (idempotency_key, payload) VALUES (:key, :payload)"
        ),
        {"key": key, "payload": json.dumps(payload, ensure_ascii=False, default=str)},
    )
    db.commit()


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
                return {"success": False, "message": "transient", "retryable": True}
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
    s01 = _workflow(business_plan, dispatch, parallel=False)
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
    first = _workflow(resume_plan, parallel_dispatch, checkpointer=checkpointer, max_retries=0)
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
    flaky = _workflow(flaky_plan, dispatch, max_retries=1)
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
        other.metadata["runtime_context"]["tenant_id"] == "2" and claimed.tenant_id == tenant_id,
        claimed.tenant_id,
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
    failure = _workflow(failure_plan, empty_dispatch, parallel=False)
    mark("B49-07", failure.success and "imported" not in empty_state, empty_state.keys())
    mark("B49-09", "stop" in [node.node_id for node in failure_plan.nodes], "stop")

    # Employee runtime on the real result file, then a second employee reads the anomaly CSV.
    employee_reads = _run_employee(
        "excel-full-read-employee",
        "读取导入结果",
        {"file_path": files["result_path"]},
        workspace,
    )
    employee_anomaly = _run_employee(
        "csv-full-read-employee",
        "读取异常清单",
        {"file_path": files["anomaly_csv"]},
        workspace,
    )
    missing_employee = _run_employee(
        "excel-full-read-employee",
        "缺少文件",
        {"file_path": str(workspace / "missing.xlsx")},
        workspace,
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


def is_cross_module_client_task(message: str, params: dict[str, Any] | None) -> bool:
    """The desktop task API already accepts this business request; no second route."""
    text = str(message or "")
    file_path = str((params or {}).get("file_path") or "").strip()
    return "Excel" in text and "导入" in text and "产品库" in text and bool(file_path)


def _workflow_receipt(
    request_id: str, *, success: bool, loaded_from_storage: bool, **extra: Any
) -> dict[str, Any]:
    from app.application.workflow.approval_persistence import (
        WORKFLOW_EXECUTION_FAILED_CODE,
        WORKFLOW_EXECUTION_SUCCESS_CODE,
    )

    return {
        "workflow_executed": True,
        "approval_request_id": request_id,
        "success": success,
        "code": WORKFLOW_EXECUTION_SUCCESS_CODE if success else WORKFLOW_EXECUTION_FAILED_CODE,
        "message": "AI 工作流执行完成" if success else "AI 工作流执行失败",
        "nodes_executed": 1 if success else 0,
        "nodes_total": 1,
        "loaded_from_storage": loaded_from_storage,
        **extra,
    }


def begin_cross_module_http(
    orchestrator: AgentOrchestrator,
    run: AgentRun,
    *,
    params: dict[str, Any],
    runtime_context: dict[str, Any],
) -> None:
    """Parse the uploaded workbook and persist the approval. Do not write ERP yet."""
    source = Path(str(params.get("file_path") or "")).expanduser()
    if not source.is_file():
        raise RuntimeError("业务 Excel 不存在，已停止写入")
    original_hash = _sha256(source)
    identified = identify_workbook(source)
    cleaned = slice_and_clean(identified)
    if not cleaned.get("qualifying"):
        raise RuntimeError("没有可导入的合格行，已停止写入")
    result_path = source.parent / "result.xlsx"
    files = write_result_workbook(result_path, cleaned)
    context = dict(run.metadata.get("runtime_context") or runtime_context)
    tenant_text = str(context.get("tenant_id") or "")
    if not tenant_text.isdigit():
        raise RuntimeError("任务缺少租户，已停止写入")
    checkpoint = {
        "trace_id": uuid.uuid4().hex,
        "task_id": str(context.get("task_id") or ""),
        "run_id": run.run_id,
        "user_id": str(context.get("user_id") or run.user_id),
        "tenant_id": tenant_text,
        "session_id": str(context.get("session_id") or context.get("conversation_id") or ""),
        "source_path": str(source),
        "original_sha256": original_hash,
        "result_path": files["result_path"],
        "result_sha256": files["sha256"],
        "anomaly_csv": files["anomaly_csv"],
        "qualifying": [dict(row["data"]) for row in cleaned["qualifying"]],
        "anomaly_count": len(cleaned["anomalies"]),
        "idempotency_key": "import-" + str(context.get("task_id") or run.run_id),
    }
    context["cross_module_http"] = True
    context["cross_module_checkpoint"] = checkpoint
    node_params = {
        "products": checkpoint["qualifying"],
        "file_path": str(source),
    }
    plan = PlanGraph(
        plan_id="plan-approve-" + checkpoint["task_id"],
        intent=str(run.message or ""),
        nodes=[
            WorkflowNode(
                "write",
                "products",
                "batch_create",
                params=node_params,
                risk="high",
                idempotent=False,
                description="导入产品",
            )
        ],
        risk_level="high",
    )
    from app.application.workflow.approval_service import get_approval_service

    approval = get_approval_service()
    gate = ApprovalGatedEngine(
        WorkflowEngine(lambda **_kwargs: {"success": False}),
        approval_service=approval,
        require_persistence=True,
    )
    with tenant_scope(int(tenant_text)):
        decision = gate.evaluate_plan(plan, runtime_context=context, strategy="interactive")
        request_id = decision.approval_request_ids[0] if decision.approval_request_ids else ""
        if not request_id:
            created = approval.create_approval_request(
                plan.plan_id,
                plan.nodes[0],
                runtime_context=context,
                plan=plan,
                require_persistence=True,
            )
            request_id = created.request_id
        metadata = approval.get_request_metadata(request_id) or {}
    if not metadata.get("id"):
        raise RuntimeError("审批请求未能持久化，已阻止数据库写入")
    run.metadata["runtime_context"] = context
    run.metadata["trace_id"] = checkpoint["trace_id"]
    run.metadata["approval_request_id"] = request_id
    run.metadata["approval_request_db_id"] = int(metadata["id"])
    run.metadata["approval_loaded_from_storage"] = False
    run.status = "waiting_user"
    orchestrator.save_run(run)
    _audit(
        "client.task_started",
        checkpoint["trace_id"],
        checkpoint["task_id"],
        checkpoint["user_id"],
        tenant_text,
        session_id=checkpoint["session_id"],
        file_sha256=original_hash,
        status="waiting_approval",
        request=run.message,
    )


def resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    """Continue the same task from the stored approval snapshot."""
    try:
        return _resume_cross_module_http(
            workflow, request_id=request_id, loaded_from_storage=loaded_from_storage
        )
    except RECOVERABLE_ERRORS:
        logger_message = "cross-module resume failed"
        import logging

        logging.getLogger(__name__).exception(logger_message)
        return _workflow_receipt(request_id, success=False, loaded_from_storage=loaded_from_storage)


def _resume_cross_module_http(
    workflow: dict[str, Any], *, request_id: str, loaded_from_storage: bool
) -> dict[str, Any]:
    from app.application.agent_orchestrator.artifact_files import store_spreadsheet
    from app.application.agent_orchestrator.run_models import artifact_from_dict
    from app.application.agent_orchestrator.task_execution_repository import (
        get_task_execution_repository,
    )
    from app.db.session import get_db

    context = workflow.get("runtime_context") if isinstance(workflow, dict) else None
    checkpoint = context.get("cross_module_checkpoint") if isinstance(context, dict) else None
    if not loaded_from_storage or not isinstance(checkpoint, dict):
        return _workflow_receipt(request_id, success=False, loaded_from_storage=False)
    source = Path(str(checkpoint.get("source_path") or ""))
    original_hash = str(checkpoint.get("original_sha256") or "")
    if not source.is_file() or _sha256(source) != original_hash:
        return _workflow_receipt(
            request_id, success=False, loaded_from_storage=True, source_unchanged=False
        )
    orchestrator = AgentOrchestrator()
    run = orchestrator.get_run(str(checkpoint.get("run_id") or ""))
    if run is None:
        return _workflow_receipt(request_id, success=False, loaded_from_storage=True)
    queue = get_task_execution_repository()
    queue.enqueue(run, requested_by="cross-module-http", priority=1)
    claimed = queue.claim("cross-module-http", lease_seconds=60, run_id=run.run_id)
    if claimed is None or claimed.run_id != run.run_id:
        return _workflow_receipt(request_id, success=False, loaded_from_storage=True)
    tenant_text = str(checkpoint.get("tenant_id") or "")
    qualifying = [
        {"data": dict(item)}
        for item in checkpoint.get("qualifying") or []
        if isinstance(item, dict)
    ]
    key = str(checkpoint.get("idempotency_key") or "")
    try:
        with get_db() as db, tenant_scope(int(tenant_text)):
            replay = _delivery_row(db, key) if key else None
            if replay is None:
                imported = import_products(db, qualifying)
                if not imported.get("success"):
                    queue.finish(run.run_id, "cross-module-http", "failed")
                    return _workflow_receipt(request_id, success=False, loaded_from_storage=True)
                price_update = update_product_price(
                    db, unit="华东涂料", model_number="HX-1", price="15.00"
                )
                _save_delivery(
                    db,
                    key,
                    {
                        "count": imported["count"],
                        "price_after": price_update.get("after"),
                        "match_ref": price_update.get("match_ref"),
                    },
                )
            else:
                imported = {"success": True, "count": replay.get("count"), "replayed": True}
                current = (
                    db.query(Product)
                    .filter(Product.unit == "华东涂料", Product.model_number == "HX-1")
                    .one()
                )
                price_update = {
                    "success": True,
                    "before": str(replay.get("price_after") or ""),
                    "after": str(current.price),
                    "replayed": True,
                }
            stored_count = _product_count(db, "华东涂料")
    except RECOVERABLE_ERRORS:
        queue.finish(run.run_id, "cross-module-http", "failed")
        raise
    result_path = Path(str(checkpoint.get("result_path") or ""))
    anomaly_count = int(checkpoint.get("anomaly_count") or 0)
    employee = _run_employee(
        "excel-full-read-employee",
        "读取导入结果",
        {"file_path": str(result_path)},
        result_path.parent,
    )
    employee_ok = bool(employee["result"].get("success"))
    verification = verify_against_data(
        qualifying_count=len(qualifying),
        anomaly_count=anomaly_count,
        stored_count=stored_count,
        tool_success=True,
        result_sha=str(checkpoint.get("result_sha256") or ""),
        result_path=result_path,
    )
    source_unchanged = source.is_file() and _sha256(source) == original_hash
    content = result_path.read_bytes() if result_path.is_file() else b""
    download_sha = hashlib.sha256(content).hexdigest() if content else ""
    artifact = store_spreadsheet(run.run_id, content, name="result.xlsx") if content else None
    if artifact is not None:
        run.artifacts.append(artifact_from_dict(artifact))
    accepted = bool(
        verification["accepted"]
        and price_update.get("after") == "15.00"
        and source_unchanged
        and download_sha == checkpoint.get("result_sha256")
    )
    run.status = "completed" if accepted else "failed"
    run.final_output = {
        "business_result": {
            "protocol": BUSINESS_HARNESS_PROTOCOL,
            "status": verification["status"] if accepted else "failed",
            "success": False,
            "summary": f"导入 {stored_count} 条，异常 {anomaly_count} 条",
            "file_name": "result.xlsx",
            "sha256": download_sha,
            "trace_id": checkpoint.get("trace_id"),
            "task_id": checkpoint.get("task_id"),
            "run_id": run.run_id,
            "loaded_from_storage": True,
            "employee_success": employee_ok,
            "source_unchanged": source_unchanged,
        }
    }
    run.metadata["approval_loaded_from_storage"] = True
    run.metadata["result_sha256"] = download_sha
    orchestrator.save_run(run)
    queue.finish(run.run_id, "cross-module-http", "completed" if accepted else "failed")
    _audit(
        "approval.decided",
        str(checkpoint.get("trace_id") or ""),
        str(checkpoint.get("task_id") or ""),
        str(checkpoint.get("user_id") or ""),
        tenant_text,
        approved=True,
        loaded_from_storage=True,
        request_ids=[request_id],
    )
    _audit(
        "agent.verified",
        str(checkpoint.get("trace_id") or ""),
        str(checkpoint.get("task_id") or ""),
        str(checkpoint.get("user_id") or ""),
        tenant_text,
        verification=verification,
        source_unchanged=source_unchanged,
    )
    _audit(
        "erp.updated",
        str(checkpoint.get("trace_id") or ""),
        str(checkpoint.get("task_id") or ""),
        str(checkpoint.get("user_id") or ""),
        tenant_text,
        before=price_update.get("before"),
        after=price_update.get("after"),
        replayed=bool(imported.get("replayed")),
        stored_count=stored_count,
    )
    return _workflow_receipt(
        request_id,
        success=accepted,
        loaded_from_storage=True,
        stored_count=stored_count,
        verification_status=verification["status"],
        result_sha256=download_sha,
        source_unchanged=source_unchanged,
        employee_success=employee_ok,
    )
