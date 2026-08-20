"""XCmax 双向同步服务。

对外提供:
  record_change(entity_type, entity_id, operation, payload) — 记录变更并入 outbox
  push_outbox(remote_host, remote_port)  — 把本地 outbox 推送到远端
  pull_from_remote(remote_host, remote_port, since_cursor)  — 从远端拉取增量变更
  apply_inbox()  — 把 inbox 中的变更应用到本地业务数据库

支持的实体类型（entity_type）：
  personnel      人员档案
  department     部门
  attendance     考勤记录（shipment_records）
  approval       审批请求
  approval_flow  审批流程定义
  print_job      打印任务
  template       文档/打印模板
  model_config   模型服务配置
  ecosystem      智能生态配置
  workflow_employee  员工工作流节点
  account_entitlements 账号权益快照（管理员强制推送到企业端）
  im_message         IM 消息（im_messages）
  im_read_state      IM 已读游标（im_conversation_members.last_read_message_id）
"""

from __future__ import annotations

import http.cookiejar
import importlib
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_NODE_ID = os.environ.get("XCMAX_NODE_ID", "local")
_DEFAULT_URLOPEN = urllib.request.urlopen
_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _direct_cookie_opener() -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
    jar: http.cookiejar.CookieJar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(jar),
    )
    return opener, jar


def _csrf_token_from_jar(jar: http.cookiejar.CookieJar) -> str:
    for cookie in jar:
        if cookie.name == "csrf_token" and str(cookie.value or "").strip():
            return str(cookie.value)
    return ""


def _open_sync_request(
    opener: urllib.request.OpenerDirector,
    req: urllib.request.Request,
    *,
    timeout: float,
) -> Any:
    """Open requests through direct opener, unless a test monkeypatches urlopen."""
    if urllib.request.urlopen is not _DEFAULT_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)
    return opener.open(req, timeout=timeout)


def _prime_csrf_cookie(
    opener: urllib.request.OpenerDirector, jar: http.cookiejar.CookieJar, base_url: str
) -> str:
    try:
        req = urllib.request.Request(f"{base_url}/api/health", method="GET")
        with _open_sync_request(opener, req, timeout=10) as resp:
            resp.read(4096)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("prime sync csrf cookie failed: %s", exc)
    return _csrf_token_from_jar(jar)


def utc_now_ms() -> int:
    """UTC epoch 毫秒，供 LWW meta.updated_at_ms 使用。"""
    from datetime import UTC, datetime

    return int(datetime.now(UTC).timestamp() * 1000)


def _payload_updated_at_ms(payload: dict[str, Any]) -> int:
    meta = payload.get("meta") or {}
    return int(meta.get("updated_at_ms") or 0)


