"""Compat shim — canonical router lives in routes.py (debt19)."""

from app.application.agent_orchestrator.task_dispatcher import (  # noqa: F401
    notify_agent_task_dispatcher,
)
from app.fastapi_routes.domains.agent.route_support import (  # noqa: F401
    enqueue_run as _enqueue_run,
)
from app.fastapi_routes.domains.agent.routes import *  # noqa: F403
from app.fastapi_routes.domains.agent.routes import router as router

__all__ = ["router", "_enqueue_run", "notify_agent_task_dispatcher"]
