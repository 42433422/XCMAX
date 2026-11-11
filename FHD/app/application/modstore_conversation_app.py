"""Mod 商店对话客户端应用层门面。"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from app.domain.shared_services.conversation.modstore_adapter import (
    create_modstore_openai_client_from_request,
)

__all__ = ["create_modstore_openai_client_from_request"]


def request_model_scope(request: Any | None):
    if request is None:
        return nullcontext()
    from app.infrastructure.llm.client import llm_client_factory_scope

    return llm_client_factory_scope(lambda: create_modstore_openai_client_from_request(request))
