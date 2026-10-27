"""Explicit, already-enrolled Linux catalog admission; never provisioning."""

from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher

_lock = threading.RLock()
_owner: CatalogAdmission | None = None


@dataclass(eq=False)
class CatalogAdmission:
    profile: tuple[Path, tuple[str, int, int]]
    config: object
    environment: tuple[str, ...]
    ready: bool = False
    dispatcher: AgentTaskDispatcher | None = None
    repositories: tuple[Any, ...] = ()


def _environment():
    # These values are process configuration, never request fields. Do not log secrets.
    return tuple(
        os.environ.get(key, "")
        for key in (
            "DATABASE_URL",
            "XCAGI_DATA_DIR",
            "WORKSPACE_ROOT",
            "XCAGI_OWNED_SOURCE_PROFILE",
            "SECRET_KEY",
            "XCAGI_DESKTOP_MODE",
        )
    )


def admit(config, existing_app=None):
    """Reserve one identity before the factory can start any runtime side effects."""
    global _owner
    declared = getattr(config, "OWNED_SOURCE_PROFILE", None)
    if declared is None:
        declared = os.environ.get("XCAGI_OWNED_SOURCE_PROFILE", "")
    with _lock:
        if _owner is not None:
            raise RuntimeError("guarded catalog process already belongs to another application")
        if declared != os.environ.get("XCAGI_OWNED_SOURCE_PROFILE", ""):
            raise RuntimeError("guarded parent and worker configuration differs")
        if not declared:
            return None
        if existing_app is not None:
            raise RuntimeError("guarded catalog requires a dedicated application process")
        from app.application.agent_orchestrator import (
            run_repository,
            task_dispatcher,
            task_execution_repository,
        )
        from app.desktop_runtime import database_generation_registry as registry

        if (
            run_repository.agent_memory_mode_enabled()
            or run_repository._agent_run_repository is not None
            or task_execution_repository._task_execution_repository is not None
            or task_dispatcher._dispatcher is not None
        ):
            raise RuntimeError("guarded catalog requires unused durable runtime repositories")
        secret = os.environ.get("SECRET_KEY", "").strip()
        if not secret or secret != getattr(config, "SECRET_KEY", None):
            raise RuntimeError("guarded parent and worker configuration differs")
        candidate = registry.validate_existing_owned_profile(config)
        if registry._owned_profile is not None:
            raise RuntimeError("guarded catalog profile already has an owner")
        admission = CatalogAdmission(candidate, config, _environment())
        runs = run_repository.SQLAlchemyAgentRunRepository(auto_create=False)
        queue = task_execution_repository.SQLAlchemyTaskExecutionRepository(auto_create=False)
        admission.repositories = (runs, queue)
        run_repository._agent_run_repository = runs
        run_repository._agent_run_repository_status = {
            "mode": "sqlalchemy",
            "durable": True,
            "degraded_reason": "",
        }
        task_execution_repository._task_execution_repository = queue
        registry._owned_profile = candidate
        _owner = admission
        return admission


def require_admission(admission, *, ready=True):
    from app.desktop_runtime import database_generation_registry as registry

    with _lock:
        if (
            admission is None
            or admission is not _owner
            or registry._owned_profile != admission.profile
            or admission.environment != _environment()
            or (ready and not admission.ready)
        ):
            raise RuntimeError("guarded application readiness is unavailable")
    registry.require_owned_source_profile()


def release(admission):
    """Only the owning, drained application may release its own runtime identity."""
    global _owner
    if admission is None:
        return
    from app.application.agent_orchestrator import (
        run_repository,
        task_dispatcher,
        task_execution_repository,
    )
    from app.desktop_runtime import database_generation_registry as registry

    with _lock:
        if admission is not _owner:
            return
        admission.ready = False
        if admission.dispatcher is not None:
            state = admission.dispatcher.snapshot()
            if state["running"] or state["active_count"]:
                raise RuntimeError("guarded workers are not drained; retain original authority")
        if admission.repositories:
            runs, queue = admission.repositories
            if run_repository._agent_run_repository is runs:
                run_repository._agent_run_repository = None
                run_repository._agent_run_repository_status = {
                    "mode": "uninitialized",
                    "durable": False,
                    "degraded_reason": "",
                }
            if task_execution_repository._task_execution_repository is queue:
                task_execution_repository._task_execution_repository = None
        if task_dispatcher._dispatcher is admission.dispatcher:
            task_dispatcher._dispatcher = None
        if registry._owned_profile == admission.profile:
            registry._owned_profile = None
        _owner = None


@asynccontextmanager
async def lifespan(app):
    """No DB repair, Mod installation, role seeding or model/background bootstrap."""
    admission = app.state.catalog_admission
    from app.application.agent_orchestrator import (
        run_repository,
        task_dispatcher,
        task_execution_repository,
    )
    from app.desktop_runtime import database_generation_registry as registry

    try:
        require_admission(admission, ready=False)
        if registry.validate_existing_owned_profile(admission.config) != admission.profile:
            raise RuntimeError("guarded identity changed before lifespan startup")
        runs, queue = admission.repositories
        if (
            run_repository._agent_run_repository is not runs
            or task_execution_repository._task_execution_repository is not queue
            or task_dispatcher._dispatcher is not None
        ):
            raise RuntimeError("guarded application runtime ownership changed")
        runs.list_recent(limit=1)
        queue.get("")
        admission.dispatcher = task_dispatcher.get_agent_task_dispatcher()
        task_dispatcher.start_agent_task_dispatcher()
        app.state.agent_task_dispatcher = admission.dispatcher
        admission.ready = True
        yield
    finally:
        admission.ready = False
        if admission.dispatcher is not None:
            admission.dispatcher.stop()
        release(admission)


class CatalogAdmissionMiddleware:
    """Production factory routes cannot borrow another app's global profile."""

    def __init__(self, app, *, admission):
        self.app, self.admission = app, admission

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            path.startswith("/api/etl/owned-mixed-v1/products") or self.admission is not None
        ):
            try:
                if self.admission is None:
                    from app.desktop_runtime import database_generation_registry as registry

                    # Preserve the unconfigured route's existing auth/error
                    # semantics, but never lend it another runtime's profile.
                    if _owner is not None or registry._owned_profile is not None:
                        raise RuntimeError("guarded application ownership differs")
                else:
                    require_admission(self.admission)
            except (RuntimeError, OSError, ValueError):
                response = JSONResponse(
                    {
                        "success": False,
                        "outcome": "unknown",
                        "retryable": False,
                        "message": "guarded application readiness is unavailable",
                    },
                    status_code=503,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
