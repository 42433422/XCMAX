# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_group_chat_service")


from app.application.ai_group_chat_service_aigroupchatservice_mixin02__aigroupchatservicepart02mixin_mixin01 import (
    __AiGroupChatServicePart02MixinPart01Mixin,
)
from app.application.ai_group_chat_service_aigroupchatservice_mixin02__aigroupchatservicepart02mixin_mixin02 import (
    __AiGroupChatServicePart02MixinPart02Mixin,
)
from app.application.ai_group_chat_service_aigroupchatservice_mixin02__aigroupchatservicepart02mixin_mixin03 import (
    __AiGroupChatServicePart02MixinPart03Mixin,
)


class _AiGroupChatServicePart02Mixin(
    __AiGroupChatServicePart02MixinPart01Mixin,
    __AiGroupChatServicePart02MixinPart02Mixin,
    __AiGroupChatServicePart02MixinPart03Mixin,
):
    pass
