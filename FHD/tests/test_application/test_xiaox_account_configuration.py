"""Account configuration wiring; synthetic qualification is never live acceptance."""

from __future__ import annotations

import copy
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.application.agent_runtime import configuration
from app.application.market_llm.protocols import Connection
from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    QualificationUpgradeRequired,
    RuntimePolicyError,
)
from tests.fixtures.xiaox_qualification import synthetic_qualification


@pytest.fixture
def account(monkeypatch, tmp_path):
    state = SimpleNamespace(
        calls=[],
        attempts=[],
        succeeds=True,
        error_code="runtime_qualification_failed",
        checks={},
        snapshot={
            "provider": "litellm",
            "model": "team-model",
            "key_source": "platform",
            "config_revision": "7",
            "route_token": "private-route-token",
            "model_capabilities": {"context_window": 32000, "max_output_tokens": 4000},
            "runtime": {
                "schema": "xcmax.xiaox-route.v1",
                "codex_version": CODEX_VERSION,
                "gateway_kind": "market",
                "upstream_vendor": "anthropic",
                "response_model": "claude-fixture",
                "failover_policy": "disabled",
                "max_model_calls": 24,
                "max_request_bytes": 4194304,
            },
        },
    )

    def response(request):
        state.calls.append(request)
        assert request.url.path == "/api/llm/resolve-chat-default"
        assert request.url.params["runtime"] == "codex"
        data = copy.deepcopy(state.snapshot)
        data["route_token"] = (
            f"private-route-token-{len(state.calls)}" if "route_token" in data else None
        )
        if "model" in request.url.params:
            data["model"] = request.url.params["model"]
        return httpx.Response(200, json=data)

    def qualify(settings, **kwargs):
        state.attempts.append((settings, kwargs))
        if state.succeeds:
            # Deliberately synthetic: exercises the real receipt reader, not a model.
            settings.qualification_file.write_text(
                json.dumps(
                    synthetic_qualification(settings.route, settings.qualification_file.parent)
                )
            )
        return {"ok": state.succeeds, "error_code": state.error_code, "checks": state.checks}

    monkeypatch.setattr(
        configuration,
        "httpx_sync_client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(response), **kwargs),
    )
    monkeypatch.setattr(
        configuration,
        "_account_connection",
        lambda owner: Connection("https://market.test", f"private-account-{owner}", None, 5),
    )
    monkeypatch.setattr(configuration, "enterprise_model_for_actor", lambda _owner: None)
    monkeypatch.setattr(configuration, "get_desktop_state_dir", lambda **_kwargs: str(tmp_path))
    monkeypatch.setattr("app.infrastructure.xiaox.qualification.qualify_runtime", qualify)
    monkeypatch.delenv("XCAGI_AGENT_RUNTIME_CONFIG", raising=False)
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "unrelated-host-account")
    return state


@pytest.mark.parametrize("signed, expected", [(None, 300), (120, 120)])
def test_market_timeout_remains_bounded_by_the_advertised_route(
    account, monkeypatch, signed, expected
):
    from app.infrastructure.xiaox.model_gateway import model_request_timeout_seconds

    monkeypatch.setenv("XCAGI_MODEL_REQUEST_TIMEOUT_SEC", "300")
    if signed is not None:
        account.snapshot["runtime"]["request_timeout_seconds"] = signed
    settings = configuration.get_account_runtime_settings("test-owner", qualify=False)
    assert settings.route is not None
    assert model_request_timeout_seconds(settings.route) == expected


@pytest.mark.parametrize("key_source", ["platform", "user_override"])
def test_account_route_needs_no_manual_config_and_reuses_exact_qualification(
    account, tmp_path, key_source
):
    account.snapshot["key_source"] = key_source
    first = configuration.get_account_runtime_settings("41")
    second = configuration.get_account_runtime_settings("41")
    other = configuration.get_account_runtime_settings("42")
    assert first.require_qualified().model == "litellm/team-model"
    assert first.route.base_url == "https://market.test/v1"
    assert first.route.token() == "private-account-41"
    assert first.route.response_model == "claude-fixture"
    assert first.route.key_source == key_source
    assert first.route.route_token != account.attempts[0][0].route.route_token
    assert second.route.identity == first.route.identity
    assert first.runtime_root != other.runtime_root
    assert len(account.attempts) == 2
    assert len(account.calls) == 5  # Two fresh qualifications refresh; cached PASS resolves once.
    assert stat.S_IMODE(first.runtime_root.stat().st_mode) == 0o700
    assert account.calls[0].headers["Authorization"] == "Bearer private-account-41"
    public = repr(first) + json.dumps(first.route.runtime_identity())
    durable = "".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert all(
        secret not in public + durable
        for secret in ("private-account-41", "private-route-token", "unrelated-host-account")
    )


