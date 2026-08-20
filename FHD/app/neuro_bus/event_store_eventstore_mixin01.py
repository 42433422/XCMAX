# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.event_store")


from app.neuro_bus.event_store_eventstore_mixin01__eventstorepart01mixin_mixin01 import (
    __EventStorePart01MixinPart01Mixin,
)
from app.neuro_bus.event_store_eventstore_mixin01__eventstorepart01mixin_mixin02 import (
    __EventStorePart01MixinPart02Mixin,
)


class _EventStorePart01Mixin(
    __EventStorePart01MixinPart01Mixin, __EventStorePart01MixinPart02Mixin
):
    pass
