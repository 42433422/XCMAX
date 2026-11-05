"""Choose native image input or the existing local OCR conversion."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .protocols import Messages, Route


def prepare_sync(
    messages: Messages, route: Route, vision: Callable[[str, str], bool | None]
) -> Messages:
    from app.application.workflow.multimodal_user_content import (
        messages_have_image_parts,
        replace_image_parts_with_ocr_text,
    )

    if not messages_have_image_parts(messages):
        return messages
    support = vision(*route)
    if support is True:
        return messages
    return replace_image_parts_with_ocr_text(
        messages, model_label="/".join(route), model_confirmed_text_only=support is False
    )


async def prepare_async(
    messages: Messages, route: Route, vision: Callable[[str, str], Awaitable[bool | None]]
) -> Messages:
    from app.application.workflow.multimodal_user_content import (
        messages_have_image_parts,
        replace_image_parts_with_ocr_text,
    )

    if not messages_have_image_parts(messages):
        return messages
    support = await vision(*route)
    if support is True:
        return messages
    return await asyncio.to_thread(
        replace_image_parts_with_ocr_text,
        messages,
        model_label="/".join(route),
        model_confirmed_text_only=support is False,
    )
