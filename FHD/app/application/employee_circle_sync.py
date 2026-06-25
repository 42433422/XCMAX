"""FHD 拉 MODstore 汇报流 → 投影成 ai_circle 员工动态（真实 loop 工作汇报）。

真相源：MODstore collab feed（``employee_collab_reporter`` 把 6 类 loop 产出写入的部门汇报线程）。
经 ``modstore_local_client`` 实时 HTTP 拉取，按 ``source_ref`` 幂等投影成 ``AiCirclePost``；
不依赖 MODstore→FHD 反向通道。best-effort：MODstore 不可达时静默跳过（交流圈降级为已有内容）。
节流：默认 45s 内最多同步一次（``/circle/posts`` 每次加载触发，但不会每次都打 MODstore）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.application import ai_circle_service
from app.application.modstore_local_client import modstore_get

logger = logging.getLogger(__name__)

_THREADS_PATH = "/api/admin/employee-autonomy/collab/threads"
_TITLE_PREFIX = "[员工交流圈]"
_SYNC_MIN_INTERVAL_SEC = 45.0
_last_sync: datetime | None = None


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


async def sync_modstore_reports(*, limit: int = 200, force: bool = False) -> dict[str, Any]:
    """拉 MODstore 部门汇报线程的消息，幂等投影成员工动态。返回新增/扫描计数。"""
    global _last_sync
    now = datetime.now(UTC)
    if (
        not force
        and _last_sync is not None
        and (now - _last_sync).total_seconds() < _SYNC_MIN_INTERVAL_SEC
    ):
        return {"ok": True, "skipped": True, "reason": "throttled"}
    _last_sync = now

    try:
        data = await modstore_get(_THREADS_PATH, query="limit=200")
    except Exception:  # noqa: BLE001 - best-effort，MODstore 不可达即跳过
        logger.warning("circle sync: list threads failed", exc_info=True)
        return {"ok": False, "synced": 0, "error": "threads_unreachable"}

    threads = data.get("items") if isinstance(data, dict) else None
    if not isinstance(threads, list):
        return {"ok": True, "synced": 0, "scanned": 0}

    synced = 0
    scanned = 0
    for t in threads:
        if not isinstance(t, dict) or not str(t.get("title") or "").startswith(_TITLE_PREFIX):
            continue
        tid = int(t.get("id") or 0)
        if tid <= 0:
            continue
        try:
            mdata = await modstore_get(
                f"{_THREADS_PATH}/{tid}/messages", query=f"limit={int(limit)}"
            )
        except Exception:  # noqa: BLE001 - best-effort，单线程失败不影响其余
            logger.warning("circle sync: messages failed tid=%s", tid, exc_info=True)
            continue
        msgs = mdata.get("items") if isinstance(mdata, dict) else None
        if not isinstance(msgs, list):
            continue
        for m in msgs:
            if not isinstance(m, dict):
                continue
            scanned += 1
            mid = int(m.get("id") or 0)
            sender = str(m.get("sender_employee_id") or "").strip()
            body = str(m.get("content") or "").strip()
            if mid <= 0 or not sender or not body:
                continue
            try:
                new_id = ai_circle_service.upsert_employee_post(
                    employee_id=sender,
                    author_name=sender,
                    body=body,
                    source_ref=f"modstore-collab:{mid}",
                    source_type="loop_report",
                    created_at=_parse_iso(m.get("created_at") or ""),
                )
                if new_id:
                    synced += 1
            except Exception:  # noqa: BLE001 - 单条失败不影响其余
                logger.warning("circle sync: upsert failed mid=%s", mid, exc_info=True)
    return {"ok": True, "synced": synced, "scanned": scanned}
