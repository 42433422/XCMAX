# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


def _env(name: str, default: str = "") -> str:
    return (_facade().os.environ.get(name) or default).strip()


def _bridge_user_id() -> int:
    """可选：把 QQ 来访都挂在哪个真实用户名下做审计/计费。0 = 不挂任何人。"""
    raw = _facade()._env("BUTLER_QQ_BRIDGE_USER_ID", "0")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


class _CredsState:
    __slots__ = ("data", "expires_at")

    def __init__(self) -> None:
        self.data: _facade().Dict[str, _facade().Any] = {}
        self.expires_at: float = 0.0
