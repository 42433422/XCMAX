"""File-backed coordination for daily scheduler pipelines."""

from __future__ import annotations

import json
import os
import time
import uuid
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
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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
    "write_scheduler_heartbeat",
]
