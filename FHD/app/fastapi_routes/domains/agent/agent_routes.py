"""Compat shim — canonical router lives in routes.py (debt19)."""

from app.fastapi_routes.domains.agent.routes import *  # noqa: F403
from app.fastapi_routes.domains.agent.routes import router as router
