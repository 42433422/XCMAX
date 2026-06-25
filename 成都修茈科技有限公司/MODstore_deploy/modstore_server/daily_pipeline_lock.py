"""File-backed coordination for daily scheduler pipelines."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback is best effort only.
    fcntl = None  # type: ignore[assignment]


DEFAULT_RUNTIME_DIR = str(Path.home() / ".xcmax" / "modstore-daily")
DEFAULT_LOCK_NAME = "daily_pipeline.lock"
DEFAULT_HEARTBEAT_NAME = "scheduler_heartbeat.json"


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or DEFAULT_RUNTIME_DIR).expanduser()


def daily_pipeline_lock_path() -> Path:
    raw = os.environ.get("MODSTORE_DAILY_PIPELINE_LOCK_FILE")
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_LOCK_NAME


def scheduler_heartbeat_path() -> Path:
    raw = os.environ.get("MODSTORE_SCHEDULER_HEARTBEAT_FILE")
    return Path(raw).expanduser() if raw else _runtime_dir() / DEFAULT_HEARTBEAT_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: str = "1") -> bool:
    raw = (os.environ.get(name, default) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def daily_pipeline_lock_enabled() -> bool:
    return _env_bool("MODSTORE_DAILY_PIPELINE_LOCK_ENABLED", "1")


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def write_scheduler_heartbeat(*, job_count: Optional[int] = None) -> Dict[str, Any]:
    payload = {
        "job_count": job_count,
        "pid": os.getpid(),
        "schema_version": 1,
        "timestamp": _now_iso(),
        "timestamp_epoch": time.time(),
    }
    path = scheduler_heartbeat_path()
    _write_json_atomic(path, payload)
    payload["path"] = str(path)
    return payload


def scheduler_heartbeat_status(*, max_age_seconds: int = 600) -> Dict[str, Any]:
    path = scheduler_heartbeat_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "path": str(path), "reason": "heartbeat_missing"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(path), "reason": "heartbeat_unreadable"}
    try:
        age_seconds = max(0.0, time.time() - float(payload.get("timestamp_epoch") or 0))
    except (TypeError, ValueError):
        age_seconds = float("inf")
    return {
        "age_seconds": age_seconds,
        "heartbeat": payload,
        "ok": age_seconds <= max(1, int(max_age_seconds)),
        "path": str(path),
        "reason": "ok" if age_seconds <= max(1, int(max_age_seconds)) else "heartbeat_stale",
    }


# 日循环每 24h 跑一次,留一轮宽限(2 天)再判停摆,避免单次延迟误报。
DEFAULT_LOOP_MAX_SILENCE_SECONDS = 172800


def _loop_max_silence_seconds() -> int:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_MAX_SILENCE_SEC")
    try:
        return max(1, int(raw)) if raw else DEFAULT_LOOP_MAX_SILENCE_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_LOOP_MAX_SILENCE_SECONDS


def _parse_iso_epoch(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def self_maintenance_loop_liveness(
    last_activity_iso: Optional[str],
    *,
    max_silence_seconds: Optional[int] = None,
    now_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Pure staleness verdict for the self-maintenance loop.

    ``last_activity_iso`` 应取 ledger 中最近一次 **complete 或 skip** 的时间戳——skip
    也算"调度器有跳动"(进程活着、只是被门控跳过),只有 complete 与 skip 长期都没有
    才说明调度器真的停摆(生产曾因此停摆 12 天无人知)。无任何活动记录按 stale 处理。

    纯函数:不读时钟外部状态(``now_epoch`` 可注入),便于单测。供 ops 状态接口附加到
    响应里,外部探针/日志告警据此发现"调度器不活了"。
    """
    threshold = (
        max_silence_seconds if max_silence_seconds is not None else _loop_max_silence_seconds()
    )
    threshold = max(1, int(threshold))
    now = time.time() if now_epoch is None else float(now_epoch)
    last_epoch = _parse_iso_epoch(last_activity_iso)
    if last_epoch is None:
        return {
            "is_stale": True,
            "age_seconds": None,
            "last_activity": None,
            "threshold_seconds": threshold,
            "reason": "no_activity_recorded",
        }
    age = max(0.0, now - last_epoch)
    is_stale = age > threshold
    return {
        "is_stale": is_stale,
        "age_seconds": age,
        "last_activity": str(last_activity_iso),
        "threshold_seconds": threshold,
        "reason": "loop_stalled" if is_stale else "ok",
    }


@contextmanager
def acquire_daily_pipeline_lock(
    *,
    stage: str,
    timeout_seconds: float = 0.0,
) -> Iterator[Dict[str, Any]]:
    """Acquire a cross-process lock for the 08:00 daily business chain.

    The lock is intentionally shared by digest, vibe-line execution and
    release-train orchestration. Later stages wait for earlier stages instead of
    reading half-written digest state.
    """

    if not daily_pipeline_lock_enabled() or fcntl is None:
        yield {"acquired": True, "disabled": True, "stage": stage}
        return

    path = daily_pipeline_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.0, float(timeout_seconds or 0.0))
    fh = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    break
                time.sleep(1.0)

        if not acquired:
            yield {
                "acquired": False,
                "path": str(path),
                "reason": "daily_pipeline_lock_busy",
                "stage": stage,
                "timeout_seconds": timeout_seconds,
            }
            return

        payload = {
            "acquired_at": _now_iso(),
            "pid": os.getpid(),
            "schema_version": 1,
            "stage": stage,
        }
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        yield {"acquired": True, "path": str(path), "stage": stage}
    finally:
        if acquired:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        fh.close()


__all__ = [
    "acquire_daily_pipeline_lock",
    "daily_pipeline_lock_path",
    "scheduler_heartbeat_path",
    "scheduler_heartbeat_status",
    "self_maintenance_loop_liveness",
    "write_scheduler_heartbeat",
]
