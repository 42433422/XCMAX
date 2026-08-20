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
