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
        raise KellaiRequestError(
            detail if isinstance(detail, str) else "客来来拒绝了请求，请检查授权和连接状态",
            exc.code if 400 <= exc.code < 600 else 502,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise KellaiRequestError(
            "客来来暂不可达；发送结果可能未知，请查询原请求回执后再操作"
        ) from exc
    if not isinstance(payload, dict) or not payload.get("success") or "data" not in payload:
        raise KellaiRequestError("客来来响应无效，请查询原请求回执", 502)
    return payload
