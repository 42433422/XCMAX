import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimePolicyError,
    RuntimeSettings,
    independent_gateway_url,
    qualification_host_identity,
    runtime_settings,
)
from tests.fixtures.xiaox_qualification import synthetic_qualification


def _route(**kwargs):
    return ModelRoute(
        "http://127.0.0.1:8000/v1", "model", "enterprise", "local", 32000, 4000, **kwargs
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


def test_unconfigured_fixed_executor_blocks_instead_of_selecting_retired_native(monkeypatch):
    monkeypatch.delenv("XCAGI_AGENT_RUNTIME_CONFIG", raising=False)
    settings = runtime_settings()
    assert settings.engine == "xiaox"
    assert settings.surfaces == ("chat", "employee")
    with pytest.raises(RuntimePolicyError, match="qualification is missing"):
        settings.require_qualified()


@pytest.mark.parametrize(
    "override", [{"engine": "native"}, {"surfaces": ["chat"]}, {"surfaces": []}]
)
def test_deployment_cannot_reenable_retired_loops_or_split_entrypoints(
    tmp_path, monkeypatch, override
):
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps(override))
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", str(config))
    with pytest.raises(RuntimePolicyError):
        runtime_settings()


def test_only_real_exact_route_qualification_can_enable_runtime(tmp_path):
    route = _route()
    path = tmp_path / "qualification.json"
    settings = RuntimeSettings(engine="xiaox", route=route, qualification_file=path)
    evidence = synthetic_qualification(route, tmp_path)
    for replacement in (
        {"model_kind": "synthetic"},
        {"route_identity": "another-route"},
        {"codex_version": "0.170.0"},
        {"host_identity": {}},
        {"checks": {}},
        {"evidence_refs": []},
    ):
        path.write_text(json.dumps({**evidence, **replacement}))
        with pytest.raises(RuntimePolicyError):
            settings.require_qualified()
    path.write_text(json.dumps(evidence))
    assert settings.require_qualified() == route


@pytest.mark.parametrize(
    "defect",
    ["deleted", "changed", "wrong_binding", "missing_digest", "outside", "symlink", "oversize"],
)
def test_pass_requires_the_original_bounded_local_evidence(tmp_path, defect):
    route = _route()
    certificate = tmp_path / "qualification.json"
    receipt = synthetic_qualification(route, tmp_path)
    evidence = Path(receipt["evidence_refs"][0])
    if defect == "deleted":
        evidence.unlink()
    elif defect == "changed":
        evidence.write_text(evidence.read_text() + " ")
    elif defect in {"wrong_binding", "oversize"}:
        raw = json.loads(evidence.read_text())
        raw["route_identity"] = "different-route" if defect == "wrong_binding" else route.identity
        if defect == "oversize":
            raw["padding"] = "x" * 1_048_577
        evidence.write_text(json.dumps(raw))
        receipt["evidence_sha256"][str(evidence)] = hashlib.sha256(
            evidence.read_bytes()
        ).hexdigest()
    elif defect == "missing_digest":
        receipt.pop("evidence_sha256")
    elif defect == "outside":
        certificate = tmp_path / "different-host" / "qualification.json"
        certificate.parent.mkdir()
    elif defect == "symlink":
        actual = evidence.with_name("original.json")
        evidence.rename(actual)
        evidence.symlink_to(actual)
    certificate.write_text(json.dumps(receipt))
    with pytest.raises(RuntimePolicyError, match="evidence"):
        RuntimeSettings(route=route, qualification_file=certificate).require_qualified()