def test_failed_setup_is_not_rebilled_on_each_chat_and_explicit_retry_is_bounded(account):
    account.succeeds = False
    with pytest.raises(configuration.RuntimeSetupError, match="尚未通过"):
        configuration.get_account_runtime_settings("41")
    with pytest.raises(configuration.RuntimeSetupError, match="runtime-check --retry"):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 1
    account.succeeds = True
    qualified = configuration.get_account_runtime_settings("41", retry=True)
    assert qualified.require_qualified() == qualified.route
    configuration.get_account_runtime_settings("41", retry=True)
    assert len(account.attempts) == 2


@pytest.mark.parametrize("succeeds", [True, False])
def test_previous_single_step_qualification_gets_one_bounded_automatic_upgrade(account, succeeds):
    previous = configuration.get_account_runtime_settings("41")
    certificate = previous.qualification_file
    receipt = synthetic_qualification(
        previous.route, certificate.parent, checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS")
    )
    certificate.write_text(json.dumps(receipt))
    original_evidence = Path(receipt["evidence_refs"][0])
    original_evidence_bytes = original_evidence.read_bytes()
    account.succeeds = succeeds
    if succeeds:
        upgraded = configuration.get_account_runtime_settings("41")
        assert upgraded.require_qualified() == upgraded.route
        assert len(account.attempts) == 2
        configuration.get_account_runtime_settings("41")
    else:
        for _ in range(2):
            with pytest.raises(configuration.RuntimeSetupError):
                configuration.get_account_runtime_settings("41")
        assert json.loads(certificate.read_text()) == receipt
    assert len(account.attempts) == 2  # No repeated billing on subsequent chats.
    assert original_evidence.read_bytes() == original_evidence_bytes
    if not succeeds:
        account.succeeds = True
        retried = configuration.get_account_runtime_settings("41", retry=True)
        assert retried.require_qualified() == retried.route
        assert len(account.attempts) == 3


def test_interrupted_upgrade_does_not_start_another_paid_probe(account):
    previous = configuration.get_account_runtime_settings("41")
    certificate = previous.qualification_file
    receipt = synthetic_qualification(
        previous.route, certificate.parent, checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS")
    )
    certificate.write_text(json.dumps(receipt))
    certificate.with_name("setup-attempt.json").write_text(
        json.dumps({"state": "started", "route_identity": previous.route.identity})
    )
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 1


def test_verified_seven_check_status_requires_upgrade_without_starting_it(account):
    settings = configuration.get_account_runtime_settings("41")
    receipt = synthetic_qualification(
        settings.route,
        settings.qualification_file.parent,
        checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS"),
    )
    settings.qualification_file.write_text(json.dumps(receipt))
    before = settings.qualification_file.with_name("setup-attempt.json").read_bytes()
    status = configuration.get_account_runtime_status("41")
    assert status["qualification"] == "required" and status["retry_required"] is False
    assert len(account.attempts) == 1
    assert settings.qualification_file.with_name("setup-attempt.json").read_bytes() == before
    configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 2


@pytest.mark.parametrize(
    "defect", ["missing_host", "missing_digest", "changed_evidence", "failed_eighth"]
)
def test_unverified_old_evidence_cannot_authorize_automatic_upgrade(account, defect):
    settings = configuration.get_account_runtime_settings("41")
    checks = dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS")
    if defect == "failed_eighth":
        checks["multi_step_restart_continuation"] = "FAIL"
    receipt = synthetic_qualification(
        settings.route, settings.qualification_file.parent, checks=checks
    )
    if defect == "missing_host":
        receipt.pop("host_identity")
    elif defect == "missing_digest":
        receipt.pop("evidence_sha256")
    elif defect == "changed_evidence":
        Path(receipt["evidence_refs"][0]).write_text("changed original proof")
    settings.qualification_file.write_text(json.dumps(receipt))
    before = settings.qualification_file.read_bytes()
    with pytest.raises(RuntimePolicyError) as failure:
        settings.require_qualified()
    assert not isinstance(failure.value, QualificationUpgradeRequired)
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 1
    assert settings.qualification_file.read_bytes() == before


