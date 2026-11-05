from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from app.domain.shared_services.conversation.intent import IntentMixin


def _build_result(primary_intent: str) -> SimpleNamespace:
    return SimpleNamespace(
        primary_intent=primary_intent,
        tool_key=None,
        intent_hints=[],
        is_negated=False,
        is_greeting=False,
        is_goodbye=False,
        is_help=False,
        is_confirmation=False,
        is_negation_intent=False,
        is_likely_unclear=False,
        slots={},
        all_matched_tools=[],
    )


@pytest.mark.parametrize("neuro_enabled", [False, True])
def test_concurrent_intent_calls_keep_loop_responsive_and_contexts_isolated(
    monkeypatch, neuro_enabled
):
    request_id = ContextVar("request_id", default="unset")
    loop_ticks = 0
    observed: list[tuple[str, str, int]] = []

    class Recognizer:
        def recognize(self, message, *args, **kwargs):
            before = request_id.get()
            ticks_before = loop_ticks
            time.sleep(0.2)
            observed.append((message, before, loop_ticks - ticks_before))
            result = _build_result(before)
            return SimpleNamespace(recognizer_result=result) if neuro_enabled else result

    host = IntentMixin()
    host.user_preference_service = SimpleNamespace(get_preference=lambda *args: "online")
    host.unified_recognizer = Recognizer()
    monkeypatch.setenv("XCAGI_NEURO_INTENT", "1" if neuro_enabled else "0")
    monkeypatch.setenv("XCAGI_SKIP_INTENT_LLM", "0")
    monkeypatch.setattr(
        "app.neuro_bus.integrations.intent_integration.get_neuro_intent_recognizer",
        lambda: Recognizer(),
    )
    monkeypatch.setattr(
        "app.neuro_bus.integrations.intent_integration.try_neuro_reflex_intent",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_intent_resolved",
        lambda *args: None,
    )

    async def run():
        stop = False

        async def heartbeat():
            nonlocal loop_ticks
            while not stop:
                loop_ticks += 1
                await asyncio.sleep(0.005)

        async def call(value: str):
            token = request_id.set(value)
            try:
                result = await host._recognize_intent(
                    value, "pro", value, {"request": value}
                )
                return result["primary_intent"], request_id.get()
            finally:
                request_id.reset(token)

        heartbeat_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        try:
            return await asyncio.gather(call("first"), call("second"))
        finally:
            stop = True
            await heartbeat_task

    first, second = asyncio.run(run())

    assert first == ("first", "first")
    assert second == ("second", "second")
    assert sorted((message, context) for message, context, _ in observed) == [
        ("first", "first"),
        ("second", "second"),
    ]
    for _, _, ticks_during_call in observed:
        assert ticks_during_call > 10
