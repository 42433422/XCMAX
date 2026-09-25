"""Evaluate the real normal-chat router with its configured model fallback.

Only routing is invoked: no builder, tool execution or business write is called.
Gold labels are used solely for scoring, never to select the prediction path.
"""

import os
import time
from contextlib import contextmanager
from unittest.mock import patch

from app.application import llm_intent_gate as gate
from app.utils.operational_errors import BOUNDARY_ERRORS


def predict(text: str) -> dict:
    from app.application.normal_chat_dispatch import route_normal_mode_message
    from app.services.intent_service import is_goodbye, is_greeting

    if is_greeting(text):
        return {"intent": "greeting"}
    if is_goodbye(text):
        return {"intent": "goodbye"}
    return route_normal_mode_message(text)


def match_prediction(case: dict, result: dict) -> bool:
    actual = result.get("intent", "unknown")
    if case.get("expect_negated") or case.get("expected_out_of_scope"):
        return actual in {"unknown", "clarify"}
    expected = case.get("expected_route") or case.get("check")
    if expected is None:
        tool = case.get("expected_tool") or case.get("expected_primary")
        expected = gate._LLM_TO_ROUTE.get(tool, tool)
    if expected is None:
        raise ValueError("benchmark case has no expected outcome")
    if actual != expected:
        return False
    slots = result.get("slots") or {}
    return all(slots.get(key) == value for key, value in case.get("expected_slots", {}).items())


def match_llm(case: dict, text: str) -> bool:
    return match_prediction(case, predict(text))


@contextmanager
def observe_model_calls():
    """Instrument the real provider boundary; never replace model responses."""
    from app.infrastructure.llm import structured_output

    original = structured_output.complete_structured_sync
    evidence = {"attempted": 0, "completed": 0, "errors": {}, "models": [], "seconds": 0.0}
    previous = os.environ.get("XCAGI_LLM_INTENT_GATE")
    previous_cache = gate._cache.copy()
    os.environ["XCAGI_LLM_INTENT_GATE"] = "1"
    gate._cache.clear()

    def observed(*args, **kwargs):
        evidence["attempted"] += 1
        started = time.monotonic()
        try:
            result = original(*args, **kwargs)
            evidence["completed"] += 1
            model = str(getattr(result, "model", "") or "")
            if model and model not in evidence["models"]:
                evidence["models"].append(model)
            return result
        except BOUNDARY_ERRORS as exc:  # Evaluation boundary records errors, then preserves them.
            name = type(exc).__name__
            evidence["errors"][name] = evidence["errors"].get(name, 0) + 1
            raise
        finally:
            evidence["seconds"] = round(evidence["seconds"] + time.monotonic() - started, 3)

    try:
        with patch.object(structured_output, "complete_structured_sync", observed):
            yield evidence
    finally:
        if previous is None:
            os.environ.pop("XCAGI_LLM_INTENT_GATE", None)
        else:
            os.environ["XCAGI_LLM_INTENT_GATE"] = previous
        gate._cache.clear()
        gate._cache.update(previous_cache)
