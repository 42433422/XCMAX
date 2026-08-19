# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


@_facade().dataclass(frozen=True)
class SurfaceTarget:
    lane: str
    lane_label: str
    name: str
    path: str
    viewport: str
    prepare: str = ""
    base: str = ""
