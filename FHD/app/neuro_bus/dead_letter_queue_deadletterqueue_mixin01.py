# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.neuro_bus.dead_letter_queue")


from app.neuro_bus.dead_letter_queue_deadletterqueue_mixin01__deadletterqueuepart01mixin_mixin01 import (
    __DeadLetterQueuePart01MixinPart01Mixin,
)
from app.neuro_bus.dead_letter_queue_deadletterqueue_mixin01__deadletterqueuepart01mixin_mixin02 import (
    __DeadLetterQueuePart01MixinPart02Mixin,
)


class _DeadLetterQueuePart01Mixin(
    __DeadLetterQueuePart01MixinPart01Mixin, __DeadLetterQueuePart01MixinPart02Mixin
):
    pass
