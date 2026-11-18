"""Uncached model classification of the legacy intent corpus, without executing tools.

Uses the production model gateway and LangChain's Pydantic parser. This measures
classification/slots only; it is not evidence that a workflow executed successfully.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.workflow.planner_llm_gateway import request_planner_completion
from app.domain.shared_services.deepseek_intent_service import INTENT_DESCRIPTIONS, SLOT_DEFINITIONS
from app.utils.operational_errors import BOUNDARY_ERRORS


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: str
    slots: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intent")
    @classmethod
    def known_intent(cls, value: str) -> str:
        if value not in INTENT_DESCRIPTIONS and value != "out_of_scope":
            raise ValueError("model returned an unknown intent")
        return value


_PARSER = PydanticOutputParser(pydantic_object=Prediction)
_EVIDENCE: ContextVar[dict | None] = ContextVar("intent_benchmark_calls", default=None)


@contextmanager
def observe_model_calls() -> Iterator[dict]:
    evidence = {"attempted": 0, "completed": 0, "errors": [], "models": []}
    token = _EVIDENCE.set(evidence)
    try:
        yield evidence
    finally:
        _EVIDENCE.reset(token)


def predict(text: str) -> dict:
    """One fresh provider request per sample; configuration/failures stay visible."""
    evidence = _EVIDENCE.get()
    if evidence is not None:
        evidence["attempted"] += 1
    try:
        payload = request_planner_completion(
            ai_service=None,
            context=None,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "根据用户原话分类并提取槽位，仅用于离线评测，禁止执行操作。"
                        "否定操作选 negation；非业务也非问候/告别/帮助选 out_of_scope。"
                        "只提取原话明确给出的槽位，不编造缺失值。\n"
                        + json.dumps(
                            {"intents": INTENT_DESCRIPTIONS, "slots": SLOT_DEFINITIONS},
                            ensure_ascii=False,
                        )
                        + "\n"
                        + _PARSER.get_format_instructions()
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        if not isinstance(payload, dict) or not payload.get("choices"):
            raise RuntimeError("configured model unavailable or returned no completion")
        message = payload["choices"][0].get("message") or {}
        if message.get("tool_calls") or not isinstance(message.get("content"), str):
            raise ValueError("classification requires text without tool calls")
        prediction = _PARSER.parse(message["content"]).model_dump()
        if evidence is not None:
            evidence["completed"] += 1
            model = str(payload.get("model") or "unknown")
            if model not in evidence["models"]:
                evidence["models"].append(model)
        return prediction
    except BOUNDARY_ERRORS as exc:
        if evidence is not None:
            # Never record provider exception text: it can contain request credentials.
            evidence["errors"].append(type(exc).__name__)
        raise


def match_prediction(case: dict, result: dict) -> bool:
    intent = result.get("intent")
    check = case.get("check")
    if check in {"greeting", "goodbye", "help"}:
        expected = "greet" if check == "greeting" else check
    elif case.get("expect_negated"):
        expected = "negation"
    elif case.get("expected_out_of_scope"):
        expected = "out_of_scope"
    else:
        expected = (
            case.get("expected_route") or case.get("expected_tool") or case.get("expected_primary")
        )
    if not expected or intent != expected:
        return False
    slots = result.get("slots") or {}
    return all(slots.get(key) == value for key, value in (case.get("expected_slots") or {}).items())