@pytest.mark.parametrize(
    "receipt_state", ["passed_eight", "passed_seven", "missing_host", "changed_evidence"]
)
def test_missing_journal_cannot_turn_an_existing_certificate_into_a_first_attempt(
    account, receipt_state
):
    settings = configuration.get_account_runtime_settings("41")
    certificate = settings.qualification_file
    checks = QUALIFICATION_CHECKS if receipt_state == "passed_eight" else QUALIFICATION_CHECKS[:-1]
    receipt = synthetic_qualification(
        settings.route, certificate.parent, checks=dict.fromkeys(checks, "PASS")
    )
    if receipt_state == "missing_host":
        receipt.pop("host_identity")
    elif receipt_state == "changed_evidence":
        Path(receipt["evidence_refs"][0]).write_text("unknown original evidence")
    certificate.write_text(json.dumps(receipt))
    journal = certificate.with_name("setup-attempt.json")
    journal.unlink()
    status = configuration.get_account_runtime_status("41")
    if receipt_state == "passed_eight":
        assert status["qualification"] == "passed"
        assert (
            configuration.get_account_runtime_settings("41").require_qualified() == settings.route
        )
    else:
        assert status["qualification"] == "interrupted" and status["retry_required"] is True
        with pytest.raises(configuration.RuntimeSetupError):
            configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 1 and not journal.exists()
    if receipt_state != "passed_eight":
        assert (
            configuration.get_account_runtime_settings("41", retry=True).require_qualified()
            == settings.route
        )
        assert len(account.attempts) == 2


def test_missing_failed_upgrade_journal_does_not_repeat_a_paid_attempt(account):
    settings = configuration.get_account_runtime_settings("41")
    certificate = settings.qualification_file
    receipt = synthetic_qualification(
        settings.route, certificate.parent, checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS")
    )
    certificate.write_text(json.dumps(receipt))
    account.succeeds = False
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 2
    journal = certificate.with_name("setup-attempt.json")
    assert json.loads(journal.read_text())["model_attempted"] is True
    journal.unlink()
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 2 and not journal.exists()


def test_staging_only_prepares_a_pinned_route_and_qualifies_on_execution(account):
    staged = configuration.get_account_runtime_settings("41", qualify=False)
    assert account.attempts == []
    assert not staged.qualification_file.exists()
    assert not staged.qualification_file.with_name("setup-attempt.json").exists()
    account.snapshot["model"] = "different-default"
    started = configuration.get_account_runtime_settings(
        "41", previous=staged.route.runtime_identity()
    )
    assert started.require_qualified().identity == staged.route.identity
    assert len(account.attempts) == 1
    assert account.calls[-1].url.params["model"] == "team-model"


def test_failed_setup_preserves_only_safe_diagnostic_code_and_checks(account, tmp_path):
    account.succeeds = False
    account.error_code = "runtime_billing_evidence_missing"
    account.checks = {
        "responses_stream": "PASS",
        "business_receipt_verified": "FAIL",
        "credential": "private-token",
    }
    for _ in range(2):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            configuration.get_account_runtime_settings("41")
        assert exc.value.code == "runtime_billing_evidence_missing"
        assert "计费回执" in str(exc.value)
        assert exc.value.checks == {"responses_stream": "PASS", "business_receipt_verified": "FAIL"}
    assert len(account.attempts) == 1
    attempt = json.loads(next(tmp_path.rglob("setup-attempt.json")).read_text())
    assert attempt["error_code"] == "runtime_billing_evidence_missing"
    assert "private-token" not in json.dumps(attempt)


@pytest.mark.parametrize(
    "missing", ["runtime", "route_token", "config_revision", "model_capabilities"]
)
def test_incomplete_platform_contract_does_not_start_a_qualification(account, missing):
    account.snapshot.pop(missing)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_settings("41")
    assert exc.value.code == "runtime_configuration_required"
    assert account.attempts == []


