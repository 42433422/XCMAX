"""Compatibility facade for the private Mod delivery application use case.

Private-delivery state, progress and artifact handling now live under
``app.application``.  Some installed extensions and older route modules still
import this service path, so retain it as a lazy forwarding facade instead of
maintaining a second state machine that can drift from the desktop product.
"""

from __future__ import annotations

from app.application import private_mod_delivery_app as _delivery

__all__ = list(_delivery.__all__)


def __getattr__(name: str):
    """Forward the legacy service API to the canonical application layer."""
    try:
        return getattr(_delivery, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_delivery)))
