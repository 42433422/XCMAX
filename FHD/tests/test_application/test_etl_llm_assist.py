from __future__ import annotations

from app.application.etl.llm_assist import (
    LlmAssistResult,
    advise_field_mappings,
)
from app.infrastructure.llm.structured_output import StructuredResult


def test_etl_structured_assist_uses_software_conversation_provider(monkeypatch):
    software_service = object()
    captured = {}
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, software_service),
    )

    def fake_complete(messages, **kwargs):
        captured["messages"] = messages
        captured.update(kwargs)
        return StructuredResult(
            data={
                "mappings": [
                    {
                        "source": "货品",
                        "target": "name",
                        "transform": "trim",
                        "confidence": 0.93,
                        "reason": "货品列是产品名称",
                    }
                ]
            },
            attempts=1,
            repaired=False,
            model="software-model",
        )

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        fake_complete,
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": ["品名"],
            }
        ],
    )

    assert result.used_llm is True
    assert result.model == "software-model"
    assert result.data["mappings"][0]["target"] == "name"
    assert captured["conversation_service"] is software_service
    assert captured["profile"] == "etl"


def test_llm_mapping_rejects_invented_source_and_target(monkeypatch):
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._complete",
        lambda *_args, **_kwargs: LlmAssistResult(
            used_llm=True,
            data={
                "mappings": [
                    {
                        "source": "不存在列",
                        "target": "name",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                    {
                        "source": "货品",
                        "target": "dangerous_field",
                        "confidence": 0.99,
                        "reason": "invented",
                    },
                ]
            },
        ),
    )

    result = advise_field_mappings(
        headers=["货品"],
        samples={"货品": ["底漆"]},
        target_fields=[
            {
                "key": "name",
                "label": "产品名称",
                "type": "string",
                "required": True,
                "aliases": [],
            }
        ],
    )

    assert result.data["mappings"] == []