def test_capacity_refresh_applies_to_new_tasks_and_preserves_original_binding(account):
    read = configuration.get_account_runtime_settings
    original = read("41", qualify=False).route
    limits = account.snapshot["model_capabilities"]
    limits["max_input_tokens"] = 29000
    same = read("41", previous=original.runtime_identity(), qualify=False).route
    assert same.identity == original.identity
    assert same.input_token_budget == 28000

    limits["max_input_tokens"] = 12000
    current = read("41", qualify=False).route
    assert (current.input_token_budget, current.max_output_tokens) == (12000, 4000)
    assert current.effective_context_window == 16000
    assert current.identity != original.identity
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        read("41", previous=original.runtime_identity(), qualify=False)
    assert exc.value.code == "runtime_changed"
    assert not account.attempts


def test_resume_pins_original_model_and_rejects_config_change_before_probe(account, monkeypatch):
    original = configuration.get_account_runtime_settings("41")
    previous = original.route.runtime_identity()
    account.snapshot["model"] = "new-default"
    monkeypatch.setattr(
        configuration,
        "enterprise_model_for_actor",
        lambda _: ("litellm", "chosen-model", "platform"),
    )
    selected = configuration.get_account_runtime_settings("41", qualify=False)
    assert selected.route.model == "litellm/chosen-model"
    same = configuration.get_account_runtime_settings("41", previous=previous)
    assert same.route.identity == original.route.identity
    assert account.calls[-1].url.params["provider"] == "litellm"
    assert account.calls[-1].url.params["model"] == "team-model"
    account.snapshot["config_revision"] = "8"
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_settings("41", previous=previous)
    assert exc.value.code == "runtime_changed"
    assert len(account.attempts) == 1
    account.snapshot["key_source"] = "user_override"
    with pytest.raises(configuration.RuntimeSetupError, match="密钥来源已变化"):
        configuration.get_account_runtime_settings("41", qualify=False)


def test_route_change_during_qualification_blocks_business_without_requalifying(
    account, monkeypatch
):
    from app.infrastructure.xiaox import qualification

    run = qualification.qualify_runtime

    def changed(settings, **kwargs):
        result = run(settings, **kwargs)
        account.snapshot["config_revision"] = "8"
        return result

    monkeypatch.setattr(qualification, "qualify_runtime", changed)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_settings("41")
    assert exc.value.code == "runtime_changed"
    assert len(account.attempts) == 1
    assert len(account.calls) == 2
    assert account.calls[-1].url.params["model"] == "team-model"


def test_first_setup_lock_prevents_concurrent_paid_probes(account, monkeypatch):
    from threading import Event

    entered, release = Event(), Event()

    def qualify(settings, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"ok": False}

    monkeypatch.setattr("app.infrastructure.xiaox.qualification.qualify_runtime", qualify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(configuration.get_account_runtime_settings, "41")
        try:
            assert entered.wait(5)
            assert configuration.get_account_runtime_status("41")["qualification"] == "in_progress"
            with pytest.raises(configuration.RuntimeSetupError) as exc:
                configuration.get_account_runtime_settings("41")
            assert exc.value.code == "runtime_qualification_in_progress"
        finally:
            release.set()
        with pytest.raises(configuration.RuntimeSetupError):
            first.result()


def test_background_credentials_are_looked_up_for_verified_owner_only(monkeypatch):
    monkeypatch.setattr("app.domain.context.current_request.get_current_request", lambda: None)
    token = Mock(return_value="private-owner-token")
    monkeypatch.setattr("app.fastapi_routes.market_account.latest_session_market_token", token)
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "forbidden-global-token")
    connection = configuration._account_connection("41")
    token.assert_called_once_with(user_id=41)
    assert connection.auth_token == "private-owner-token"
    assert connection.user_id is None
    token.return_value = ""
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration._account_connection("41")
    assert exc.value.code == "runtime_login_required"


def test_request_owner_mismatch_never_borrows_latest_token(monkeypatch):
    from app.application.market_llm import authentication

    monkeypatch.setattr("app.domain.context.current_request.get_current_request", lambda: object())
    monkeypatch.setattr(
        authentication,
        "load_session_ports",
        lambda: SimpleNamespace(
            session_id=lambda request: "real-login-session", owner=lambda sid: 42
        ),
    )
    latest = Mock(side_effect=AssertionError("must not borrow any token"))
    monkeypatch.setattr("app.fastapi_routes.market_account.latest_session_market_token", latest)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration._account_connection("41")
    assert exc.value.code == "runtime_login_required"
    latest.assert_not_called()


