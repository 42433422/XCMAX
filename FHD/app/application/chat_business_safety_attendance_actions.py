"""Attendance export and print implementations with explicit dependencies."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from app.application.chat_business_safety import (
    _DB_NAME,
    BusinessActorIdentity,
    BusinessChatIntent,
    _new_receipt,
    _not_executed,
    _payload,
)


def handle_attendance_export(
    message: str,
    intent: BusinessChatIntent,
    *,
    actor: BusinessActorIdentity,
    attendance_rows: Callable[..., tuple[list[dict[str, Any]], dict[str, Any], str | None]],
    attendance_error_payload: Callable[..., dict[str, Any]],
    create_attendance_export: Callable[..., tuple[Any, str]],
) -> dict[str, Any]:
    rows, meta, error = attendance_rows(message, actor=actor)
    if error:
        return attendance_error_payload(intent, error, meta)
    if not rows:
        source = f"{_DB_NAME}:attendance_daily_records"
        return _not_executed(
            intent,
            "考勤表未生成：已查询真实考勤库，但指定范围没有记录。",
            reason="no_attendance_rows",
            source=source,
            details=meta,
        )
    try:
        output, relpath = create_attendance_export(rows, meta)
    except Exception:  # noqa: BLE001 - converted to a truthful receipt
        return _not_executed(
            intent,
            "考勤表未生成：文件写出失败。",
            reason="attendance_export_failed",
            source=f"{_DB_NAME}:attendance_daily_records",
            status="failed",
            details=meta,
        )
    url = f"/api/mod/taiyangniao-pro/attendance/download?relpath={quote(relpath)}"
    artifact = {
        "kind": "file",
        "filename": output.name,
        "path": str(output),
        "download_url": url,
        "size_bytes": output.stat().st_size,
    }
    receipt = _new_receipt(
        intent,
        status="completed",
        executed=True,
        verified=output.is_file() and output.stat().st_size > 0,
        source=f"{_DB_NAME}:attendance_daily_records",
        affected_rows=len(rows),
        artifacts=[artifact],
        details=meta,
    )
    text = (
        f"考勤表已根据真实记录生成，共 {len(rows)} 行。\n"
        f"[下载 {output.name}]({url})\n"
        f"导出回执：{receipt['receipt_id']}。"
    )
    return _payload(text, intent, receipt)


def handle_attendance_print(
    message: str,
    intent: BusinessChatIntent,
    *,
    actor: BusinessActorIdentity,
    attendance_rows: Callable[..., tuple[list[dict[str, Any]], dict[str, Any], str | None]],
    attendance_error_payload: Callable[..., dict[str, Any]],
    create_attendance_export: Callable[..., tuple[Any, str]],
    get_printer_service: Callable[[], Any],
) -> dict[str, Any]:
    rows, meta, error = attendance_rows(message, actor=actor)
    if error:
        return attendance_error_payload(intent, error, meta)
    if not rows:
        return _not_executed(
            intent,
            "打印未执行：指定范围没有可核验的考勤记录。",
            reason="no_attendance_rows",
            source=f"{_DB_NAME}:attendance_daily_records",
            details=meta,
        )
    try:
        service = get_printer_service()
        printers = service.get_printers()
    except Exception:  # noqa: BLE001
        return _not_executed(
            intent,
            "打印未执行：无法读取系统打印机状态。",
            reason="printer_status_failed",
            source="printer_service",
            status="failed",
        )
    count = (
        int(printers.get("count") or len(printers.get("printers") or []))
        if isinstance(printers, dict)
        else 0
    )
    if not isinstance(printers, dict) or not printers.get("success") or count <= 0:
        return _not_executed(
            intent,
            "打印未执行：当前没有可用打印机。请先在“考勤打印机”中连接并验证打印机。",
            reason="no_available_printer",
            source="printer_service",
            details={"printer_count": count},
        )
    try:
        output, relpath = create_attendance_export(rows, meta)
        result = service.print_document(str(output))
    except Exception:  # noqa: BLE001
        return _not_executed(
            intent,
            "打印未执行：考勤文件生成或提交打印失败。",
            reason="print_submit_failed",
            source="printer_service",
            status="failed",
        )
    if not isinstance(result, dict) or not result.get("success"):
        reason = (
            str((result or {}).get("message") or "printer_rejected")
            if isinstance(result, dict)
            else "printer_rejected"
        )
        return _not_executed(
            intent,
            f"打印未执行：打印服务未接受任务（{reason}）。",
            reason=reason,
            source="printer_service",
            status="failed",
        )
    url = f"/api/mod/taiyangniao-pro/attendance/download?relpath={quote(relpath)}"
    printer_name = str(result.get("printer") or result.get("printer_name") or "系统默认打印机")
    receipt = _new_receipt(
        intent,
        status="submitted",
        executed=True,
        verified=True,
        source="printer_service",
        affected_rows=len(rows),
        artifacts=[
            {
                "kind": "file",
                "filename": output.name,
                "path": str(output),
                "download_url": url,
                "size_bytes": output.stat().st_size,
            }
        ],
        details={**meta, "printer": printer_name, "backend_result": result},
    )
    text = (
        f"考勤表已提交到 {printer_name}，共 {len(rows)} 行。打印机是否实际出纸仍以设备状态为准。\n"
        f"打印回执：{receipt['receipt_id']}；[下载打印文件]({url})。"
    )
    return _payload(text, intent, receipt)
