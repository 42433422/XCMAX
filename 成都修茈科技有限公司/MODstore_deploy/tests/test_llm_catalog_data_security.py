from __future__ import annotations

from modstore_server import llm_catalog_data


def test_cache_key_is_stable_and_does_not_expose_api_key() -> None:
    secret = "sk-super-secret-value"

    first = llm_catalog_data.cache_key(7, "openai", secret)
    second = llm_catalog_data.cache_key(7, "openai", secret)

    assert first == second
    assert first.startswith("openai:")
    assert secret not in first
    assert llm_catalog_data.cache_key(8, "openai", secret) != first
    assert llm_catalog_data.cache_key(7, "anthropic", secret) != first
    assert llm_catalog_data.cache_key(7, "openai", secret + "-rotated") != first


def test_vendor_declared_capacity_requires_exact_provider_model_and_provenance(monkeypatch):
    monkeypatch.setattr(
        llm_catalog_data,
        "load_fallback",
        lambda: {
            "vendor": [
                {
                    "model": "supported",
                    "context_window": 32000,
                    "max_output_tokens": 4000,
                    "capability_source": "https://vendor.example/model",
                },
                {
                    "model": "output-only",
                    "max_tokens": 8000,
                    "capability_source": "https://vendor.example/model",
                },
                {"model": "no-evidence", "context_window": 32000},
            ],
        },
    )
    assert llm_catalog_data.declared_model_capabilities("vendor", "supported") == {
        "context_window": 32000,
        "max_output_tokens": 4000,
    }
    for provider, model in (
        ("other", "supported"),
        ("vendor", "supported-alias"),
        ("vendor", "output-only"),
        ("vendor", "no-evidence"),
    ):
        assert llm_catalog_data.declared_model_capabilities(provider, model) == {}


def test_shipped_mimo_capacity_matches_existing_offline_declaration():
    import json
    from pathlib import Path

    catalog = Path(__file__).resolve().parents[3] / "FHD/config/model_context_windows.json"
    offline = json.loads(catalog.read_text(encoding="utf-8"))["models"]
    declared = llm_catalog_data.declared_model_capabilities("xiaomi", "mimo-v2.6-flash")
    assert declared["context_window"] == offline["xiaomi/mimo-v2.6-flash"]
    assert declared["max_output_tokens"] == 128000
