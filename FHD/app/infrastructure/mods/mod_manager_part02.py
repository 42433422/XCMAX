# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.infrastructure.mods.mod_manager')

class ModManager(_facade()._ModManagerPart01Mixin, _facade()._ModManagerPart02Mixin):
    pass
