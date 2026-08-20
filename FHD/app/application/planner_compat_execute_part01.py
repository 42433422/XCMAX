# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.planner_compat_execute")


class _GlobalsFacade:
    def __init__(self, values: dict[str, _facade().Any]) -> None:
        self._values = values

    def __getattr__(self, name: str) -> _facade().Any:
        return self._values[name]


def set_facade_globals(
    values: dict[str, _facade().Any],
) -> _facade().Token[dict[str, _facade().Any] | None]:
    return _facade()._FACADE_GLOBALS.set(values)


def reset_facade_globals(token: _facade().Token[dict[str, _facade().Any] | None]) -> None:
    _facade()._FACADE_GLOBALS.reset(token)
