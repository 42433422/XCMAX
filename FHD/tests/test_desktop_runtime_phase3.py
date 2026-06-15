"""desktop_runtime cache / queue / logging 单测。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.desktop_runtime.cache import DesktopMemoryCache, get_desktop_cache
from app.desktop_runtime.logging_setup import attach_desktop_file_logging
from app.desktop_runtime.queue import submit_background


def test_desktop_memory_cache_get_set_delete():
    cache = DesktopMemoryCache()
    cache.set("k", "v")
    assert cache.get("k") == "v"
    cache.delete("k")
    assert cache.get("k") is None


def test_desktop_memory_cache_ttl_expiry(monkeypatch):
    cache = DesktopMemoryCache()
    now = 1_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    cache.set("ttl", "gone", ttl=10)
    assert cache.get("ttl") == "gone"
    monkeypatch.setattr(time, "time", lambda: now + 11)
    assert cache.get("ttl") is None


def test_desktop_memory_cache_get_or_set_factory():
    cache = DesktopMemoryCache()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return "built"

    assert cache.get_or_set("x", factory) == "built"
    assert cache.get_or_set("x", factory) == "built"
    assert calls["n"] == 1


def test_get_desktop_cache_singleton():
    assert get_desktop_cache() is get_desktop_cache()


def test_attach_desktop_file_logging_idempotent(tmp_path):
    root = logging.getLogger()
    before = len(root.handlers)
    attach_desktop_file_logging(tmp_path)
    after_first = len(root.handlers)
    attach_desktop_file_logging(tmp_path)
    assert len(root.handlers) == after_first
    assert (tmp_path / "xcagi.log").is_file() or after_first > before


def test_submit_background_runs_func():
    done = {"ok": False}

    def job():
        done["ok"] = True

    fut = submit_background(job)
    fut.result(timeout=5)
    assert done["ok"] is True
