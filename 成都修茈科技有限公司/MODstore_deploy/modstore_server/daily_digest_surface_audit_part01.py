# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest_surface_audit")


def _internal_api_base() -> str:
    """MODstore 登录 / catalog / digest-identity API 根（Mac 本地默认 :8788，非生产 :9990）。"""
    from modstore_server.surface_audit_deps import resolve_internal_api_base

    return resolve_internal_api_base()
