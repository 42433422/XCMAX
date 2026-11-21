"""Fixed loopback transport shared by the product UI and approved Agent tools."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

_BASE = "http://127.0.0.1:8793/api/kellai/integrations/xcmax/"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class KellaiRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def request_kellai(
    path: str, connection: dict[str, Any], body: dict[str, Any] | None = None, *, opener=None
) -> dict[str, Any]:
    """Never retry a write: lost responses must be reconciled by its request ID."""
    receipt_id = (
        str((body or {}).get("client_request_id") or "")
        if path == "messages/send"
        else path.removeprefix("messages/requests/")
        if path.startswith("messages/requests/")
        else ""
    )
    request = urllib.request.Request(
        f"{_BASE}{path}",
        headers={
            "Authorization": f"Bearer {connection['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    try:
        with (opener or _OPENER.open)(request, timeout=30 if body is not None else 5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8"))
            detail = error.get("detail") or error.get("error")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("error")
        except (ValueError, OSError):
            detail = None
        if path == "messages/send" and receipt_id and exc.code == 409 and detail == "requires_desktop_execution":
            # A configuration change must not hide an earlier dispatch with
            # this ID. Read the ledger before declaring this request unsent.
            try:
                request_kellai(f"messages/requests/{receipt_id}", connection, opener=opener)
            except KellaiRequestError as lookup_error:
                if lookup_error.status_code != 404:
                    raise
            else:
                # This read does not prove the new POST has the original body.
                # Keep it a conflict and let the caller explicitly query the ID.
                raise KellaiRequestError("原请求已有发送账本，请查询原回执，不要变更内容复用请求号", 409) from exc
            return {
                "success": False,
                "data": {
                    "request_id": receipt_id,
                    "status": "requires_desktop_execution",
                    "success": False,
                    "persisted": False,
                    "error": "此渠道需要在客来来桌面端执行，当前请求未外发",
                },
            }
        raise KellaiRequestError(
            detail if isinstance(detail, str) else "客来来拒绝了请求，请检查授权和连接状态",
            exc.code if 400 <= exc.code < 600 else 502,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise KellaiRequestError(
            "客来来暂不可达；发送结果可能未知，请查询原请求回执后再操作"
        ) from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if receipt_id:
        # A valid failed/unknown receipt has success=false. Preserve its
        # outcome instead of converting a known rejection into a transport error.
        if (
            isinstance(data, dict)
            and data.get("request_id") == receipt_id
            and isinstance(data.get("status"), str)
            and data["status"] in {
                "sending", "unknown", "accepted", "delivered", "failed", "cancelled",
                "requires_desktop_execution", "rejected",
            }
        ):
            return payload
        raise KellaiRequestError("客来来回执与原请求不符，请查询原请求回执", 502)
    if not isinstance(payload, dict) or not payload.get("success") or "data" not in payload:
        raise KellaiRequestError("客来来响应无效，请查询原请求回执", 502)
    return payload
