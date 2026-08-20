# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


from app.application.ai_group_chat_service_aigroupchatservice_mixin01__aigroupchatservicepart01mixin_mixin01 import (
    __AiGroupChatServicePart01MixinPart01Mixin,
)
from app.application.ai_group_chat_service_aigroupchatservice_mixin01__aigroupchatservicepart01mixin_mixin02 import (
    __AiGroupChatServicePart01MixinPart02Mixin,
)


class _AiGroupChatServicePart01Mixin(
    __AiGroupChatServicePart01MixinPart01Mixin, __AiGroupChatServicePart01MixinPart02Mixin
):
    pass
