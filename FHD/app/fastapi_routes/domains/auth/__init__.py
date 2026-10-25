"""Authentication domains can be imported without assembling the application router."""

from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import auth_routes as routes

__all__ = ["auth", "routes"]


def __getattr__(name: str) -> ModuleType:
    if name in {"routes", "_routes"}:
        return import_module(f"{__name__}.routes")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
