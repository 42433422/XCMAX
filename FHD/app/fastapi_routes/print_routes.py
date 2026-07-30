"""打印 API（继承自归档 print 蓝图的端点契约）。"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from app.utils.agent_route_status import agent_route_http_status
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/print", tags=["print"])

_PRINT_CONFIRM_TTL_SECONDS = 300
_print_confirm_cache: dict[str, dict[str, Any]] = {}


def _cleanup_print_confirm_cache() -> None:
    now = time.time()
    expired = [
        token
        for token, payload in _print_confirm_cache.items()
        if float(payload.get("expires_at", 0.0)) <= now
    ]
    for token in expired:
        _print_confirm_cache.pop(token, None)


def _create_print_confirm_token(payload: dict[str, Any]) -> str:
    _cleanup_print_confirm_cache()
    token = uuid.uuid4().hex
    _print_confirm_cache[token] = {
        **payload,
        "expires_at": time.time() + _PRINT_CONFIRM_TTL_SECONDS,
    }
    return token


def _consume_print_confirm_token(token: str) -> dict[str, Any]:
    _cleanup_print_confirm_cache()
    return _print_confirm_cache.pop(token, {})


def _svc():
    # 仅打印相关接口应保持轻量，避免 `import app.services` 触发重型依赖/循环导入导致卡死。
    from app.application.facades.print_facade import printer_service

    return printer_service


def _print_agent_user_id(request: Request, payload: dict[str, Any]) -> str:
    return str(
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or payload.get("user_id")
        or payload.get("userId")
        or "print-route"
    ).strip()


def _authenticated_print_owner_id(request: Request) -> int | None:
    """Read only the middleware-authenticated owner for physical printing.

    Legacy callers still use header/body ids for harmless AgentRun attribution
    on older routes.  A document print is different: it spends a private,
    one-click capability and must never treat either client-controlled field
    as an authorization decision.
    """

    try:
        owner_user_id = int(getattr(request.state, "user_id", None) or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    return owner_user_id if owner_user_id > 0 else None


def _agent_node_output(run: Any, node_id: str) -> dict[str, Any]:
    final_output = getattr(run, "final_output", None)
    node_outputs = dict((final_output or {}).get("node_outputs") or {})
    output = dict(node_outputs.get(node_id) or {})
    if not output:
        for step in getattr(run, "steps", []) or []:
            if str(getattr(step, "node_id", "")) == node_id:
                output = dict(getattr(step, "output", {}) or {})
                break
    if not output:
        output = {"success": getattr(run, "status", "") == "completed"}
    if not output.get("success") and getattr(run, "error", "") and not output.get("message"):
        output["message"] = getattr(run, "error", "")
    run_id = str(getattr(run, "run_id", "") or "")
    if run_id:
        output["run_id"] = run_id
        output["agent_run_id"] = run_id
    output["agent_status"] = str(getattr(run, "status", "") or "")
    return output


def _print_agent_status_code(result: dict[str, Any], *, failure_status: int = 400) -> int:
    return agent_route_http_status(result, failure_status=failure_status)


def _run_print_agent(
    *,
    request: Request,
    action: str,
    params: dict[str, Any],
    route_path: str,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any]:
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode
    from app.application.workflow_registry_app import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    action_meta = dict((registry.get("print") or {}).get("actions") or {}).get(action)
    if not isinstance(action_meta, dict):
        return {
            "success": False,
            "message": f"未注册的 print 动作: {action}",
            "agent_status": "failed",
        }

    node_id = f"print_{action}"
    user_id = (
        str(authenticated_owner_user_id)
        if authenticated_owner_user_id is not None
        else _print_agent_user_id(request, params)
    )
    plan = PlanGraph(
        plan_id=node_id,
        intent=node_id,
        todo_steps=[f"通过 AgentOrchestrator 执行 print.{action}"],
        nodes=[
            WorkflowNode(
                node_id=node_id,
                tool_id="print",
                action=action,
                params=dict(params or {}),
                risk=str(action_meta.get("risk") or "medium"),
                idempotent=bool(action_meta.get("idempotent", False)),
                description=f"Execute print.{action} through the unified Agent runtime.",
            )
        ],
        risk_level=str(action_meta.get("risk") or "medium"),
        metadata={"source": "print_route", "route": route_path},
    )
    runtime_context = {
        "source": "print_route",
        "route": route_path,
        "request_path": str(request.url.path),
        "user_id": user_id,
        "route_confirmed": True,
        "service_source": "fastapi_print_route",
    }
    orchestrator = AgentOrchestrator()
    run = orchestrator.start_run_from_plan(
        user_id=user_id,
        message=str(params.get("message") or f"Print {action}"),
        plan=plan,
        runtime_context=runtime_context,
    )
    if run.status in {"waiting_user", "running"}:
        continued = orchestrator.continue_run(
            run.run_id,
            approved_by=user_id or "print-route",
            approved_step_id=node_id,
            runtime_context=runtime_context,
        )
        if continued is not None:
            run = continued
    return _agent_node_output(run, node_id)


@router.get("/printers")
def get_printers():
    try:
        result = _svc().get_printers()
        return JSONResponse(result)
    except RECOVERABLE_ERRORS as e:
        logger.error("获取打印机列表失败: %s", e, exc_info=True)
        return JSONResponse(
            {
                "success": False,
                "message": f"获取打印机列表失败: {str(e)}",
                "printers": [],
            },
            status_code=500,
        )


@router.get("/printer-selection")
def get_printer_selection():
    try:
        selection = _svc().get_printer_selection()
        return JSONResponse({"success": True, "selection": selection})
    except RECOVERABLE_ERRORS as e:
        logger.error("获取打印机选择失败: %s", e, exc_info=True)
        return JSONResponse(
            {"success": False, "message": f"获取打印机选择失败: {str(e)}"},
            status_code=500,
        )


@router.put("/printer-selection")
def save_printer_selection(
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
):
    try:
        result = _run_print_agent(
            request=request,
            action="save_printer_selection",
            params={
                "document_printer": data.get("document_printer"),
                "label_printer": data.get("label_printer"),
            },
            route_path="/api/print/printer-selection",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS as e:
        logger.error("保存打印机选择失败: %s", e, exc_info=True)
        return JSONResponse(
            {"success": False, "message": f"保存打印机选择失败: {str(e)}"},
            status_code=500,
        )


@router.get("/default")
def get_default_printer():
    try:
        result = _svc().get_default_printer()
        return JSONResponse(result)
    except RECOVERABLE_ERRORS as e:
        logger.error("获取默认打印机失败: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/document")
def print_document(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    reservation: dict[str, Any] | None = None
    try:
        file_path = data.get("file_path", "")
        printer_name = data.get("printer_name")
        use_automation = data.get("use_automation", False)
        print_token = data.get("print_token")
        order_id = data.get("order_id")
        if not file_path:
            return JSONResponse({"success": False, "message": "文件路径不能为空"}, status_code=400)
        if not os.path.exists(file_path):
            return JSONResponse(
                {"success": False, "message": f"文件不存在: {file_path}"}, status_code=400
            )
        from app.application.print_authorization import (
            defer_document_print_capability,
            finish_document_print_capability,
            reserve_document_print_capability,
        )

        owner_user_id = _authenticated_print_owner_id(request)
        reservation = reserve_document_print_capability(
            print_token,
            owner_user_id=owner_user_id,
            file_path=file_path,
            order_id=order_id,
        )
        if not reservation.get("success"):
            error_code = str(reservation.get("error_code") or "")
            status_code = (
                403
                if error_code
                in {
                    "PRINT_AUTH_REQUIRED",
                    "PRINT_CONFIRMATION_OWNER_MISMATCH",
                }
                else 409
            )
            return JSONResponse(reservation, status_code=status_code)
        result = _run_print_agent(
            request=request,
            action="print_document",
            params={
                "file_path": str(reservation["file_path"]),
                "printer_name": printer_name,
                "use_automation": use_automation,
            },
            route_path="/api/print/document",
            authenticated_owner_user_id=owner_user_id,
        )
        print_succeeded = bool(result.get("success"))
        # Older/Windows print adapters report only a success boolean and keep
        # their historical behaviour.  macOS CUPS adapters additionally report
        # physical completion after the bounded IPP monitor.
        print_completed = bool(result.get("print_completed", print_succeeded))
        result.setdefault("print_completed", print_completed)
        result.setdefault(
            "print_state",
            "completed" if print_completed else ("queued" if print_succeeded else "failed"),
        )
        post_print_receipt = None
        pending_job: dict[str, Any] | None = None
        if print_succeeded and not print_completed:
            pending_job = defer_document_print_capability(
                reservation,
                printer_name=result.get("printer"),
                job_id=result.get("job_id"),
            )
            if pending_job.get("success"):
                result["print_job_token"] = pending_job["print_job_token"]
                result["print_tracking_available"] = bool(pending_job.get("tracking_available"))
            else:
                # The operating system already owns a job, so never release
                # the one-click capability for a duplicate submission.  This
                # fallback is deliberately visible and requires regenerating
                # a fresh document if CUPS cannot provide a job identifier.
                finish_document_print_capability(
                    reservation,
                    print_succeeded=True,
                    print_completed=False,
                )
                result["print_tracking_available"] = False
                result["message"] = (
                    "打印任务已提交，但无法追踪 macOS CUPS 状态；"
                    "请核验打印机后重新生成发货单，勿重复提交当前任务"
                )
        else:
            post_print_receipt = finish_document_print_capability(
                reservation,
                print_succeeded=print_succeeded,
                print_completed=print_completed,
            )
        reservation = None
        if result.get("success"):
            if post_print_receipt:
                result["post_print_receipt"] = post_print_receipt
            result["printed_file_path"] = str(data.get("file_path") or "")
            result["printed_order_id"] = order_id
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS as e:
        if reservation and reservation.get("success"):
            from app.application.print_authorization import finish_document_print_capability

            finish_document_print_capability(reservation, print_succeeded=False)
        logger.error("打印文档失败: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": f"打印失败: {str(e)}"}, status_code=500)


@router.get("/jobs/{print_job_token}")
def get_document_print_job_status(request: Request, print_job_token: str):
    """Owner-bound, read-only reconciliation for a queued CUPS job.

    The initial document endpoint never turns an ``lp`` acknowledgement into a
    shipment receipt.  This route queries the job's IPP state with trusted
    tracker metadata and issues the receipt only when CUPS reports completed.
    It never resubmits, cancels, or otherwise changes a physical print job.
    """

    from app.application.print_authorization import (
        get_pending_document_print_job,
        settle_pending_document_print_job,
    )

    owner_user_id = _authenticated_print_owner_id(request)
    tracked = get_pending_document_print_job(
        print_job_token,
        owner_user_id=owner_user_id,
    )
    if not tracked.get("success"):
        error_code = str(tracked.get("error_code") or "")
        status_code = (
            403
            if error_code
            in {
                "PRINT_AUTH_REQUIRED",
                "PRINT_PENDING_TRACKER_OWNER_MISMATCH",
            }
            else 404
        )
        return JSONResponse(tracked, status_code=status_code)

    existing_state = str(tracked.get("state") or "pending")
    if existing_state == "completed":
        return JSONResponse(
            {
                "success": True,
                "print_completed": True,
                "print_state": "completed",
                "post_print_receipt": str(tracked.get("post_print_receipt") or ""),
                "message": "macOS CUPS 已确认发货单打印完成",
            }
        )
    if existing_state == "aborted":
        return JSONResponse(
            {
                "success": False,
                "print_completed": False,
                "print_state": "aborted",
                "error_code": "CUPS_JOB_ABORTED",
                "message": "macOS CUPS 已确认打印任务中止",
            }
        )
    if not bool(tracked.get("tracking_available")):
        return JSONResponse(
            {
                "success": False,
                "print_completed": False,
                "print_state": "unknown",
                "error_code": "CUPS_JOB_TRACKING_UNAVAILABLE",
                "message": "该任务已提交但未获得可追踪的 CUPS 作业号，请核验后重新生成发货单",
            }
        )

    observed = _svc().get_document_print_job_status(
        str(tracked.get("printer_name") or ""),
        str(tracked.get("job_id") or ""),
    )
    observed_state = str(observed.get("state") or "pending")
    settled = settle_pending_document_print_job(
        print_job_token,
        owner_user_id=owner_user_id,
        state=observed_state,
        reason=observed.get("reason"),
    )
    if not settled.get("success") and str(settled.get("state") or "") != "aborted":
        error_code = str(settled.get("error_code") or "")
        status_code = 403 if error_code == "PRINT_PENDING_TRACKER_OWNER_MISMATCH" else 404
        return JSONResponse(settled, status_code=status_code)

    settled_state = str(settled.get("state") or observed_state or "pending")
    if settled_state == "completed":
        return JSONResponse(
            {
                "success": True,
                "print_completed": True,
                "print_state": "completed",
                "post_print_receipt": str(settled.get("post_print_receipt") or ""),
                "message": "macOS CUPS 已确认发货单打印完成",
            }
        )
    if settled_state == "aborted":
        reason = str(settled.get("reason") or observed.get("reason") or "").strip()
        return JSONResponse(
            {
                "success": False,
                "print_completed": False,
                "print_state": "aborted",
                "error_code": "CUPS_JOB_ABORTED",
                "message": "macOS CUPS 已确认打印任务中止" + (f"（{reason}）" if reason else ""),
            }
        )
    return JSONResponse(
        {
            "success": True,
            "print_completed": False,
            "print_state": "pending",
            "message": "macOS CUPS 正在等待打印机完成，尚未标记为已打印",
        }
    )


@router.post("/label")
def print_label(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        file_path = data.get("file_path", "")
        printer_name = data.get("printer_name")
        copies = data.get("copies", 1)
        require_confirm = bool(data.get("require_confirm", True))
        confirm_token = str(data.get("confirm_token") or "").strip()
        confirm_action = str(data.get("confirm_action") or "").strip().lower()
        try:
            copies = int(copies)
        except RECOVERABLE_ERRORS:
            copies = 0
        if not file_path:
            return JSONResponse({"success": False, "message": "文件路径不能为空"}, status_code=400)
        if not os.path.exists(file_path):
            return JSONResponse(
                {"success": False, "message": f"文件不存在: {file_path}"}, status_code=400
            )
        if copies < 1 or copies > 100:
            return JSONResponse(
                {"success": False, "message": "打印份数必须在1-100之间"}, status_code=400
            )

        service = _svc()
        if require_confirm:
            if confirm_action == "cancel":
                if confirm_token:
                    _consume_print_confirm_token(confirm_token)
                return JSONResponse(
                    {"success": True, "status": "print_cancelled", "message": "已取消打印"},
                    status_code=200,
                )
            if not confirm_token:
                resolved_printer = printer_name or service.get_label_printer()
                token = _create_print_confirm_token(
                    {
                        "file_path": file_path,
                        "printer_name": resolved_printer,
                        "copies": copies,
                    }
                )
                return JSONResponse(
                    {
                        "success": True,
                        "status": "print_confirm_required",
                        "require_confirm": True,
                        "confirm_token": token,
                        "confirm_prompt": (
                            f"已准备打印 {copies} 份标签，是否立即打印到【{resolved_printer or '自动选择打印机'}】？"
                        ),
                        "preview": {
                            "file_path": file_path,
                            "label_count": copies,
                            "printer": resolved_printer,
                        },
                        "message": "已生成标签，等待打印确认",
                    },
                    status_code=200,
                )
            token_payload = _consume_print_confirm_token(confirm_token)
            if not token_payload:
                return JSONResponse(
                    {
                        "success": False,
                        "status": "print_confirm_required",
                        "error_code": "print_confirm_required",
                        "message": "打印确认已过期或无效，请重新发起打印请求",
                    },
                    status_code=400,
                )
            file_path = str(token_payload.get("file_path") or file_path)
            copies = int(token_payload.get("copies") or copies)
            printer_name = token_payload.get("printer_name") or printer_name

        result = _run_print_agent(
            request=request,
            action="print_label",
            params={
                "file_path": str(file_path),
                "printer_name": printer_name,
                "copies": copies,
            },
            route_path="/api/print/label",
        )
        if isinstance(result, dict):
            result.setdefault("status", "printed")
            result.setdefault("require_confirm", False)
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS as e:
        logger.error("打印标签失败: %s", e, exc_info=True)
        return JSONResponse(
            {"success": False, "message": f"打印标签失败: {str(e)}"}, status_code=500
        )


@router.post("/test")
def test_printer_post(request: Request, data: dict[str, Any] = Body(default_factory=dict)):
    try:
        printer_name = data.get("printer_name", "")
        if not printer_name:
            return JSONResponse(
                {"success": False, "message": "打印机名称不能为空"}, status_code=400
            )
        result = _run_print_agent(
            request=request,
            action="test",
            params={"printer_name": str(printer_name)},
            route_path="/api/print/test",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS as e:
        logger.error("测试打印机失败: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/validate")
def validate_printer_separation():
    try:
        result = _svc().validate_printer_separation()
        return JSONResponse({"success": True, **result})
    except RECOVERABLE_ERRORS as e:
        logger.error("验证打印机分离失败: %s", e, exc_info=True)
        return JSONResponse(
            {"success": False, "valid": False, "error": str(e)},
            status_code=500,
        )


@router.get("/document-printer")
def get_document_printer():
    try:
        printer = _svc().get_document_printer()
        if printer:
            return JSONResponse({"success": True, "printer": printer})
        return JSONResponse({"success": False, "message": "未找到发货单打印机"})
    except RECOVERABLE_ERRORS as e:
        logger.error("获取发货单打印机失败: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/label-printer")
def get_label_printer():
    try:
        printer = _svc().get_label_printer()
        if printer:
            return JSONResponse({"success": True, "printer": printer})
        return JSONResponse({"success": False, "message": "未找到标签打印机"})
    except RECOVERABLE_ERRORS as e:
        logger.error("获取标签打印机失败: %s", e)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.get("/test")
def test_print_service_get():
    return JSONResponse(
        {
            "success": True,
            "message": "打印服务运行正常",
        }
    )


@router.post("/workflow/label-print/dispatch")
def workflow_label_print_dispatch(
    request: Request,
    data: dict[str, Any] = Body(default_factory=dict),
):
    """工作流标签打印调度接口——幂等，同一 idempotency_key 重复调用仅执行一次打印。"""
    idempotency_key = str(data.get("idempotency_key") or "").strip()
    model_number = str(data.get("model_number") or "").strip()
    quantity = max(1, min(100, int(data.get("quantity") or 1)))

    if not model_number:
        return JSONResponse({"success": False, "message": "model_number 不能为空"}, status_code=400)

    # 检查幂等缓存（5 分钟 TTL，与打印确认 token 同机制）
    if idempotency_key:
        cached = _print_confirm_cache.get(f"wf_lp:{idempotency_key}")
        if cached and float(cached.get("expires_at", 0)) > time.time():
            return JSONResponse(
                {"success": True, "message": "已在幂等窗口内执行过，跳过重复打印", "skipped": True},
                status_code=200,
            )
        # 写入幂等标记
        _print_confirm_cache[f"wf_lp:{idempotency_key}"] = {
            "model_number": model_number,
            "expires_at": time.time() + _PRINT_CONFIRM_TTL_SECONDS,
        }

    try:
        result = _run_print_agent(
            request=request,
            action="workflow_label_dispatch",
            params={
                "model_number": model_number,
                "quantity": quantity,
                "idempotency_key": idempotency_key,
            },
            route_path="/api/print/workflow/label-print/dispatch",
        )
        return JSONResponse(result, status_code=_print_agent_status_code(result))
    except RECOVERABLE_ERRORS as e:
        logger.error("workflow_label_print_dispatch 失败: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": f"打印失败: {e}"}, status_code=500)


@router.get("/list_labels")
def list_labels(limit: int = Query(default=2, ge=1, le=20)):
    try:
        from app.utils.path_utils import get_resource_path

        labels_dir = get_resource_path("ai_assistant", "商标导出")
        if not os.path.isdir(labels_dir):
            return JSONResponse(
                {
                    "success": True,
                    "labels": [],
                    "message": "商标导出目录不存在",
                }
            )

        image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}
        labels: list[dict[str, str]] = []

        for filename in os.listdir(labels_dir):
            ext = os.path.splitext(filename.lower())[1]
            if ext not in image_extensions:
                continue
            file_path = os.path.join(labels_dir, filename)
            if not os.path.isfile(file_path):
                continue
            match = re.match(r"(.+?)_?第？?(\d+)?项？\.png", filename, re.IGNORECASE)
            order_number = match.group(1) if match else os.path.splitext(filename)[0]
            label_number = match.group(2) if match and match.group(2) else "1"
            labels.append(
                {
                    "filename": filename,
                    "order_number": order_number.strip() if order_number else "",
                    "label_number": label_number.strip() if label_number else "1",
                }
            )

        labels.sort(key=lambda x: x.get("filename", ""), reverse=True)
        labels = labels[:limit]
        return JSONResponse({"success": True, "labels": labels})
    except RECOVERABLE_ERRORS as e:
        logger.error("获取标签列表失败: %s", e, exc_info=True)
        return JSONResponse({"success": False, "labels": [], "message": str(e)}, status_code=500)


@router.get("/label/{filename}")
def serve_label_image(filename: str):
    try:
        from app.utils.path_utils import get_resource_path

        labels_dir = get_resource_path("ai_assistant", "商标导出")
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(labels_dir, safe_filename)
        if not os.path.exists(file_path):
            logger.warning("标签文件不存在: %s", file_path)
            return JSONResponse({"success": False, "message": "文件不存在"}, status_code=404)
        return FileResponse(file_path, media_type="image/png")
    except RECOVERABLE_ERRORS as e:
        logger.error("获取标签图片失败: %s", e, exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
