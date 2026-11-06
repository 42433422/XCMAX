"""C21–C30 网络与服务稳定性契约。

断线恢复不等于业务成功。已完成的结果保持完成；未完成的请求标为中断或失败；
有副作用的操作在结果未知时不得自动再执行。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.security.log_redaction import redact_log_text

FAILURE_NOTICES: dict[str, tuple[str, str]] = {
    "offline": ("当前网络已断开。请检查网络后重试。", "retry"),
    "server_down": ("服务暂时不可用。请稍后重试，无需重新登录。", "retry"),
    "token_expired": ("登录已过期，请重新登录。这不是网络故障。", "relogin"),
    "permission": ("当前账号没有权限。请联系管理员，不要当作网络错误重试。", "admin"),
    "timeout": ("请求超时，操作未成功。请重试；已提交的写入请先核对结果，勿重复提交。", "check_result"),
    "model_provider": ("模型服务暂时失败，本轮未成功。请稍后重试。", "retry"),
    "insufficient_balance": ("余额不足，操作未成功。请联系管理员充值后再试。", "admin"),
    "tool_failure": ("工具执行失败，未标记为成功。请查看任务状态后再决定是否重试。", "check_result"),
    "bad_tool_args": ("工具参数不正确，操作未执行。请修改后再试。", "retry"),
    "db_down": ("数据库暂时不可用，操作未成功。请联系管理员。", "admin"),
    "upload_failed": ("上传失败，文件未完成。请重试。", "retry"),
    "download_failed": ("下载失败，文件未完成。请重试。", "retry"),
    "backend_restart": ("服务正在重启。请稍后重试，无需重新登录。进行中的操作未成功。", "retry"),
    "interrupted": ("操作已中断，未标记为成功。请核对任务状态后再决定是否重试。", "check_result"),
}

OPERATION_TIMEOUT_S = {
    "health": 3,
    "erp_read": 10,
    "chat": 30,
    "tool": 30,
    "upload": 30,
    "download": 30,
}

_UNKNOWN_STATES = frozenset({"running", "unknown", "interrupted", "timeout"})


class DuplicateSideEffect(Exception):
    """同一幂等键已有未确认结果，拒绝再执行。"""

    def __init__(self, record: dict[str, Any]):
        self.record = record
        super().__init__("结果未知，请先核对服务端后再提交。该操作未标记为成功。")


def failure_payload(kind: str) -> dict[str, Any]:
    message, action = FAILURE_NOTICES[kind]
    return {"success": False, "error_code": kind, "message": message, "action": action}


class InFlightLedger:
    """记录进行中的工作。断线只打断未完成项，不把它们改成成功，也不重放已完成的副作用。"""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, dict[str, Any]] = {}

    def begin(
        self,
        task_id: str,
        *,
        side_effect: bool = False,
        idempotency_key: str | None = None,
        kind: str = "chat",
    ) -> dict[str, Any]:
        if idempotency_key:
            prior = self.by_key.get(idempotency_key)
            if prior and prior["state"] == "succeeded":
                return prior
            if prior and prior["state"] in _UNKNOWN_STATES:
                raise DuplicateSideEffect(prior)
        record = {
            "id": task_id,
            "state": "running",
            "success": False,
            "side_effect": side_effect,
            "key": idempotency_key,
            "kind": kind,
            "result": None,
        }
        self.tasks[task_id] = record
        if idempotency_key:
            self.by_key[idempotency_key] = record
        return record

    def complete(self, task_id: str, result: Any = None) -> dict[str, Any]:
        record = self.tasks[task_id]
        record["state"] = "succeeded"
        record["success"] = True
        record["result"] = result
        return record

    def fail(self, task_id: str, kind: str) -> dict[str, Any]:
        record = self.tasks[task_id]
        record["state"] = "failed"
        record["success"] = False
        record["error_code"] = kind
        return record

    def mark_unknown(self, task_id: str, kind: str = "timeout") -> dict[str, Any]:
        record = self.tasks[task_id]
        record["state"] = "unknown"
        record["success"] = False
        record["error_code"] = kind
        return record

    def interrupt_open(self, reason: str) -> list[str]:
        changed: list[str] = []
        for record in self.tasks.values():
            if record["state"] == "running":
                record["state"] = "interrupted"
                record["success"] = False
                record["error_code"] = reason
                changed.append(record["id"])
        return changed


class RefreshSingleFlight:
    """并发 401 只发起一次刷新。失败要求重新登录，不能变成无限 401 或网络错误。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wait: tuple[threading.Event, dict[str, Any]] | None = None

    def run(self, refresh: Callable[[], bool]) -> bool:
        with self._lock:
            if self._wait is None:
                done = threading.Event()
                box: dict[str, Any] = {}

                def work() -> None:
                    try:
                        box["ok"] = bool(refresh())
                    except Exception:  # noqa: BLE001 — 刷新回调的任何失败都按重新登录处理，不能当成网络成功。
                        box["ok"] = False
                    finally:
                        done.set()
                        with self._lock:
                            self._wait = None

                self._wait = (done, box)
                threading.Thread(target=work, daemon=True).start()
            done, box = self._wait
        if not done.wait(timeout=5):
            return False
        return bool(box.get("ok"))


