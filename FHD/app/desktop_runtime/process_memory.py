"""Bound long-lived desktop backend memory and return unused pages to the OS.

xcagi-backend stays up for the whole desktop session. Several caches are capped
at write time; this guard additionally trims them and asks glibc to release
private pages when unique memory stays high.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import threading

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SOFT_LIMIT_BYTES = 1200 * 1024 * 1024
_INTERVAL_SECONDS = 60.0
_stop = threading.Event()
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _desktop_mode() -> bool:
    return (os.environ.get("XCAGI_DESKTOP_MODE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _unique_bytes() -> int:
    try:
        import psutil

        info = psutil.Process().memory_full_info()
        return int(getattr(info, "uss", None) or info.rss)
    except RECOVERABLE_ERRORS:
        return 0


def _malloc_trim() -> None:
    if os.name != "posix":
        return
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except RECOVERABLE_ERRORS:
        return


def release_excess_process_memory() -> dict[str, int | bool]:
    """Trim retained desktop caches when private memory is above the soft limit."""
    before = _unique_bytes()
    if not _desktop_mode() or before < _SOFT_LIMIT_BYTES:
        return {"before": before, "after": before, "trimmed": False}
    try:
        from app.neuro_bus.event_store import get_event_store

        get_event_store().trim_memory(5000)
    except RECOVERABLE_ERRORS:
        logger.debug("event store trim skipped", exc_info=True)
    try:
        from app.neuro_bus.bus import get_neuro_bus

        bus = get_neuro_bus()
        buffer = getattr(bus, "_event_buffer", None)
        if isinstance(buffer, list) and len(buffer) > 500:
            del buffer[:-500]
    except RECOVERABLE_ERRORS:
        logger.debug("neuro event buffer trim skipped", exc_info=True)
    try:
        from app.utils.performance.cache_manager import get_ai_response_cache

        get_ai_response_cache().clear()
    except RECOVERABLE_ERRORS:
        logger.debug("ai response cache trim skipped", exc_info=True)
    gc.collect()
    _malloc_trim()
    after = _unique_bytes()
    logger.warning(
        "desktop backend memory trim before=%s after=%s",
        before,
        after,
    )
    return {"before": before, "after": after, "trimmed": True}


def start_process_memory_guard() -> None:
    global _thread
    if not _desktop_mode():
        return
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()

        def _loop() -> None:
            while not _stop.wait(_INTERVAL_SECONDS):
                try:
                    release_excess_process_memory()
                except RECOVERABLE_ERRORS:
                    logger.debug("desktop memory guard failed", exc_info=True)

        _thread = threading.Thread(target=_loop, name="xcagi-memory-guard", daemon=True)
        _thread.start()


def stop_process_memory_guard() -> None:
    _stop.set()
