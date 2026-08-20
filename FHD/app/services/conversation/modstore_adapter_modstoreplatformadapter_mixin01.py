# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.conversation.modstore_adapter")


from app.services.conversation.modstore_adapter_modstoreplatformadapter_mixin01__modstoreplatformadapterpart01mixin_mixin01 import (
    __ModstorePlatformAdapterPart01MixinPart01Mixin,
)
from app.services.conversation.modstore_adapter_modstoreplatformadapter_mixin01__modstoreplatformadapterpart01mixin_mixin02 import (
    __ModstorePlatformAdapterPart01MixinPart02Mixin,
)


class _ModstorePlatformAdapterPart01Mixin(
    __ModstorePlatformAdapterPart01MixinPart01Mixin, __ModstorePlatformAdapterPart01MixinPart02Mixin
):
    pass