@dataclass
class TraceLog:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def start(self, **fields: Any) -> dict[str, Any]:
        record = {"started": time.perf_counter(), **fields}
        self.rows.append(record)
        return record

    def finish(self, record: dict[str, Any], *, status: int, error_code: str = "") -> dict[str, Any]:
        record["status"] = status
        record["error_code"] = error_code
        record["duration_ms"] = round((time.perf_counter() - record["started"]) * 1000, 3)
        record["ended"] = True
        return record

    def render(self) -> str:
        lines = []
        for row in self.rows:
            lines.append(
                " ".join(
                    [
                        f"request_id={row.get('request_id', '')}",
                        f"status={row.get('status', '')}",
                        f"duration_ms={row.get('duration_ms', '')}",
                        f"error_code={row.get('error_code', '')}",
                        f"user={row.get('user', '')}",
                        f"tenant={row.get('tenant', '')}",
                        f"session_ref={row.get('session_ref', '')}",
                        f"task={row.get('task', '')}",
                        f"detail={row.get('detail', '')}",
                    ]
                )
            )
        return redact_log_text("\n".join(lines))


class SseHub:
    """加速时钟下的连接账本：心跳、闪断重连有上限，退出必须释放。"""

    def __init__(self, *, heartbeat_s: float = 15, max_reconnects: int = 8) -> None:
        self.heartbeat_s = heartbeat_s
        self.max_reconnects = max_reconnects
        self.conns: dict[str, dict[str, Any]] = {}

    def open(self, conn_id: str, now: float = 0) -> None:
        self.conns[conn_id] = {
            "opened": now,
            "last_beat": now,
            "reconnects": 0,
            "closed": False,
        }

    def heartbeat(self, conn_id: str, now: float) -> None:
        row = self.conns[conn_id]
        if row["closed"]:
            raise RuntimeError("closed connection")
        if now - row["last_beat"] > self.heartbeat_s * 4:
            raise RuntimeError("heartbeat stalled")
        row["last_beat"] = now

    def blip(self, conn_id: str, now: float) -> bool:
        row = self.conns[conn_id]
        if row["closed"] or row["reconnects"] >= self.max_reconnects:
            return False
        row["reconnects"] += 1
        row["last_beat"] = now
        return True

    def close(self, conn_id: str) -> None:
        self.conns[conn_id]["closed"] = True

    def live_count(self) -> int:
        return sum(1 for row in self.conns.values() if not row["closed"])


def timeout_outcome(operation: str, elapsed_s: float, *, hung: bool = False) -> dict[str, Any]:
    limit = OPERATION_TIMEOUT_S[operation]
    timed_out = hung or elapsed_s > limit
    if not timed_out:
        return {"success": True, "state": "completed", "limit_s": limit}
    return {"success": False, "state": "timeout", "limit_s": limit, "action": "check_result"}


class CapacityError(Exception):
    def __init__(self, lane: str):
        self.lane = lane
        super().__init__(f"lane {lane} queue is full")


class LanePool:
    """各通道独立并发。一条慢通道不能占住其他通道，队列有上限。"""

    def __init__(self, limits: dict[str, int]) -> None:
        self.limits = dict(limits)
        self.inflight = dict.fromkeys(limits, 0)
        self.queued = dict.fromkeys(limits, 0)
        self._cv = threading.Condition()

    def run(self, lane: str, fn: Callable[[], Any], *, queue_limit: int | None = None) -> Any:
        limit = self.limits[lane]
        qmax = limit if queue_limit is None else queue_limit
        with self._cv:
            if self.queued[lane] + self.inflight[lane] >= qmax:
                raise CapacityError(lane)
            self.queued[lane] += 1
            while self.inflight[lane] >= limit:
                self._cv.wait()
            self.queued[lane] -= 1
            self.inflight[lane] += 1
        try:
            return fn()
        finally:
            with self._cv:
                self.inflight[lane] -= 1
                self._cv.notify_all()


def lane_for_path(path: str) -> str:
    lowered = (path or "").lower()
    if "/api/tools" in lowered or "/api/skills" in lowered:
        return "tool"
    if "/sales" in lowered or "/erp" in lowered or "/purchase" in lowered:
        return "erp"
    if "/chat" in lowered or "/api/ai/" in lowered:
        return "chat"
    return ""


