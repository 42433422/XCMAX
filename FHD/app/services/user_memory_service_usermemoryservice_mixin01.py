# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.user_memory_service")


from app.services.user_memory_service_usermemoryservice_mixin01__usermemoryservicepart01mixin_mixin01 import (
    __UserMemoryServicePart01MixinPart01Mixin,
)
from app.services.user_memory_service_usermemoryservice_mixin01__usermemoryservicepart01mixin_mixin02 import (
    __UserMemoryServicePart01MixinPart02Mixin,
)


class _UserMemoryServicePart01Mixin(
    __UserMemoryServicePart01MixinPart01Mixin, __UserMemoryServicePart01MixinPart02Mixin
):
    pass