def test_unproven_scoped_account_cannot_be_borrowed_by_background_owner(monkeypatch):
    from app.infrastructure.llm.client import llm_client_scope

    stolen = SimpleNamespace(
        is_modstore_openai_compatible=True,
        adapter=SimpleNamespace(
            _connection=Mock(
                return_value=Connection("https://other-market.test", "private-owner-42", 42, 5)
            )
        ),
    )
    monkeypatch.setattr("app.domain.context.current_request.get_current_request", lambda: None)
    token = Mock(return_value="")
    monkeypatch.setattr("app.fastapi_routes.market_account.latest_session_market_token", token)
    network = Mock(side_effect=AssertionError("must not probe another owner's model"))
    monkeypatch.setattr(configuration, "resolve_account_route", network)
    with llm_client_scope(stolen, "private-model-42"):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            configuration.get_account_runtime_settings("41")
    assert exc.value.code == "runtime_login_required"
    token.assert_called_once_with(user_id=41)
    stolen.adapter._connection.assert_not_called()
    network.assert_not_called()


def test_host_upgrade_requalifies_same_route_and_preserves_original_receipt(account, monkeypatch):
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "a" * 40)
    original = configuration.get_account_runtime_settings("41")
    original_receipt = original.qualification_file.read_bytes()
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "b" * 40)
    upgraded = configuration.get_account_runtime_settings(
        "41", previous=original.route.runtime_identity()
    )
    assert upgraded.route.identity == original.route.identity
    assert upgraded.qualification_file != original.qualification_file
    assert len(account.attempts) == 2
    assert original.qualification_file.read_bytes() == original_receipt
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "a" * 40)
    restored = configuration.get_account_runtime_settings("41")
    assert restored.qualification_file == original.qualification_file
    assert len(account.attempts) == 2


def test_only_proven_zero_model_attempt_may_retry_automatically(account, monkeypatch):
    from app.infrastructure.xiaox import qualification

    real_test_runner = qualification.qualify_runtime
    attempts = []

    def unavailable(settings, **kwargs):
        attempts.append(settings)
        journal = settings.qualification_file.with_name("setup-attempt.json")
        assert json.loads(journal.read_text())["state"] == "started"
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600
        if len(attempts) == 1:
            return {
                "ok": False,
                "error_code": "runtime_qualification_unavailable",
                "model_attempted": False,
            }
        return real_test_runner(settings, **kwargs)

    monkeypatch.setattr(qualification, "qualify_runtime", unavailable)
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    restored = configuration.get_account_runtime_settings("41")
    assert restored.require_qualified() == restored.route
    assert len(attempts) == 2


def test_status_does_not_start_paid_qualification_or_create_state(account, tmp_path):
    status = configuration.get_account_runtime_status("41")
    assert status["qualification"] == "required"
    assert status["route"]["model"] == "litellm/team-model"
    assert account.attempts == []
    assert list(tmp_path.iterdir()) == []


def test_interrupted_or_corrupt_attempt_requires_explicit_retry(account, monkeypatch):
    from app.infrastructure.xiaox import qualification

    run = qualification.qualify_runtime

    def crashed(_settings, **_kwargs):
        raise KeyboardInterrupt("simulated process termination")

    monkeypatch.setattr(qualification, "qualify_runtime", crashed)
    with pytest.raises(KeyboardInterrupt):
        configuration.get_account_runtime_settings("41")
    monkeypatch.setattr(qualification, "qualify_runtime", run)
    status = configuration.get_account_runtime_status("41")
    assert status["qualification"] == "interrupted"
    assert status["error_code"] == "runtime_qualification_interrupted"
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert account.attempts == []
    staged = configuration.get_account_runtime_settings("41", qualify=False)
    staged.qualification_file.with_name("setup-attempt.json").write_text("{truncated")
    assert configuration.get_account_runtime_status("41")["qualification"] == "interrupted"
    configuration.get_account_runtime_settings("41", retry=True)
    assert configuration.get_account_runtime_status("41")["qualification"] == "passed"
    assert len(account.attempts) == 1


