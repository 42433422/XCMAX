"""Owner-authorized print handling for the legacy tool dispatcher."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def dispatch_legacy_print_payload(
    action: str,
    params: dict,
    *,
    json_response_fn,
    owner_user_id: int | None,
):
    _j = json_response_fn
    from app.services import get_printer_service

    svc = get_printer_service()
    if action == "view":
        return _j({"success": True, "redirect": "/console?view=print"})
    if action in ("list", "query"):
        return _j(svc.get_printers(), 200)
    if action == "print_label":
        result = svc.print_label(
            str(params.get("file_path") or "").strip(),
            params.get("printer_name"),
            int(params.get("copies") or 1),
        )
        return _j(result, 200)
    if action == "print_document":
        # This legacy dispatcher can be reached without the protected
        # FastAPI print route.  A local path must not be sufficient to
        # trigger a physical print: use the same owner-bound capability
        # issued alongside a generated shipment document.
        from app.application.print_authorization import (
            defer_document_print_capability,
            finish_document_print_capability,
            reserve_document_print_capability,
        )

        reservation = reserve_document_print_capability(
            params.get("print_token"),
            owner_user_id=owner_user_id,
            file_path=params.get("file_path"),
            order_id=params.get("order_id"),
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
            return _j(reservation, status_code)
        try:
            result = svc.print_document(
                str(reservation["file_path"]),
                params.get("printer_name"),
                bool(params.get("use_automation", False)),
            )
        except RECOVERABLE_ERRORS as exc:
            finish_document_print_capability(reservation, print_succeeded=False)
            return _j({"success": False, "message": f"打印失败：{exc}"}, 500)
        print_succeeded = bool(result.get("success"))
        print_completed = bool(result.get("print_completed", print_succeeded))
        receipt = None
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
                finish_document_print_capability(
                    reservation,
                    print_succeeded=True,
                    print_completed=False,
                )
                result["print_tracking_available"] = False
        else:
            receipt = finish_document_print_capability(
                reservation,
                print_succeeded=print_succeeded,
                print_completed=print_completed,
            )
        if result.get("success"):
            if receipt:
                result["post_print_receipt"] = receipt
        return _j(result, 200 if result.get("success") else 400)
    if action == "test":
        result = svc.test_printer(str(params.get("printer_name") or "").strip())
        return _j(result, 200)
    return _j({"success": True, "message": "标签打印"})


sync_module_functions(
    target=globals(),
    source_module="app.services.tools_payload_legacy",
    function_names=("dispatch_legacy_print_payload",),
)
