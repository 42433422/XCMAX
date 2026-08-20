# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.openapi_connector_runtime")


class OutboundBlocked(RuntimeError):
    """用于安全策略拦截出站请求。"""
