"""XCmax 服务器后台 / 双向同步 服务端实现。

为本地并行实例（历史个人节点等）提供与 ``app/fastapi_routes/xcmax_admin.py`` 对称的
服务器端接口：

  GET  /api/xcmax/admin/modules        — 服务器侧已上架的 Mod / 员工包
  GET  /api/xcmax/admin/remote-status  — 自身存活与版本（供同名节点级联探测）
  GET  /api/xcmax/admin/daily-digests   — 每日摘要存档列表
  GET  /api/xcmax/admin/daily-digests/{id} — 单条摘要正文
  GET  /api/xcmax/admin/digest-identity — 与修茈市场管理端解锁同源的身份校验码摘要
  POST /api/xcmax/admin/loop/memory/evict — 手动驱逐 self-maintenance loop 中过期的 open_items（veto 通道）
  GET  /api/xcmax/sync/status          — 同步指针 / outbox / inbox 概览
  GET  /api/xcmax/sync/changes         — 服务器变更日志（供本地节点拉取）
  POST /api/xcmax/sync/receive         — 接收来自本地节点的变更（写入 inbox）
  POST /api/xcmax/sync/push            — （服务器端通常不需要主动 push，占位）
  POST /api/xcmax/sync/pull            — （同上）
  GET  /api/xcmax/sync/conflicts       — 冲突清单（与本地客户端同名）
  POST /api/xcmax/sync/conflicts/{id}/resolve — 冲突处理
  GET  /api/xcmax/sync/stream          — SSE 心跳（与本地 SSE 对称）

存储：使用与 ``modstore.db`` 同目录的独立 SQLite 文件 ``xcmax_sync.db``，
避免侵入 ORM 元数据。可由 ``XCMAX_SYNC_DB_PATH`` 环境变量覆盖。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse
from modstore_server import xcmax_admin_surface_routes as _surface_routes
from modstore_server import xcmax_admin_sync_routes as _sync_routes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])


def _resolve_admin_user(authorization: Optional[str] = Header(None)):
    """Admin auth dependency for the loop-memory evict veto endpoint.

    Lazily imports ``modstore_server.api.deps`` so the router module stays
    cheap to load and does not pull SQLAlchemy ORM mappings during router
    discovery. Mirrors the ``require_admin`` pattern used by
    ``/api/ops/self-maintenance/governance-review``.
    """

    from modstore_server.api.deps import get_current_user, require_admin

    user = get_current_user(authorization=authorization)
    return require_admin(user=user)


# ---------------------------------------------------------------------------
# 存储：独立 SQLite，避开 ORM 元数据；多 worker 下 WAL 模式即可够用
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()


def _resolve_sync_db_path() -> Path:
    raw = (os.environ.get("XCMAX_SYNC_DB_PATH") or "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
    else:
        try:
            from modstore_server.db.base import default_db_path

            p = default_db_path().parent / "xcmax_sync.db"
        except Exception:
            p = Path(__file__).resolve().parent / "xcmax_sync.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_resolve_sync_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema_once() -> None:
    """幂等建表 + WAL；多 worker 安全。"""
    with _db_lock:
        with _connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS xcmax_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    actor TEXT NOT NULL DEFAULT 'system',
                    origin_node TEXT NOT NULL DEFAULT 'server',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_xcmax_changes_entity
                    ON xcmax_changes(entity_type, entity_id);
                CREATE TABLE IF NOT EXISTS xcmax_inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    origin_node TEXT NOT NULL DEFAULT 'remote',
                    status TEXT NOT NULL DEFAULT 'pending',
                    conflict_note TEXT DEFAULT NULL,
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_xcmax_inbox_status
                    ON xcmax_inbox(status, id);
                CREATE TABLE IF NOT EXISTS xcmax_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.commit()


_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    try:
        _init_schema_once()
        _schema_ready = True
    except Exception:
        logger.exception("xcmax_sync schema init failed")


def _meta_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM xcmax_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO xcmax_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------------------
# 后端模块清单（来自 Mod 目录 + 员工包，作为服务器侧的「模块注册表」）
# ---------------------------------------------------------------------------

CORE_SERVER_MODULES: list[dict[str, Any]] = [
    {
        "module_id": "modstore-core",
        "display_name": "ModStore 核心",
        "route": "",
        "source": "core",
        "sync_scope": "system",
        "active": True,
        "version": "0.2.0",
    },
    {
        "module_id": "xcmax-sync",
        "display_name": "XCmax 双向同步",
        "route": "/api/xcmax/sync",
        "source": "core",
        "sync_scope": "system",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "agent-butler",
        "display_name": "数字管家",
        "route": "/api/agent/butler",
        "source": "core",
        "sync_scope": "none",
        "active": True,
        "version": "1.0",
    },
    {
        "module_id": "workflow",
        "display_name": "工作流编排",
        "route": "/api/workflow",
        "source": "core",
        "sync_scope": "workflow",
        "active": True,
        "version": "1.0",
    },
]


def _collect_catalog_modules() -> list[dict[str, Any]]:
    """从 ModStore catalog 读取已上架的包，转换为 XCmax 模块视图。"""
    rows: list[dict[str, Any]] = []
    try:
        from modstore_server.catalog_store import list_packages

        items, _ = list_packages(limit=500, offset=0)
        for it in items:
            pid = str(it.get("id") or "").strip()
            if not pid:
                continue
            artifact = str(it.get("artifact") or "mod").strip().lower()
            source = "employee" if artifact == "employee" else "remote"
            rows.append(
                {
                    "module_id": pid,
                    "display_name": str(it.get("name") or pid),
                    "route": "",
                    "source": source,
                    "sync_scope": "module_info",
                    "active": bool(it.get("status", "active") not in ("delisted", "draft")),
                    "version": str(it.get("version") or ""),
                }
            )
    except Exception as exc:
        logger.debug("xcmax modules: catalog_store unavailable: %s", exc)
    return rows


@router.get("/admin/modules", response_model=None)
async def list_modules() -> dict[str, Any]:
    """获取服务器模块注册表（核心 + ModStore 已上架 + 员工包）。"""
    modules: list[dict[str, Any]] = list(CORE_SERVER_MODULES)
    modules.extend(_collect_catalog_modules())
    return {"success": True, "data": modules, "total": len(modules)}


# ---------------------------------------------------------------------------
# 远端状态：从本进程角度报告自身存活，便于级联节点探测
# ---------------------------------------------------------------------------

_PROCESS_START_TS = time.time()


@router.get("/admin/remote-status", response_model=None)
async def remote_status() -> dict[str, Any]:
    try:
        from modstore_server.deploy_context import health_payload
    except Exception:
        health_payload = lambda: {}  # noqa: E731

    ctx = {}
    try:
        ctx = health_payload() or {}
    except Exception:
        ctx = {}

    return {
        "success": True,
        "data": {
            "reachable": True,
            "latency_ms": 0,
            "version": str(ctx.get("git_sha") or "0.2.0"),
            "deploy_time": datetime.fromtimestamp(_PROCESS_START_TS, tz=timezone.utc).isoformat(),
            "hostname": str(ctx.get("hostname") or ""),
            "deploy_tier": str(ctx.get("deploy_tier") or "local"),
        },
    }


# ---------------------------------------------------------------------------
# 调度器健康：watchdog（scheduler-watchdog.yml）每 10 分钟探一次。
# 关键判定：引擎运行、注册完整、必需任务无缺失且仍有排期。
# 任一不满足 → watchdog SSH 进 CVM 重启 modstore-scheduler.service。
# ---------------------------------------------------------------------------


@router.get("/scheduler/health", response_model=None)
async def scheduler_health() -> dict[str, Any]:
    """报告 APScheduler 运行状态 + 待执行 job 数。

    响应 watchdog 探测；当调度器卡死（实例占满 / 线程池耗尽）时，
    ``scheduler.running`` 仍可能为 True 但 ``next_run_time`` 全面停滞，
    因此同时输出每 job 的 ``next_run_time``，watchdog 可基于此判定是否停摆。
    """
    try:
        from modstore_server.workflow_scheduler import (
            _scheduler,
            scheduler_integrity_status,
            scheduler_runtime_health_status,
        )

        if _scheduler is None:
            return {
                "success": False,
                "ok": False,
                "data": {
                    "scheduler_started": False,
                    "scheduler_running": False,
                    "job_count": 0,
                    "pending_job_count": 0,
                    "jobs": [],
                    "reason": "scheduler not initialized (process not running background jobs?)",
                },
            }

        jobs_payload: list[dict[str, Any]] = []
        pending = 0
        try:
            for j in _scheduler.get_jobs():
                nrt = j.next_run_time
                if nrt is not None:
                    pending += 1
                jobs_payload.append(
                    {
                        "id": j.id,
                        "next_run_time": nrt.isoformat() if nrt else None,
                        "trigger": str(j.trigger),
                    }
                )
        except Exception:
            logger.exception("scheduler_health: get_jobs failed")

        running = bool(getattr(_scheduler, "running", False))
        integrity = scheduler_integrity_status()
        runtime_health = scheduler_runtime_health_status()
        healthy = bool(integrity["ok"]) and bool(runtime_health["ok"]) and pending > 0
        return {
            "success": True,
            "ok": healthy,
            "data": {
                "scheduler_started": True,
                "scheduler_running": running,
                "scheduler_healthy": healthy,
                "job_count": len(jobs_payload),
                "pending_job_count": pending,
                "registration_complete": integrity["registration_complete"],
                "required_job_count": integrity["required_job_count"],
                "missing_required_jobs": integrity["missing_required_jobs"],
                "startup_probe_failures": integrity["startup_probe_failures"],
                "runtime_healthy": runtime_health["ok"],
                "runtime_jobs": runtime_health["jobs"],
                "unhealthy_runtime_jobs": runtime_health["unhealthy_jobs"],
                "recovering_runtime_jobs": runtime_health["recovering_jobs"],
                "jobs": jobs_payload,
                "reported_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    except Exception as exc:
        logger.exception("scheduler_health endpoint failed")
        return {
            "success": False,
            "ok": False,
            "data": {"reason": str(exc)},
        }


# ---------------------------------------------------------------------------
# 同步状态 / 变更日志 / 接收
# ---------------------------------------------------------------------------


@router.post("/admin/loop/memory/evict", response_model=None)
async def xcmax_admin_loop_memory_evict(
    body: dict[str, Any] = Body(default_factory=dict),
    admin_user: Any = Depends(_resolve_admin_user),
):
    """Manually evict stale self-maintenance loop open_items (veto channel).

    Body (all optional):
      - ``note``: free-form reason captured in the governance audit record

    Triggers the same eviction rules as the automatic path:
      - failed_steps item with created_at > 24h AND retry_count >= 3
      - any item with created_at > 7d
    Evicted items are moved to ``evicted_items`` (max 100) and a
    ``loop_evicted`` governance audit record is appended.
    """

    try:
        from modstore_server.self_maintenance_loop_runner import evict_loop_memory_items

        result = evict_loop_memory_items(
            actor="manual",
            note=str(body.get("note") or ""),
            admin_user_id=getattr(admin_user, "id", None),
        )
        return {"success": True, "data": result}
    except Exception as exc:
        logger.warning("xcmax loop memory evict failed: %s", exc)
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=500,
        )


__all__ = ["router"]


router.routes.extend(_sync_routes.router.routes)
router.routes.extend(_surface_routes.router.routes)

_last_change_id = _sync_routes._last_change_id
_inbox_pending_count = _sync_routes._inbox_pending_count
_inbox_conflict_count = _sync_routes._inbox_conflict_count
sync_status = _sync_routes.sync_status
sync_changes = _sync_routes.sync_changes
sync_receive = _sync_routes.sync_receive
sync_push = _sync_routes.sync_push
sync_pull = _sync_routes.sync_pull
list_conflicts = _sync_routes.list_conflicts
resolve_conflict = _sync_routes.resolve_conflict
_sse_generator = _sync_routes._sse_generator
sync_stream = _sync_routes.sync_stream

_daily_digest_record_to_dict = _surface_routes._daily_digest_record_to_dict
xcmax_daily_digest_records = _surface_routes.xcmax_daily_digest_records
xcmax_daily_digest_record_detail = _surface_routes.xcmax_daily_digest_record_detail
xcmax_release_train = _surface_routes.xcmax_release_train
xcmax_digest_identity = _surface_routes.xcmax_digest_identity
xcmax_surface_audit_lane = _surface_routes.xcmax_surface_audit_lane
