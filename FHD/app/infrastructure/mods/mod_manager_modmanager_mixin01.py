# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.infrastructure.mods.mod_manager")


from app.infrastructure.mods.mod_manager_modmanager_mixin01__modmanagerpart01mixin_mixin01 import (
    __ModManagerPart01MixinPart01Mixin,
)
from app.infrastructure.mods.mod_manager_modmanager_mixin01__modmanagerpart01mixin_mixin02 import (
    __ModManagerPart01MixinPart02Mixin,
)


class _ModManagerPart01Mixin(
    __ModManagerPart01MixinPart01Mixin, __ModManagerPart01MixinPart02Mixin
):
    pass
