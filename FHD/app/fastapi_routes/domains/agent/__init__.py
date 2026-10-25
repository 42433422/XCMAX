"""Agent API domain."""

from __future__ import annotations

from . import agent_routes as routes
from .agent_routes import router

__all__ = ["router", "routes"]
