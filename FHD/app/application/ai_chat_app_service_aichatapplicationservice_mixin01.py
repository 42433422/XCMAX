# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


from app.application.ai_chat_app_service_aichatapplicationservice_mixin01__aichatapplicationservicepart01mixin_mixin01 import (
    __AIChatApplicationServicePart01MixinPart01Mixin,
)
from app.application.ai_chat_app_service_aichatapplicationservice_mixin01__aichatapplicationservicepart01mixin_mixin02 import (
    __AIChatApplicationServicePart01MixinPart02Mixin,
)


class _AIChatApplicationServicePart01Mixin(
    __AIChatApplicationServicePart01MixinPart01Mixin,
    __AIChatApplicationServicePart01MixinPart02Mixin,
):
    pass
