"""共享管理端 IM 通知客户端：CI escalate / CVM watcher → 老板 IM。

旁路 POST ``/api/internal/im/employee-message``（与 notification_service 同契约）。

铁律：fail-open。任何异常（网络/超时/非 2xx/env 缺失）只打 stderr，返回 False，
绝不阻断 escalate 主流程。
"""

from __future__ import annotations

import os
import sys
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _internal_base() -> str:
    return (
        (
            os.environ.get("XCAGI_FHD_INTERNAL_URL")
            or os.environ.get("FHD_INTERNAL_BASE_URL")
            or os.environ.get("FHD_API_BASE_URL")
            or os.environ.get("XCAGI_API_BASE_URL")
            or ""
        )
        .strip()
        .rstrip("/")
    )


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


def _boss_user_id() -> int:
    raw = (
        os.environ.get("XCAGI_AUTONOMY_IM_BOSS_USER_ID")
        or os.environ.get("MODSTORE_BOSS_USER_ID")
        or "1"
    ).strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def notify_boss_im(
    text: str,
    *,
    employee_id: str = "ci-autonomy",
    display_name: str = "CI/CVM 自治",
    source: str = "runtime",
) -> bool:
    """把 escalate / 告警摘要推到管理端老板 IM（best-effort）。"""
    body = (text or "").strip()
    if not body:
        return False

    base = _internal_base()
    key = _internal_api_key()
    boss_id = _boss_user_id()
    if not base or not key or boss_id <= 0:
        print(
            f"[im-notify] skip ({source}): missing base/key/boss_user_id",
            file=sys.stderr,
        )
        return False
    if httpx is None:
        print(f"[im-notify] skip ({source}): httpx unavailable", file=sys.stderr)
        return False

    url = f"{base}/api/internal/im/employee-message"
    payload: dict[str, Any] = {
        "boss_user_id": boss_id,
        "employee_id": str(employee_id or "ci-autonomy"),
        "body": body[:4000],
        "display_name": str(display_name or employee_id or "CI/CVM 自治"),
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                url,
                headers={"X-Internal-Api-Key": key, "Content-Type": "application/json"},
                json=payload,
            )
        ok = 200 <= resp.status_code < 300
        if not ok:
            print(
                f"[im-notify] non-2xx ({source}): {resp.status_code}",
                file=sys.stderr,
            )
        return ok
    except Exception as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover - fail-open
        print(f"[im-notify] http error ({source}): {exc!r}", file=sys.stderr)
        return False