def _read_sync_meta(key: str) -> dict[str, Any]:
    import sqlite3 as _sqlite3

    from app.db.xcmax_sync import _ensure_schema, _resolve_db_path

    conn = _sqlite3.connect(str(_resolve_db_path()))
    _ensure_schema(conn)
    row = conn.execute("SELECT value FROM sync_meta WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return {}
    try:
        return cast("dict[str, Any]", json.loads(row[0] or "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}


def _write_sync_meta(key: str, value: dict[str, Any]) -> None:
    import sqlite3 as _sqlite3

    from app.db.xcmax_sync import _ensure_schema, _resolve_db_path

    conn = _sqlite3.connect(str(_resolve_db_path()))
    _ensure_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
        (key, json.dumps(value, ensure_ascii=False, default=str)),
    )
    conn.commit()
    conn.close()


# 公共变更记录入口（各业务路由均可调用）


def record_change(
    entity_type: str,
    entity_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    actor: str = "system",
    version: int = 1,
) -> int:
    """记录变更并自动写入 outbox，供各业务路由调用（非阻塞，失败不影响主流程）。

    使用示例（在 FastAPI 路由中）：
        from app.services.xcmax_sync_service import record_change
        record_change("attendance", str(record_id), "insert", {"employee": "张三", ...})
    """
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        return int(
            db.append_change(
                entity_type=entity_type,
                entity_id=str(entity_id),
                operation=operation,
                payload=payload,
                version=version,
                actor=actor,
                origin_node=_NODE_ID,
                enqueue_outbox=True,
            )
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("record_change failed (entity=%s id=%s): %s", entity_type, entity_id, exc)
        return -1


# 推送 outbox → 远端


def push_outbox(
    remote_host: str | None = None,
    remote_port: int | None = None,
) -> dict[str, Any]:
    """读取 pending outbox 条目，逐条 POST 到远端 /api/xcmax/sync/receive。"""
    from app.db.xcmax_sync import SyncDb

    host = remote_host or os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
    port = int(remote_port or os.environ.get("XCMAX_REMOTE_PORT", "9999"))
    base_url = f"http://{host}:{port}"

    db = SyncDb()
    pending = db.get_pending_outbox(limit=200)
    sent = failed = 0
    opener, cookie_jar = _direct_cookie_opener()
    csrf_token = _prime_csrf_cookie(opener, cookie_jar, base_url) if pending else ""

    for item in pending:
        outbox_id = item["id"]
        payload = {
            "entity_type": item["entity_type"],
            "entity_id": item["entity_id"],
            "operation": item["operation"],
            "payload": item.get("payload") or {},
            "origin_node": _NODE_ID,
        }
        try:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/xcmax/sync/receive",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    **({"X-CSRF-Token": csrf_token} if csrf_token else {}),
                },
                method="POST",
            )
            with _open_sync_request(opener, req, timeout=10) as resp:
                resp.read(4096)
            db.mark_outbox_sent(outbox_id)
            sent += 1
        except urllib.error.HTTPError as exc:
            err_msg = f"HTTP {exc.code}: {exc.reason}"
            logger.warning("outbox push item %s failed: %s", outbox_id, err_msg)
            db.mark_outbox_failed(outbox_id, err_msg, retry=exc.code >= 500)
            failed += 1
        except RECOVERABLE_ERRORS as exc:
            err_msg = str(exc)
            logger.warning("outbox push item %s failed: %s", outbox_id, err_msg)
            db.mark_outbox_failed(outbox_id, err_msg, retry=True)
            failed += 1

    return {"sent": sent, "failed": failed, "total_pending": len(pending)}


# ---------------------------------------------------------------------------
# 拉取远端变更 → inbox
# ---------------------------------------------------------------------------


def pull_from_remote(
    remote_host: str | None = None,
    remote_port: int | None = None,
    since_cursor: int | None = None,
) -> dict[str, Any]:
    """从远端拉取增量变更写入 inbox。"""
    from app.db.xcmax_sync import SyncDb

    host = remote_host or os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
    port = int(remote_port or os.environ.get("XCMAX_REMOTE_PORT", "9999"))

    db = SyncDb()
    status = db.get_status()
    cursor = since_cursor if since_cursor is not None else (status.get("remote_cursor") or 0)

    url = f"http://{host}:{port}/api/xcmax/sync/changes?since_cursor={cursor}&limit=200"
    try:
        req = urllib.request.Request(url, method="GET")
        with _open_sync_request(_DIRECT_HTTP_OPENER, req, timeout=10) as resp:
            body = json.loads(resp.read(1024 * 512).decode("utf-8", errors="replace"))
        changes = body.get("data") or []
        if changes:
            db.enqueue_inbox(changes, remote_cursor=int(changes[-1].get("id") or 0))
            db.update_remote_cursor(int(changes[-1].get("id") or 0))
        return {"pulled": len(changes), "since_cursor": cursor}
    except RECOVERABLE_ERRORS as exc:
        logger.warning("pull_from_remote failed: %s", exc)
        return {"pulled": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# 应用 inbox → 本地业务库
# ---------------------------------------------------------------------------

_ENTITY_APPLIERS: dict[str, Any] = {}


def register_entity_applier(entity_type: str):
    """装饰器：注册业务实体变更应用函数。"""

    def decorator(fn):
        _ENTITY_APPLIERS[entity_type] = fn
        return fn

    return decorator


_basic_appliers = importlib.import_module("app.services.xcmax_sync_basic_appliers")
_extended_appliers = importlib.import_module("app.services.xcmax_sync_extended_appliers")
_apply_personnel = _basic_appliers._apply_personnel
_apply_department = _basic_appliers._apply_department
_apply_attendance = _basic_appliers._apply_attendance
_apply_approval = _basic_appliers._apply_approval
_apply_approval_flow = _basic_appliers._apply_approval_flow
_apply_print_job = _basic_appliers._apply_print_job
_apply_template = _basic_appliers._apply_template
_apply_model_config = _extended_appliers._apply_model_config
_apply_ecosystem = _extended_appliers._apply_ecosystem
_apply_im_message = _extended_appliers._apply_im_message
_apply_im_read_state = _extended_appliers._apply_im_read_state
_apply_workflow_employee = _extended_appliers._apply_workflow_employee
_sync_payload_list = _extended_appliers._sync_payload_list
_apply_account_entitlements = _extended_appliers._apply_account_entitlements


from app.application.private_mod_delivery_sync import apply_private_mod_delivery

register_entity_applier("private_mod_delivery")(apply_private_mod_delivery)


def apply_inbox(limit: int = 200) -> dict[str, Any]:
    """幂等地把 inbox 中 pending 的变更应用到本地。"""
    import sqlite3

    from app.db.xcmax_sync import SyncDb

    db = SyncDb()
    try:
        db._resolve_db_path() if hasattr(db, "_resolve_db_path") else None
        from app.db.xcmax_sync import _resolve_db_path

        path = _resolve_db_path()
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, entity_type, entity_id, operation, payload_json FROM sync_inbox WHERE status='pending' LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
    except RECOVERABLE_ERRORS as exc:
        logger.warning("apply_inbox read failed: %s", exc)
        return {"applied": 0, "errors": 1}

    applied = errors = conflicts = 0
    for row in rows:
        inbox_id = row["id"]
        entity_type = row["entity_type"]
        try:
            payload = json.loads(row["payload_json"] or "{}")
            item = {
                "entity_type": entity_type,
                "entity_id": row["entity_id"],
                "operation": row["operation"],
                "payload": payload,
            }
            applier = _ENTITY_APPLIERS.get(entity_type)
            if applier:
                applier(item)
                db.mark_inbox_applied(inbox_id)
                applied += 1
            else:
                logger.debug("no applier for entity_type=%s, skipping", entity_type)
                db.mark_inbox_applied(inbox_id)
                applied += 1
        except RECOVERABLE_ERRORS as exc:
            db.mark_inbox_conflict(inbox_id, str(exc))
            conflicts += 1
            errors += 1

    return {"applied": applied, "conflicts": conflicts, "errors": errors}
