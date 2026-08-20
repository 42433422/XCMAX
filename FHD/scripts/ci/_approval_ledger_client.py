"""共享 approval ledger client：旁路写入后端 approval ledger。

供 CI 自愈脚本（ai_self_heal.py）、人工升级脚本（escalate_to_human.py）、
CVM 自治 watcher（cvm_autonomy_watcher.py）复用，避免三处重复实现 POST
`/api/ops/autonomy/actions/ingest` 的逻辑。

铁律：fail-open。任何异常（网络/超时/非 2xx/env 缺失）都只打 stderr 日志，
返回 None，绝不让 ledger 写入失败阻断主流程。
"""

from __future__ import annotations

import os
import sys
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    import httpx
except ImportError:  # pragma: no cover - 测试环境可能未装 httpx
    httpx = None  # type: ignore[assignment]


def post_to_approval_ledger(
    action: str,
    payload: dict,
    source: str = "runtime",
    action_id: str | None = None,
) -> dict | None:
    """旁路调用后端 `POST /api/ops/autonomy/actions/ingest` 写入待办。

    env 依赖：
    - `FHD_API_BASE_URL`：后端基址（如 `https://xiu-ci.com`），缺失 fail-open。
    - `AUTONOMY_WEBHOOK_TOKEN` 或 `MODSTORE_OPS_INGEST_TOKEN`：鉴权 token，
      任一存在即可；两者都缺失 fail-open。

    成功返回 response.json()（dict），失败返回 None。
    """
    base_url = os.environ.get("FHD_API_BASE_URL", "").strip()
    if not base_url:
        print(
            "[approval-ledger] FHD_API_BASE_URL missing, skip ledger write",
            file=sys.stderr,
        )
        return None

    token = (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()
    if not token:
        print(
            "[approval-ledger] autonomy token missing, skip ledger write",
            file=sys.stderr,
        )
        return None

    if httpx is None:
        print(
            "[approval-ledger] httpx unavailable, skip ledger write",
            file=sys.stderr,
        )
        return None

    url = f"{base_url.rstrip('/')}/api/ops/autonomy/actions/ingest"
    headers = {"X-Autonomy-Token": token, "Content-Type": "application/json"}
    body: dict[str, Any] = {
        "action": action,
        "payload": payload,
        "source": source,
    }
    if action_id:
        body["action_id"] = action_id

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=body)
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover - fail-open，覆盖网络/超时等
        print(f"[approval-ledger] http error: {exc!r}", file=sys.stderr)
        return None

    if resp.status_code < 200 or resp.status_code >= 300:
        print(
            f"[approval-ledger] non-2xx status={resp.status_code} body={resp.text[:500]}",
            file=sys.stderr,
        )
        return None

    try:
        data = resp.json()
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover - 后端返回非 JSON
        print(f"[approval-ledger] json decode error: {exc!r}", file=sys.stderr)
        return None

    if not isinstance(data, dict):
        print(
            f"[approval-ledger] unexpected response type: {type(data).__name__}",
            file=sys.stderr,
        )
        return None
    return data
