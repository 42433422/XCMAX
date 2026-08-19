"""Shared FastAPI app factory for tests/ and XCAGI/xcagi_tests/."""

from __future__ import annotations

import os


def get_test_fastapi_app():
    """Return fully wired FastAPI app (same entry as production assembly)."""
    os.environ["XCAGI_NEURO_INTENT"] = "1"
    # TestClient 不跑 lifespan deferred 任务；关闭 fast-start 避免 SPA fallback 抢先匹配 API。
    os.environ["XCAGI_DESKTOP_FAST_START"] = "0"
    from app.fastapi_app import get_fastapi_app

    return get_fastapi_app()


def prime_test_env(*, sqlite_url: str | None = None) -> None:
    """Common env defaults for pytest suites."""
    os.environ.setdefault("XCAGI_SKIP_INTENT_LLM", "1")
    os.environ.setdefault("SECRET_KEY", "pytest-xcagi-secret-key-not-for-production")
    os.environ.setdefault("XCAGI_CLIENT_MODS_OFF", "0")
    if sqlite_url:
        os.environ["DATABASE_URL"] = sqlite_url