def format_http_trace_line(
    *,
    request_id: str,
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    error_code: str = "",
    tenant: str = "",
    user: str = "",
    task: str = "",
    session_ref: str = "",
    lane: str = "",
) -> str:
    safe_path = path.split("?", 1)[0]
    parts = [
        "http_trace",
        f"request_id={request_id}",
        f"method={method}",
        f"path={safe_path}",
        f"status={status}",
        f"duration_ms={round(duration_ms, 1)}",
    ]
    if error_code:
        parts.append(f"error_code={error_code}")
    if tenant:
        parts.append(f"tenant={tenant}")
    if user:
        parts.append(f"user={user}")
    if task:
        parts.append(f"task={task}")
    if session_ref:
        parts.append(f"session_ref={session_ref}")
    if lane:
        parts.append(f"lane={lane}")
    return redact_log_text(" ".join(parts))


def emit_current_lane(lane: str, *, status: int = 0, error_code: str = "") -> None:
    """把当前请求号写到对话、工具或 ERP 日志。没有请求上下文时直接跳过。"""
    try:
        import logging

        from app.infrastructure.request_context import get_current_request
        from app.middleware.request_id import ensure_request_id

        request = get_current_request()
        if request is None or not lane:
            return
        logging.getLogger("app.stability").info(
            format_http_trace_line(
                request_id=ensure_request_id(request),
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=0,
                error_code=error_code,
                lane=lane,
            )
        )
    except Exception:
        return


_EFFECT_LOCK = threading.Lock()
_EFFECT_LIVE: set[str] = set()


def effect_db_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    base = Path(os.environ.get("XCAGI_DATA_DIR") or ".")
    return base / "stability_effects.sqlite"


def _effect_conn(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(
        "create table if not exists effects ("
        "key text primary key, lane text, tenant text, state text, ref text, updated_at real)"
    )
    return conn


def effect_claim(key: str, lane: str, tenant: str, *, path: Path | None = None) -> dict[str, Any]:
    """占用一个副作用键。已成功的不执行；崩溃留下的 running 变成未知并不再执行。"""
    safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")[:80]
    if not safe:
        raise ValueError("idempotency key required")
    now = time.time()
    with _EFFECT_LOCK:
        conn = _effect_conn(effect_db_path(path))
        try:
            row = conn.execute("select state, ref from effects where key=?", (safe,)).fetchone()
            if safe in _EFFECT_LIVE:
                return {"key": safe, "state": "running", "execute": False, "duplicate": True, "ref": ""}
            if row is None:
                conn.execute(
                    "insert into effects(key, lane, tenant, state, ref, updated_at) values (?,?,?,?,?,?)",
                    (safe, lane, tenant, "running", "", now),
                )
                conn.commit()
                _EFFECT_LIVE.add(safe)
                return {"key": safe, "state": "running", "execute": True, "duplicate": False, "ref": ""}
            state, ref = row
            if state == "succeeded":
                return {"key": safe, "state": "succeeded", "execute": False, "duplicate": False, "ref": ref}
            if state == "running":
                conn.execute(
                    "update effects set state='unknown', updated_at=? where key=?",
                    (now, safe),
                )
                conn.commit()
                return {"key": safe, "state": "unknown", "execute": False, "duplicate": False, "ref": ref or ""}
            if state == "unknown":
                return {"key": safe, "state": "unknown", "execute": False, "duplicate": False, "ref": ref or ""}
            conn.execute(
                "update effects set state='running', lane=?, tenant=?, updated_at=? where key=?",
                (lane, tenant, now, safe),
            )
            conn.commit()
            _EFFECT_LIVE.add(safe)
            return {"key": safe, "state": "running", "execute": True, "duplicate": False, "ref": ""}
        finally:
            conn.close()


def effect_drop_process_memory() -> None:
    """模拟进程退出：内存中的进行中标记消失，库里的 running 留待下次占用时改成未知。"""
    with _EFFECT_LOCK:
        _EFFECT_LIVE.clear()


def effect_finish(key: str, state: str, ref: str = "", *, path: Path | None = None) -> None:
    safe = "".join(ch for ch in key if ch.isalnum() or ch in "-_")[:80]
    with _EFFECT_LOCK:
        _EFFECT_LIVE.discard(safe)
        conn = _effect_conn(effect_db_path(path))
        try:
            conn.execute(
                "update effects set state=?, ref=?, updated_at=? where key=?",
                (state, ref[:120], time.time(), safe),
            )
            conn.commit()
        finally:
            conn.close()
