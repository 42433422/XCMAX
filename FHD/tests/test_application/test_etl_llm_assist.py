from __future__ import annotations

from app.application.etl.llm_assist import (
    LlmAssistResult,
    advise_field_mappings,
)
from app.application.etl.llm_session_provider import (
    SessionMarketProvider,
    bind_etl_llm_owner,
    current_etl_llm_owner,
    reset_etl_llm_owner,
)
from app.infrastructure.llm.structured_output import StructuredResult


def test_etl_structured_assist_uses_software_conversation_provider(monkeypatch):
    software_service = object()
    captured = {}
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, software_service, None),
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
    assert captured["provider"] is None
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


def test_etl_uses_only_current_owner_market_session(monkeypatch):
    captured = {}
    owner_token = bind_etl_llm_owner(42)
    try:
        monkeypatch.setattr(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            lambda: object(),
        )

        def fake_latest_session_market_token(*, user_id):
            captured["user_id"] = user_id
            return "owner-market-token"

        monkeypatch.setattr(
            "app.fastapi_routes.market_account.latest_session_market_token",
            fake_latest_session_market_token,
        )
        from app.application.etl.llm_assist import _active_software_llm

        configured, conversation_service, provider = _active_software_llm()
    finally:
        reset_etl_llm_owner(owner_token)

    assert configured is True
    assert conversation_service is None
    assert isinstance(provider, SessionMarketProvider)
    assert captured["user_id"] == 42


def test_etl_owner_context_resets():
    token = bind_etl_llm_owner(7)
    assert current_etl_llm_owner() == 7
    reset_etl_llm_owner(token)
    assert current_etl_llm_owner() is None


def test_etl_reports_stable_quota_degradation(monkeypatch):
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setattr(
        "app.application.etl.llm_assist._active_software_llm",
        lambda: (True, None, object()),
    )

    def quota_exhausted(*_args, **_kwargs):
        raise RuntimeError("upstream 429 quota exhausted")

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync",
        quota_exhausted,
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

    assert result.used_llm is True
    assert result.degraded is True
    assert result.degradation_code == "ETL_LLM_QUOTA_EXHAUSTED"