def test_storage_failure_stops_before_model_and_keeps_internal_path_private(account, monkeypatch):
    def fail(_path, _text):
        raise PermissionError("private-root/private-token")

    monkeypatch.setattr(configuration, "_write_private", fail)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_settings("41")
    assert exc.value.code == "runtime_storage_invalid"
    assert "private-root" not in str(exc.value) and "private-token" not in str(exc.value)
    assert account.attempts == []


def test_status_cannot_borrow_another_accounts_directory(account):
    first = configuration.get_account_runtime_settings("41")
    second, _scope, _prepared = configuration._account_runtime_inputs("42")
    second.runtime_root.symlink_to(first.runtime_root, target_is_directory=True)
    for check in (
        configuration.get_account_runtime_status,
        configuration.get_account_runtime_settings,
    ):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            check("42")
        assert exc.value.code == "runtime_storage_invalid"
    assert len(account.attempts) == 1


def test_transient_route_read_miss_is_retried_before_failing_the_turn(account, monkeypatch):
    real = configuration.resolve_account_route
    reads = []

    def flaky(*args, **kwargs):
        reads.append(1)
        if len(reads) == 1:
            raise httpx.ConnectError("private-gateway")
        return real(*args, **kwargs)

    monkeypatch.setattr(configuration, "resolve_account_route", flaky)
    settings = configuration.get_account_runtime_settings("41")
    assert settings.route.provider_id == "litellm"
    assert len(reads) >= 2
    assert account.attempts


def test_offline_configuration_stays_actionable_without_model_calls(account, monkeypatch):
    def offline(*_args, **_kwargs):
        raise httpx.ConnectError("private-account-token at private-gateway")

    monkeypatch.setattr(configuration, "resolve_account_route", offline)
    for check in (
        configuration.get_account_runtime_status,
        configuration.get_account_runtime_settings,
    ):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            check("41")
        assert exc.value.code == "runtime_platform_unavailable"
        assert "private-" not in str(exc.value)
    assert account.attempts == []


def test_actual_path_helper_keeps_status_read_only(account, monkeypatch, tmp_path):
    from app.utils.path_io.path_utils import get_desktop_state_dir

    target = tmp_path / "uninitialized-state"
    monkeypatch.setenv("XCAGI_DESKTOP_DATA_DIR", str(target))
    monkeypatch.setattr(configuration, "get_desktop_state_dir", get_desktop_state_dir)
    assert configuration.get_account_runtime_status("41")["qualification"] == "required"
    assert not target.exists() and account.attempts == []


def test_state_path_failure_is_safe_before_directory_setup(account, monkeypatch):
    def denied(**_kwargs):
        raise PermissionError("private-state-root")

    monkeypatch.setattr(configuration, "get_desktop_state_dir", denied)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_status("41")
    assert exc.value.code == "runtime_storage_invalid"
    assert "private-state-root" not in str(exc.value)
    assert account.attempts == []


@pytest.mark.parametrize("method", ["is_symlink", "exists", "is_dir"])
def test_directory_metadata_failure_is_safe_for_read_and_execution(account, monkeypatch, method):
    settings = configuration.get_account_runtime_settings("41")
    inspect = getattr(Path, method)

    def denied(path):
        if path == settings.runtime_root:
            raise PermissionError("private-account-state-directory")
        return inspect(path)

    monkeypatch.setattr(Path, method, denied)
    for check in (
        configuration.get_account_runtime_status,
        configuration.get_account_runtime_settings,
    ):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            check("41")
        assert exc.value.code == "runtime_storage_invalid"
        assert "private-account-state-directory" not in str(exc.value)
    assert len(account.attempts) == 1


def test_explicit_deployment_upgrade_qualifies_new_host_once(account, monkeypatch):
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "a" * 40)
    settings = configuration.get_account_runtime_settings("41")
    old_receipt = json.loads(settings.qualification_file.read_text())
    monkeypatch.setattr(configuration, "runtime_settings", lambda: settings)
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", "operator-runtime.json")
    monkeypatch.setattr("app.build_identity.verified_source_sha", lambda: "b" * 40)
    assert configuration.runtime_qualification_status(settings)["qualification"] == "required"
    configuration.get_deployment_runtime_settings()
    configuration.get_deployment_runtime_settings()
    assert len(account.attempts) == 2
    assert all(Path(ref).exists() for ref in old_receipt["evidence_refs"])


