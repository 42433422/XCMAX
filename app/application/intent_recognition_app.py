"""意图识别应用层入口。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways.intent import recognize_intents


def recognize_intents_app(message: str) -> dict[str, Any]:
    return recognize_intents(message)


# 兼容旧名
recognize_intents = recognize_intents_app
