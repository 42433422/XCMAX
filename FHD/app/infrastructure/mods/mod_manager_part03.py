# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


def get_mod_manager() -> _facade().ModManager:
    global _mod_manager
    if _facade()._mod_manager is None:
        _facade()._mod_manager = _facade().ModManager()
    return _facade()._mod_manager
