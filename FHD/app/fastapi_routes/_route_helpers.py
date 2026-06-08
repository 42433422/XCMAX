"""Shared helpers for FastAPI route registration."""

from __future__ import annotations

from app.utils.operational_errors import OPERATIONAL_ERRORS
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


def is_ci_strict() -> bool:
    """When CI=1, optional route import failures should fail the build."""
    return os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on")


def try_include_router(
    app: FastAPI,
    name: str,
    loader: Callable[[], APIRouter],
    *,
    prefix: str | None = None,
    tags: list[str] | None = None,
    required_in_ci: bool = False,
    log_level: int = logging.WARNING,
    **include_kwargs: Any,
) -> bool:
    """Import and mount a router; re-raise in CI when ``required_in_ci``."""
    try:
        router = loader()
        kwargs = dict(include_kwargs)
        if prefix is not None:
            kwargs["prefix"] = prefix
        if tags is not None:
            kwargs["tags"] = tags
        app.include_router(router, **kwargs)
        logger.info("Registered %s", name)
        return True
    except OPERATIONAL_ERRORS as exc:
        if is_ci_strict() and required_in_ci:
            raise RuntimeError(f"Required route mount failed in CI: {name}") from exc
        logger.log(log_level, "%s not available: %s", name, exc)
        return False


def try_call_register(
    app: FastAPI,
    name: str,
    register_fn: Callable[[FastAPI], None],
    *,
    required_in_ci: bool = False,
) -> bool:
    """Call a register function; re-raise in CI when ``required_in_ci``."""
    try:
        register_fn(app)
        logger.info("Registered %s", name)
        return True
    except OPERATIONAL_ERRORS as exc:
        if is_ci_strict() and required_in_ci:
            raise RuntimeError(f"Required route registration failed in CI: {name}") from exc
        logger.warning("%s skipped: %s", name, exc)
        return False