@pytest.mark.parametrize(
    "defect", ["missing_host", "partial_host", "malformed_sha", "bad_route", "started"]
)
def test_incomplete_previous_binding_never_triggers_silent_paid_retry(account, defect):
    account.succeeds = False
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    settings, _scope, _prepared = configuration._account_runtime_inputs("41")
    attempt = settings.qualification_file.with_name("setup-attempt.json")
    state = json.loads(attempt.read_text())
    if defect == "missing_host":
        state.pop("host_identity")
    elif defect == "partial_host":
        state["host_identity"] = {"git_sha": "b" * 40}
    elif defect == "malformed_sha":
        state["host_identity"]["git_sha"] = "unknown"
    elif defect == "bad_route":
        state["route_identity"] = "old-route"
    else:
        state["state"] = "started"
        state["host_identity"]["git_sha"] = "b" * 40
    attempt.write_text(json.dumps(state))
    account.succeeds = True
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_account_runtime_settings("41")
    assert len(account.attempts) == 1


def test_turn_timeout_is_bounded_by_chat_budget(monkeypatch):
    monkeypatch.delenv("XCAGI_RUNTIME_TURN_TIMEOUT_SEC", raising=False)
    assert configuration._turn_timeout_seconds() == 540
    monkeypatch.setenv("XCAGI_RUNTIME_TURN_TIMEOUT_SEC", "540")
    assert configuration._turn_timeout_seconds() == 540
    monkeypatch.setenv("XCAGI_RUNTIME_TURN_TIMEOUT_SEC", "9999")
    assert configuration._turn_timeout_seconds() == 570
    monkeypatch.setenv("XCAGI_RUNTIME_TURN_TIMEOUT_SEC", "1")
    assert configuration._turn_timeout_seconds() == 60


def test_upgrade_preserves_legacy_account_state_and_qualification(account, tmp_path):
    first = configuration.get_account_runtime_settings("41")
    assert first.runtime_root.parent == tmp_path / "codex-runtime"
    original = first.qualification_file.read_bytes()
    evidence = json.loads(original)
    files = {Path(ref): Path(ref).read_bytes() for ref in evidence["evidence_refs"]}
    resumed = configuration.get_account_runtime_settings("41")
    assert resumed.runtime_root == first.runtime_root
    assert resumed.qualification_file == first.qualification_file
    assert resumed.qualification_file.read_bytes() == original
    assert all(path.read_bytes() == data for path, data in files.items())
    assert not (tmp_path / "xiaox-runtime").exists()
    assert len(account.attempts) == 1


def test_xiaox_only_account_directory_is_reused_without_copy(account, tmp_path):
    settings, scope, _ = configuration._account_runtime_inputs("41")
    renamed = tmp_path / "xiaox-runtime" / scope
    renamed.mkdir(parents=True)
    marker = renamed / "original-state"
    marker.write_bytes(b"retain")
    first = configuration.get_account_runtime_settings("41")
    resumed = configuration.get_account_runtime_settings("41")
    assert first.runtime_root == resumed.runtime_root == renamed
    assert marker.read_bytes() == b"retain"
    assert not settings.runtime_root.exists()
    assert len(account.attempts) == 1


def test_split_account_state_blocks_before_paid_probe(account, tmp_path):
    settings, scope, _ = configuration._account_runtime_inputs("41")
    settings.runtime_root.mkdir(parents=True)
    renamed = tmp_path / "xiaox-runtime" / scope
    renamed.mkdir(parents=True)
    for path in (settings.runtime_root, renamed):
        (path / "original-state").write_bytes(b"retain")
    for check in (
        configuration.get_account_runtime_status,
        configuration.get_account_runtime_settings,
    ):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            check("41")
        assert exc.value.code == "runtime_storage_invalid"
    assert account.attempts == []
    for path in (settings.runtime_root, renamed):
        assert (path / "original-state").read_bytes() == b"retain"


def test_unselected_legacy_alias_symlink_blocks_account_setup(account, tmp_path):
    target = tmp_path / "other-state"
    target.mkdir()
    (tmp_path / "codex-runtime").symlink_to(target, target_is_directory=True)
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_account_runtime_settings("41")
    assert exc.value.code == "runtime_storage_invalid"
    assert account.attempts == []
    assert not list(target.iterdir())
