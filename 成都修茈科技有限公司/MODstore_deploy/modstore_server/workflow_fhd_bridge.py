"""按顺序调用 FHD ``/api/business/*`` 的轻量 HTTP 编排（与远期 NeuroBus 工作流适配并存）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _safe_json_response(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:4000]


def run_steps_on_fhd(
    base_url: str,
    steps: list[dict[str, Any]],
    *,
    timeout: float = 60.0,
    business_key: str | None = None,
) -> list[dict[str, Any]]:
    """``steps`` 每项支持 ``method``（默认 POST）、``path``（相对 ``/api/business/``）、``body``（可选 dict）。"""
    base = base_url.rstrip("/")
    headers: dict[str, str] = {}
    if (business_key or "").strip():
        headers["X-FHD-Business-Key"] = business_key.strip()

    results: list[dict[str, Any]] = []
    with httpx.Client(base_url=base, timeout=timeout, headers=headers) as client:
        for i, step in enumerate(steps):
            method = str(step.get("method") or "POST").strip().upper()
            path = str(step.get("path") or "").strip().lstrip("/")
            if not path:
                results.append({"step": i, "error": "missing path"})
                continue
            url = f"/api/business/{path}"
            body = step.get("body")
            try:
                r = client.request(method, url, json=body if isinstance(body, dict) else None)
                results.append(
                    {
                        "step": i,
                        "path": path,
                        "status_code": r.status_code,
                        "body": _safe_json_response(r),
                    }
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("workflow_fhd_bridge step %s failed: %s", i, e)
                results.append({"step": i, "path": path, "error": str(e)})
    return results
