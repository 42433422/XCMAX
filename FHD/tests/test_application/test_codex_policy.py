import json

import pytest

from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimePolicyError,
    RuntimeSettings,
    independent_gateway_url,
    runtime_settings,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://chatgpt.com/backend-api",
        "https://example.openai.azure.com/v1",
        "http://untrusted/v1",
        "https://secret:token@gateway.test/v1",
        "https://gateway.test/v1?key=secret",
        "",
    ],
)
def test_independent_profile_rejects_online_openai_and_insecure_routes(url):
    with pytest.raises(RuntimePolicyError):
        independent_gateway_url(url)


def test_no_configuration_preserves_native_behavior(monkeypatch):
    monkeypatch.delenv("XCAGI_AGENT_RUNTIME_CONFIG", raising=False)
    assert runtime_settings().engine == "native"


def test_only_real_exact_route_qualification_can_enable_runtime(tmp_path):
    route = ModelRoute("http://127.0.0.1:8000/v1", "model", "enterprise", "local", 32000, 4000)
    path = tmp_path / "qualification.json"
    settings = RuntimeSettings(engine="codex", route=route, qualification_file=path)
    evidence = {
        "schema": "xcmax.runtime-qualification.v1",
        "route_identity": route.identity,
        "codex_version": CODEX_VERSION,
        "model_kind": "real",
        "evidence_refs": ["run:1"],
        "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
    }
    for replacement in (
        {"model_kind": "synthetic"},
        {"route_identity": "another-route"},
        {"checks": {}},
        {"evidence_refs": []},
    ):
        path.write_text(json.dumps({**evidence, **replacement}))
        with pytest.raises(RuntimePolicyError):
            settings.require_qualified()
    path.write_text(json.dumps(evidence))
    assert settings.require_qualified() == route


def test_vendor_and_capacity_are_not_guessed():
    with pytest.raises(RuntimePolicyError):
        ModelRoute("https://gateway.test/v1", "model", "proxy", "openai", 32000, 4000)
    with pytest.raises(RuntimePolicyError):
        ModelRoute("https://gateway.test/v1", "model", "proxy", "local", 100, 100)
