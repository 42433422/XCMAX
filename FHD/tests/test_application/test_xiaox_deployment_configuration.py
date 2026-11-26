"""Deployment qualification wiring; synthetic fixtures are not live acceptance."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.application.agent_runtime import configuration
from app.infrastructure.xiaox.policy import (
    QUALIFICATION_CHECKS,
    QualificationUpgradeRequired,
    RuntimePolicyError,
)
from app.infrastructure.xiaox.qualification import qualify_runtime
from tests.fixtures.xiaox_qualification import synthetic_qualification


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    root = tmp_path / "operator-runtime"
    state = SimpleNamespace(
        root=root,
        destination=root / "qualification.json",
        config=tmp_path / "operator.json",
        attempts=[],
        succeeds=True,
        publishes=True,
        change=None,
    )
    state.data = {
        "route": {
            "base_url": "http://127.0.0.1:19122/v1",
            "model": "operator-fixture-model",
            "provider_id": "operator-fixture",
            "upstream_vendor": "test-fixture",
            "context_window": 32000,
            "max_output_tokens": 4000,
        },
        "runtime_root": str(root),
        "qualification_file": str(state.destination),
        "turn_timeout_seconds": 47,
    }
    state.config.write_text(json.dumps(state.data))
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_CONFIG", str(state.config))

    def qualify(settings, **kwargs):
        state.attempts.append((settings, kwargs))
        assert (
            json.loads(settings.qualification_file.with_name("setup-attempt.json").read_text())[
                "state"
            ]
            == "started"
        )
        if state.succeeds and state.publishes:
            # Synthetic wiring fixture; never evidence of a live model passing.
            settings.qualification_file.write_text(
                json.dumps(
                    synthetic_qualification(settings.route, settings.qualification_file.parent)
                )
            )
        if state.change:
            state.change()
        return {"ok": state.succeeds, "error_code": "runtime_qualification_failed"}

    monkeypatch.setattr("app.infrastructure.xiaox.qualification.qualify_runtime", qualify)
    monkeypatch.setattr(
        configuration,
        "_account_connection",
        Mock(side_effect=AssertionError("deployment must not resolve an account")),
    )
    return state


@pytest.mark.parametrize("invalid", ["relative", "outside", "traversal"])
def test_runtime_loader_rejects_unbound_qualification_path(
    deployment, tmp_path, invalid
):
    paths = {
        "relative": "qualification.json",
        "outside": str(tmp_path / "other" / "qualification.json"),
        "traversal": str(deployment.root / ".." / "other" / "qualification.json"),
    }
    deployment.data["qualification_file"] = paths[invalid]
    deployment.config.write_text(json.dumps(deployment.data))
    with pytest.raises(RuntimePolicyError, match="qualification_file"):
        configuration.runtime_settings()
    assert deployment.attempts == []
    assert not deployment.root.exists()


def test_codex_compat_signing_failure_preserves_specific_recovery(monkeypatch):
    from app.infrastructure.modstore_transport import MarketModelError

    def reject(*_args, **_kwargs):
        failure = MarketModelError({"status": 503})
        failure.code = "CODEX_ROUTE_SIGNING_UNAVAILABLE"
        raise failure

    monkeypatch.setattr(configuration, "resolve_account_route", reject)
    with pytest.raises(configuration.RuntimeSetupError) as raised:
        configuration._prepared_route(None, None)
    assert raised.value.code == "runtime_configuration_required"
    assert "签发" in str(raised.value)


def _write_legacy_deployment_receipt(deployment):
    deployment.root.mkdir(mode=0o700)
    route = configuration.runtime_settings().route
    legacy = synthetic_qualification(
        route, deployment.root, checks=dict.fromkeys(QUALIFICATION_CHECKS[:-1], "PASS")
    )
    deployment.destination.write_text(json.dumps(legacy))
    deployment.destination.with_name("setup-attempt.json").write_text(
        json.dumps({"state": "passed", "route_identity": route.identity})
    )
    return route


def test_explicit_deployment_upgrades_original_route_and_reads_back_new_receipt(deployment):
    original_route = _write_legacy_deployment_receipt(deployment)
    original_config = deployment.config.read_bytes()
    original_evidence = deployment.root / "original-evidence.json"
    original_evidence.write_text("preserve original evidence")
    with pytest.raises(QualificationUpgradeRequired):
        configuration.runtime_settings().require_qualified()
    result = configuration.get_deployment_runtime_settings()
    assert result.require_qualified().identity == original_route.identity
    assert result.turn_timeout_seconds == 47
    assert len(deployment.attempts) == 1
    assert deployment.attempts[0][0].route == original_route
    assert deployment.attempts[0][1]["owner_scope"].startswith("deployment:")
    assert deployment.config.read_bytes() == original_config
    assert original_evidence.read_text() == "preserve original evidence"
    assert (
        json.loads(deployment.destination.read_text())["checks"]["multi_step_restart_continuation"]
        == "PASS"
    )
    assert configuration.get_deployment_runtime_settings(retry=True) == result
    assert len(deployment.attempts) == 1


@pytest.mark.parametrize("failure", ["runner_failed", "new_receipt_missing"])
def test_explicit_deployment_failure_keeps_evidence_and_does_not_rebill(deployment, failure):
    _write_legacy_deployment_receipt(deployment)
    previous = deployment.destination.read_bytes()
    deployment.succeeds = failure != "runner_failed"
    deployment.publishes = False
    for _ in range(2):
        with pytest.raises(
            configuration.RuntimeSetupError, match="runtime-check --deployment --retry"
        ):
            configuration.get_deployment_runtime_settings()
    assert len(deployment.attempts) == 1
    assert deployment.destination.read_bytes() == previous
    assert (
        json.loads(deployment.destination.with_name("setup-attempt.json").read_text())["state"]
        == "failed"
    )
    deployment.succeeds = deployment.publishes = True
    result = configuration.get_deployment_runtime_settings(retry=True)
    assert result.require_qualified() == result.route
    assert len(deployment.attempts) == 2


@pytest.mark.parametrize("missing", ["configuration", "credential"])
def test_explicit_deployment_requires_configuration_and_credential_before_probe(
    deployment, monkeypatch, missing
):
    if missing == "configuration":
        monkeypatch.delenv("XCAGI_AGENT_RUNTIME_CONFIG")
    else:
        deployment.data["route"].update(
            base_url="https://independent.example/v1", api_key_env="OPERATOR_FIXTURE_MODEL_KEY"
        )
        monkeypatch.delenv("OPERATOR_FIXTURE_MODEL_KEY", raising=False)
        deployment.config.write_text(json.dumps(deployment.data))
    with pytest.raises(RuntimePolicyError):
        configuration.get_deployment_runtime_settings(retry=True)
    assert not deployment.root.exists()
    assert deployment.attempts == []


@pytest.mark.parametrize("operation", ["stat", "mkdir"])
def test_deployment_storage_errors_remain_private_structured_cli_failures(
    deployment, monkeypatch, capsys, operation
):
    from app.cli.brain import main

    original = getattr(Path, operation)
    denied = deployment.destination if operation == "stat" else deployment.root

    def fail_storage(path, *args, **kwargs):
        if path == denied:
            raise PermissionError(13, "private-storage-denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, fail_storage)
    assert main(["--json", "runtime-check", "--deployment"]) == 1
    captured = capsys.readouterr()
    assert deployment.attempts == []
    assert captured.err == ""
    response = json.loads(captured.out)
    assert response["success"] is False and response["error_code"] == "runtime_storage_invalid"
    assert str(deployment.root) not in captured.out
    assert "private-storage-denied" not in captured.out


@pytest.mark.parametrize("existing_empty_root", [False, True])
def test_empty_deployment_directory_allows_its_first_qualification(deployment, existing_empty_root):
    if existing_empty_root:
        deployment.root.mkdir(mode=0o700)
    status = configuration.runtime_qualification_status(configuration.runtime_settings())
    assert status["qualification"] == "required" and status["retry_required"] is False
    settings = configuration.get_deployment_runtime_settings()
    assert settings.require_qualified() == settings.route
    assert len(deployment.attempts) == 1


@pytest.mark.parametrize(
    "invalid",
    [
        "outside",
        "relative",
        "root_symlink",
        "parent_symlink",
        pytest.param(
            "public_root",
            marks=pytest.mark.skipif(
                os.name != "posix", reason="POSIX directory permission contract"
            ),
        ),
        "directory",
    ],
)
def test_explicit_deployment_checks_paths_before_writes_without_chmod(
    deployment, tmp_path, invalid
):
    outside = tmp_path / "untouched"
    outside.mkdir(mode=0o755)
    if invalid == "outside":
        deployment.data["qualification_file"] = str(outside / "qualification.json")
    elif invalid == "relative":
        deployment.data["qualification_file"] = "qualification.json"
    elif invalid == "root_symlink":
        deployment.root.symlink_to(outside, target_is_directory=True)
    else:
        deployment.root.mkdir(mode=0o700)
        if invalid == "parent_symlink":
            (deployment.root / "evidence").symlink_to(outside, target_is_directory=True)
            deployment.data["qualification_file"] = str(deployment.root / "evidence" / "pass.json")
        elif invalid == "public_root":
            deployment.root.chmod(0o755)
        else:
            deployment.destination.mkdir()
    deployment.config.write_text(json.dumps(deployment.data))
    before = stat.S_IMODE(deployment.root.stat().st_mode) if deployment.root.exists() else None
    with pytest.raises(configuration.RuntimeSetupError, match="目录"):
        configuration.get_deployment_runtime_settings(retry=True)
    assert deployment.attempts == []
    assert list(outside.iterdir()) == []
    assert not deployment.destination.with_name("setup-attempt.json").exists()
    if before is None:
        assert not deployment.root.exists()
    else:
        assert stat.S_IMODE(deployment.root.stat().st_mode) == before


@pytest.mark.parametrize("changed", ["route", "root", "destination"])
def test_explicit_deployment_config_drift_cannot_report_qualification_success(deployment, changed):
    def change():
        if changed == "route":
            deployment.data["route"]["model"] = "different-model"
        else:
            key = "runtime_root" if changed == "root" else "qualification_file"
            deployment.data[key] += "-changed"
        deployment.config.write_text(json.dumps(deployment.data))

    deployment.change = change
    with pytest.raises(configuration.RuntimeSetupError) as exc:
        configuration.get_deployment_runtime_settings()
    assert exc.value.code == "runtime_changed"
    assert len(deployment.attempts) == 1


def test_explicit_deployment_retry_still_honors_existing_probe_lock(deployment):
    deployment.root.mkdir(mode=0o700)
    with configuration.FileLock(deployment.destination.with_name("setup.lock"), timeout=0):
        with pytest.raises(configuration.RuntimeSetupError) as exc:
            configuration.get_deployment_runtime_settings(retry=True)
    assert exc.value.code == "runtime_qualification_in_progress"
    assert deployment.attempts == []
    assert not deployment.destination.with_name("setup-attempt.json").exists()


def test_lost_model_response_preserves_attempt_and_never_automatically_rebills(
    deployment, monkeypatch
):
    from app.infrastructure.xiaox import qualification

    probes = []

    async def lost_response(settings, _scope, _probe):
        probes.append(settings.route.identity)
        raise httpx.ReadError("private-upstream-response-lost")

    monkeypatch.setattr(qualification, "qualify_runtime", qualify_runtime)
    monkeypatch.setattr(qualification, "verify_installation", lambda: None)
    monkeypatch.setattr(qualification, "_run_probe", lost_response)
    for _ in range(2):
        with pytest.raises(configuration.RuntimeSetupError):
            configuration.get_deployment_runtime_settings()
    assert len(probes) == 1
    attempt = json.loads(deployment.destination.with_name("setup-attempt.json").read_text())
    assert attempt["state"] == "failed" and attempt["model_attempted"] is True
    assert set(attempt["checks"]) == set(QUALIFICATION_CHECKS)
    assert not deployment.destination.exists()
    artifacts = list(deployment.root.glob("attempt-*/evidence.json"))
    assert len(artifacts) == 1 and json.loads(artifacts[0].read_text())["ok"] is False
    deployment.destination.with_name("setup-attempt.json").unlink()
    status = configuration.runtime_qualification_status(configuration.runtime_settings())
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_deployment_runtime_settings()
    assert len(probes) == 1
    assert status["qualification"] == "interrupted" and status["retry_required"] is True
    with pytest.raises(configuration.RuntimeSetupError):
        configuration.get_deployment_runtime_settings(retry=True)
    assert len(probes) == 2