def test_response_model_defaults_to_request_model_and_alias_binding_is_explicit():
    route = _route()
    assert route.response_model == route.model
    assert type(route.response_model) is str
    assert route.identity == _route(response_model="model").identity

    snapshot = replace(route, response_model="model-snapshot")
    other_snapshot = replace(snapshot, response_model="model-next-snapshot")
    litellm = replace(snapshot, gateway_kind="litellm")
    assert len({route.identity, snapshot.identity, other_snapshot.identity, litellm.identity}) == 4
    assert litellm.runtime_identity() == {
        "provider_id": "enterprise",
        "route_identity": litellm.identity,
        "model": "model",
        "response_model": "model-snapshot",
        "failover_policy": "disabled",
        "gateway_kind": "litellm",
        "upstream_vendor": "local",
        "independent": True,
        "max_model_calls": 24,
    }


@pytest.mark.parametrize(
    "value",
    [None, True, 42, [], {}, "", " ", " model", "model ", "model\nsnapshot", "model\x00", "\x7f"],
)
def test_response_model_rejects_nonexact_or_malformed_identity(value):
    with pytest.raises(RuntimePolicyError, match="response_model"):
        _route(response_model=value)


@pytest.mark.parametrize("value", [None, True, "", "enabled", "auto", " disabled "])
def test_upstream_failover_cannot_be_enabled(value):
    with pytest.raises(RuntimePolicyError, match="failover must be disabled"):
        _route(failover_policy=value)


@pytest.mark.parametrize("value", [None, True, [], "", "auto", "openai", "LiteLLM"])
def test_gateway_protocol_cannot_be_guessed(value):
    with pytest.raises(RuntimePolicyError, match="gateway_kind"):
        _route(gateway_kind=value)


@pytest.mark.parametrize("check", QUALIFICATION_CHECKS)
@pytest.mark.parametrize("value", [None, "FAIL", "PENDING", True, "pass", {"status": "PASS"}])
def test_qualification_requires_each_gate_check(tmp_path, check, value):
    route = _route(response_model="model-snapshot")
    checks = dict.fromkeys(QUALIFICATION_CHECKS, "PASS")
    if value is None:
        checks.pop(check, None)
    else:
        checks[check] = value
    evidence = synthetic_qualification(route, tmp_path, checks=checks)
    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(RuntimePolicyError, match="Exact route"):
        RuntimeSettings(route=route, qualification_file=path).require_qualified()


def test_previous_six_check_receipt_cannot_enable_compaction_recovery(tmp_path):
    route = _route()
    evidence = synthetic_qualification(route, tmp_path)
    # A short real-route smoke previously met every gate. It must no longer
    # qualify without the full compaction/restart/same-task/no-replay scenario.
    evidence["checks"] = {
        "responses_stream": "PASS",
        "multi_turn_tools": "PASS",
        "openai_network_denied": "PASS",
        "business_receipt_verified": "PASS",
        "upstream_failover_disabled": "PASS",
        "response_model_identity": "PASS",
    }
    path = tmp_path / "synthetic-short-run-qualification.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(RuntimePolicyError, match="Exact route"):
        RuntimeSettings(route=route, qualification_file=path).require_qualified()


def test_previous_route_certificate_is_invalid_even_with_new_checks(tmp_path):
    route = _route()
    # The previous certificate omitted the model mapping and failover/protocol policy.
    previous = {
        key: getattr(route, key)
        for key in (
            "base_url",
            "model",
            "provider_id",
            "upstream_vendor",
            "context_window",
            "max_output_tokens",
            "max_model_calls",
            "max_request_bytes",
        )
    }
    previous["codex_version"] = CODEX_VERSION
    previous_identity = hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
    assert route.identity != previous_identity
    path = tmp_path / "qualification.json"
    path.write_text(
        json.dumps(
            {**synthetic_qualification(route, tmp_path), "route_identity": previous_identity}
        )
    )
    with pytest.raises(RuntimePolicyError, match="Exact route"):
        RuntimeSettings(route=route, qualification_file=path).require_qualified()


