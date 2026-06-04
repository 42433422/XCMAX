"""服务端被动轮询调度：不依赖浏览器页面保持打开。"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _server_poll_enabled() -> bool:
    return os.environ.get("XCAGI_PASSIVE_SERVER_POLL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _tick_seconds() -> float:
    try:
        return max(3.0, min(30.0, float(os.environ.get("XCAGI_PASSIVE_SERVER_TICK_SEC", "5"))))
    except ValueError:
        return 5.0


def list_server_passive_poll_jobs() -> list[dict[str, Any]]:
    """扫描 pipeline 中 poll_enabled 的企业用户。"""
    from app.services.user_cs_pipeline import iter_pipeline_market_user_ids, load_pipeline
    from app.services.wechat_passive_group_monitor import _load_passive_state

    jobs: list[dict[str, Any]] = []
    for uid in iter_pipeline_market_user_ids():
        doc = load_pipeline(uid)
        state = _load_passive_state(doc)
        if not state.get("poll_enabled"):
            continue
        jobs.append(
            {
                "market_user_id": uid,
                "username": str(doc.get("username") or ""),
                "poll_interval_sec": int(state.get("poll_interval_sec") or 60),
                "last_poll_at": state.get("last_poll_at"),
            }
        )
    return jobs


def _parse_iso_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError):
        return 0.0


class PassivePollScheduler:
    """后台线程按各用户 poll_interval_sec 执行 passive_poll_once。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._registry_lock = threading.Lock()
        self._user_locks: dict[int, threading.Lock] = {}

    def start(self) -> None:
        if not _server_poll_enabled():
            logger.info("服务端被动轮询未启动（XCAGI_PASSIVE_SERVER_POLL=0）")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="wechat-passive-poll-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("服务端被动轮询已启动（离开内部客服页仍可自动回复）")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=8)
            self._thread = None

    def _user_lock(self, market_user_id: int) -> threading.Lock:
        with self._registry_lock:
            lock = self._user_locks.get(market_user_id)
            if lock is None:
                lock = threading.Lock()
                self._user_locks[market_user_id] = lock
            return lock

    def _loop(self) -> None:
        while not self._stop.wait(_tick_seconds()):
            try:
                self._tick()
            except Exception:
                logger.exception("passive poll scheduler tick failed")

    def _tick(self) -> None:
        now = time.time()
        for job in list_server_passive_poll_jobs():
            uid = int(job["market_user_id"])
            interval = max(10, int(job.get("poll_interval_sec") or 60))
            last = _parse_iso_ts(job.get("last_poll_at"))
            if last > 0 and now - last < interval - 0.5:
                continue
            lock = self._user_lock(uid)
            if not lock.acquire(blocking=False):
                continue
            try:
                self._run_poll_for_user(uid, str(job.get("username") or ""))
            finally:
                lock.release()

    def _run_poll_for_user(self, market_user_id: int, username: str) -> None:
        from app.services.wechat_passive_group_monitor import passive_poll_once

        try:
            passive_poll_once(
                market_user_id=market_user_id,
                username=username,
                dry_run=False,
                auto_reply=True,
                max_replies=1,
                use_llm=True,
                skip_sync=False,
            )
        except Exception:
            logger.exception("服务端被动轮询失败 market_user_id=%s", market_user_id)


_scheduler: PassivePollScheduler | None = None
_scheduler_guard = threading.Lock()


def get_passive_poll_scheduler() -> PassivePollScheduler:
    global _scheduler
    with _scheduler_guard:
        if _scheduler is None:
            _scheduler = PassivePollScheduler()
        return _scheduler


def start_passive_poll_scheduler() -> None:
    get_passive_poll_scheduler().start()


def stop_passive_poll_scheduler() -> None:
    get_passive_poll_scheduler().stop()
