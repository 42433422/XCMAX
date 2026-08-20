"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from app.infrastructure.mods.mod_manager_modmanager_mixin01 import (
    _ModManagerPart01Mixin,
)
from app.infrastructure.mods.mod_manager_modmanager_mixin02 import (
    _ModManagerPart02Mixin,
)


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


class ModManager(_ModManagerPart01Mixin, _ModManagerPart02Mixin):
    pass