@pytest.mark.parametrize("gateway_kind", ["responses", "litellm"])
def test_host_configuration_binds_request_alias_to_one_qualified_model(
    tmp_path, monkeypatch, gateway_kind
):
    route = _route(response_model="model-snapshot", gateway_kind=gateway_kind)
    certificate = tmp_path / "qualification.json"
    certificate.write_text(json.dumps(synthetic_qualification(route, tmp_path)))
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "route": {
                    "base_url": route.base_url,
                    "model": route.model,
                    "response_model": route.response_model,
                    "failover_policy": "disabled",
                    "gateway_kind": gateway_kind,
                    "provider_id": route.provider_id,
                    "upstream_vendor": route.upstream_vendor,
                    "context_window": route.context_window,
                    "max_output_tokens": route.max_output_tokens,
                },
                "runtime_root": str(tmp_path),
                "qualification_file": str(certificate),
            }
        )
    )
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", str(config))
    assert runtime_settings().require_qualified() == route
    for changed in (
        replace(route, response_model="another-snapshot"),
        replace(route, gateway_kind="litellm" if gateway_kind == "responses" else "responses"),
    ):
        with pytest.raises(RuntimePolicyError, match="Exact route"):
            replace(runtime_settings(), route=changed).require_qualified()


def test_vendor_and_capacity_are_not_guessed():
    with pytest.raises(RuntimePolicyError):
        ModelRoute("https://gateway.test/v1", "model", "proxy", "openai", 32000, 4000)
    with pytest.raises(RuntimePolicyError):
        ModelRoute("https://gateway.test/v1", "model", "proxy", "local", 100, 100)


def test_qualification_rejects_unidentified_host_before_admission(tmp_path, monkeypatch):
    from app import build_identity

    monkeypatch.setattr(build_identity, "_local_git_sha", lambda *_args: "")
    monkeypatch.setattr(build_identity, "_identity_file", lambda *_args: {"git_sha": "unknown"})
    with pytest.raises(RuntimePolicyError, match="host build identity"):
        qualification_host_identity()


def test_account_route_renews_credentials_without_rebinding_identity():
    route = _route(
        gateway_kind="market",
        credential="account-secret",
        route_token="route-secret",
        config_revision="rev-1",
        key_source="platform",
    )
    renewed = replace(
        route, credential="renewed-account-secret", route_token="renewed-route-secret"
    )
    assert renewed.identity == route.identity
    assert replace(route, config_revision="rev-2").identity != route.identity
    assert replace(route, key_source="user_override").identity != route.identity
    assert renewed.headers("req-1") == {
        "Authorization": "Bearer renewed-account-secret",
        "X-XCMax-Route-Token": "renewed-route-secret",
        "Idempotency-Key": "req-1",
    }
    public = json.dumps(route.runtime_identity()) + repr(route)
    assert "account-secret" not in public and "route-secret" not in public


@pytest.mark.parametrize(
    "override",
    [
        {"credential": ""},
        {"route_token": ""},
        {"config_revision": ""},
        {"key_source": ""},
        {"credential": "token\r\ninjected: secret"},
        {"api_key_env": "GLOBAL_CREDENTIAL"},
    ],
)
def test_account_route_requires_request_scoped_credentials(override):
    values = {
        "gateway_kind": "market",
        "credential": "token",
        "route_token": "route-token",
        "config_revision": "rev-1",
        "key_source": "platform",
    }
    with pytest.raises(RuntimePolicyError):
        _route(**{**values, **override})


@pytest.mark.parametrize("engine", ["codex", "xiaox"])
def test_legacy_deployment_label_selects_same_executor_without_rewriting(
    tmp_path, monkeypatch, engine
):
    from dataclasses import asdict

    root = tmp_path / "codex-runtime"
    root.mkdir()
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({
        "engine": engine,
        "route": asdict(_route()),
        "runtime_root": str(root),
        "qualification_file": str(root / "qualification.json"),
    }))
    original = config.read_bytes()
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", str(config))
    settings = runtime_settings()
    assert settings.engine == "xiaox"
    assert settings.route == _route()
    assert settings.runtime_root == root
    assert config.read_bytes() == original
    with pytest.raises(RuntimePolicyError):
        settings.require_qualified()
