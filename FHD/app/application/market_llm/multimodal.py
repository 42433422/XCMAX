"""Choose native image input or the existing local OCR conversion."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from urllib.parse import quote, urlsplit

from .protocols import Messages, Route


def safe_image_result_urls(value: object) -> list[str]:
    """Keep raster data images and HTTPS targets safe inside Markdown results."""
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        return []
    images = []
    for url in value:
        if not isinstance(url, str) or not url or len(url) > 24 * 1024 * 1024:
            continue
        if any(ord(char) < 33 or ord(char) == 127 for char in url):
            continue
        if re.fullmatch(
            r"data:image/(png|jpeg|webp);base64,(?:[A-Za-z0-9+/]{4})*"
            r"(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?",
            url,
        ) and not url.endswith(","):
            images.append(url)
            continue
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or "\\" in parsed.netloc
            ):
                continue
            _ = parsed.port  # Reject malformed numeric ports before rendering.
        except ValueError:
            continue
        images.append(quote(url, safe=":/?#[]@!$&'*+,;=%"))
    return images


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
