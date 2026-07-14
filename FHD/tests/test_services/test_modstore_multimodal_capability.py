from __future__ import annotations

from app.services.conversation.modstore_adapter import _catalog_model_vision_support


def test_catalog_marks_regular_llm_as_text_only() -> None:
    catalog = {
        "providers": [
            {
                "provider": "xiaomi",
                "models_detailed": [
                    {
                        "id": "mimo-v2.5-pro",
                        "category": "llm",
                        "capability": {"effective_category": "llm"},
                    }
                ],
            }
        ]
    }
    assert _catalog_model_vision_support(catalog, "xiaomi", "mimo-v2.5-pro") is False


def test_catalog_allows_vlm_and_known_vision_name() -> None:
    catalog = {
        "providers": [
            {
                "provider": "openai",
                "models_detailed": [{"id": "visual-model", "category": "vlm"}],
            }
        ]
    }
    assert _catalog_model_vision_support(catalog, "openai", "visual-model") is True
    assert _catalog_model_vision_support({}, "openai", "gpt-4o") is True
