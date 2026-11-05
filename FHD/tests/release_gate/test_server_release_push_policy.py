import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent


def _run_bash(*args: str, env: dict[str, str], cwd: Path | None = None):
    return subprocess.run(
        ["bash", *args],
        cwd=cwd,
        env={**os.environ, **env},
        check=False,
        capture_output=True,
        text=True,
    )


def _tarball_release(tmp_path: Path, git_sha: str, **metadata: str):
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    artifact = out_dir / "fhd-full-1.0.0.0-test.tar.gz"
    artifact.write_bytes(b"server-release")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        "artifact": artifact.name,
        "sha256": artifact_sha,
        "version": "1.0.0.0",
        "git_sha": git_sha,
        "deploy_mode": "tarball",
        "admin_console_sha256": "a" * 64,
        "archive_verifier_sha256": hashlib.sha256(b"# reviewed fixture\n").hexdigest(),
        **metadata,
    }
    (out_dir / "fhd-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return out_dir, artifact, artifact_sha


def test_server_release_bundles_and_bootstraps_vendored_langgraph() -> None:
    pack = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")
    apply = (FHD_ROOT / "scripts/deploy/fhd-apply-release.sh").read_text(encoding="utf-8")

    for package in (
        "xcagi_langgraph_core",
        "xcagi_langgraph_checkpoint",
        "xcagi_langgraph_checkpoint_backends/checkpoint-sqlite",
        "xcagi_langgraph_checkpoint_backends/checkpoint-postgres",
        "xcagi_langgraph_prebuilt",
        "xcagi_langgraph_sdk",
    ):
        assert package in pack
        assert package in apply

    assert "requirements-langgraph-runtime.txt" in pack
    assert "requirements-langgraph-runtime.txt" in apply
    assert "xcagi_vendored_langgraph.pth" in apply and "_xcagi_root=next" in apply
    assert "assert_vendored_sources" in apply
    assert "FHD_SERVICE_PYTHON" in apply


def test_server_release_archive_strips_macos_extended_attributes() -> None:
    pack = (FHD_ROOT / "scripts/deploy/fhd-pack-release.sh").read_text(encoding="utf-8")

    assert "tar --no-xattrs" in pack
    assert "TAR_XATTR_ARGS+=(--no-xattrs)" in pack
    assert 'COPYFILE_DISABLE=1 tar "${TAR_XATTR_ARGS[@]}"' in pack


def test_normal_cvm_release_skips_optional_image_archive() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert 'PUSH_IMAGE_TAR="${FHD_PUSH_IMAGE_TAR:-auto}"' in script
    assert '"${DEPLOY_MODE:-tarball}" == "image"' in script
    assert '[[ -f "$IMAGE_TAR" && "$PUSH_IMAGE_TAR" == "1" ]]' in script
    assert 'deploy_emit push skipped "artifact=fhd-api-image.tar.gz reason=optional"' in script


def test_cvm_upload_prefers_resumable_rsync_and_retains_partial() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert 'rsync_resume_flag="--append"' in script
    assert 'rsync_resume_flag="--append-verify"' in script
    assert 'rsync --archive --partial "$rsync_resume_flag" --timeout=180' in script
    assert 'transfer_mode="rsync"' in script
    assert "partial retained" in script
    assert "RSYNC_SHELL" in script


@pytest.fixture
def transport(tmp_path: Path, monkeypatch) -> Path:
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    calls = tmp_path / "commands"
    ssh_body = """cmd=${!#}
case "$cmd" in
  *curl*)
    attempts=$(cat "$HEALTH_ATTEMPTS" 2>/dev/null || printf '0')
    attempts=$((attempts + 1))
    printf '%s' "$attempts" > "$HEALTH_ATTEMPTS"
    if [ "$attempts" -lt 2 ]; then exit 1; fi
    printf '%s\\n' "$HEALTH_PAYLOAD" ;;
  *REMOTE_SZ*) printf 'OK_MOVED\\n' ;;
esac
"""
    for name in ("scp", "rsync", "ssh"):
        executable = mock_bin / name
        executable.write_text(
            '#!/usr/bin/env bash\nprintf "%s %s\\n" "$0" "$*" >> "$DEPLOY_COMMANDS"\n'
            + (ssh_body if name == "ssh" else "")
        )
        executable.chmod(0o755)
    # Transport tests isolate Git/source attestation; the bootstrap tests exercise real Git.
    git = mock_bin / "git"
    git.write_text("#!/bin/sh\ncase \"$*\" in *show*) printf '# reviewed fixture\\n';; esac\n")
    git.chmod(0o755)
    for key, value in {
        "PATH": f"{mock_bin}:{os.environ['PATH']}",
        "DEPLOY_COMMANDS": str(calls),
        "HEALTH_ATTEMPTS": str(tmp_path / "health-attempts"),
        "FHD_SKIP_PACK": "1",
        "FHD_PUSH_HOST": "example.invalid",
        "FHD_PUSH_IMAGE_TAR": "0",
        "FHD_PUSH_APPLY_NOW": "0",
    }.items():
        monkeypatch.setenv(key, value)
    return calls


@pytest.mark.parametrize(
    "preserve,apply,code", [("0", "0", 0), ("1", "0", 64), ("invalid", "1", 64)]
)
def test_tarball_push_does_not_scp_optional_image_archive(
    tmp_path: Path, transport: Path, preserve: str, apply: str, code: int
) -> None:
    out_dir, artifact, _ = _tarball_release(tmp_path, "a" * 40)
    (out_dir / "fhd-api-image.tar.gz").write_bytes(b"optional-image")
    result = _run_bash(
        str(FHD_ROOT / "scripts/deploy/fhd-push-release.sh"),
        cwd=FHD_ROOT,
        env={
            "FHD_RELEASE_OUT_DIR": str(out_dir),
            "XCMAX_PRESERVE_RELEASE_HISTORY": preserve,
            "FHD_PUSH_APPLY_NOW": apply,
        },
    )
    assert result.returncode == code, result.stderr
    if code:
        assert not transport.exists()
        return
    call_log = transport.read_text()
    assert artifact.name in call_log
    assert "fhd-manifest.json" in call_log
    assert "fhd-api-image.tar.gz" not in call_log
    assert "跳过可选镜像归档" in result.stdout


def test_server_release_is_retained_by_version_and_full_sha_before_pointer_switch() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert "/var/www/update/releases/builds/${VERSION}/${GIT_SHA}/server" in script
    assert 'atomic_upload "$TARBALL" "${IMMUTABLE_REMOTE_DIR}/${ARTIFACT}"' in script
    assert 'atomic_upload "$MANIFEST" "${IMMUTABLE_REMOTE_DIR}/fhd-manifest.json"' in script
    assert (
        'names = [artifact] + (["fhd-api-image.tar.gz"] if image == "1" else []) + ["fhd-manifest.json"]'
        in script
    )
    assert script.index('atomic_upload "$MANIFEST"') < script.index("def bootstrap_promote(")


@pytest.mark.parametrize("preserve", ["0", "1"])
@pytest.mark.parametrize("wrong_field", ["", "git_sha", "artifact_sha256", "admin_console_sha256"])
def test_tarball_apply_ignores_optional_image_digest_but_verifies_artifact(
    tmp_path: Path,
    preserve: str,
    transport: Path,
    wrong_field: str,
) -> None:
    out_dir, _, artifact_sha = _tarball_release(
        tmp_path,
        "b" * 40,
        image="ghcr.io/example/fhd-api",
        image_digest="sha256:" + "c" * 64,
        admin_console_sha256="d" * 64,
    )

    health_payload = json.dumps(
        {
            "build": {
                "git_sha": "b" * 40,
                "artifact_sha256": artifact_sha,
                "admin_console_sha256": "d" * 64,
            }
        }
    )
    if wrong_field:
        payload = json.loads(health_payload)
        payload["build"][wrong_field] = "e" * len(payload["build"][wrong_field])
        health_payload = json.dumps(payload)
    health_attempts = tmp_path / "health-attempts"

    result = _run_bash(
        str(FHD_ROOT / "scripts/deploy/fhd-push-release.sh"),
        cwd=FHD_ROOT,
        env={
            "HEALTH_PAYLOAD": health_payload,
            "HEALTH_ATTEMPTS": str(health_attempts),
            "XCMAX_PRESERVE_RELEASE_HISTORY": preserve,
            "FHD_RELEASE_OUT_DIR": str(out_dir),
            "FHD_PUSH_APPLY_NOW": "1",
            "FHD_PUSH_HEALTH_RETRIES": "3",
            "FHD_PUSH_HEALTH_INTERVAL": "0",
        },
    )

    if wrong_field:
        assert result.returncode != 0
        assert "prune_release_cache.py" not in transport.read_text()
        assert "远端已应用并通过" not in result.stdout
        return
    assert result.returncode == 0, result.stderr
    assert health_attempts.read_text(encoding="utf-8") == "2"
    assert '"git_sha": "' + "b" * 40 in result.stdout
    assert "image digest mismatch" not in result.stderr
    commands = transport.read_text()
    assert f"XCMAX_PRESERVE_RELEASE_HISTORY={preserve}" in commands
    assert ("prune_release_cache.py" in commands) == (preserve == "0")


@pytest.mark.parametrize("preserve", ["0", "1"])
def test_tarball_backup_history_retention(tmp_path: Path, preserve: str) -> None:
    for name in ("pre-20261018-000000", "pre-20261019-000000", "pre-20261020-000000"):
        (tmp_path / name).mkdir()
    source = (FHD_ROOT / "scripts/deploy/fhd-apply-release.sh").read_text()
    start = source.index('if [[ "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" != 1 ]]; then')
    block = source[start : source.index("\nrollback_from_backup()", start)]
    result = _run_bash(
        "-c",
        "log() { :; }; " + block,
        env={
            "BACKUP_ROOT": str(tmp_path),
            "SCRIPT_DIR": str(FHD_ROOT / "scripts/deploy"),
            "FHD_BACKUP_RETAIN": "2",
            "XCMAX_PRESERVE_RELEASE_HISTORY": preserve,
        },
    )
    assert result.returncode == 0, result.stderr
    assert len(list(tmp_path.iterdir())) == (3 if preserve == "1" else 2)


def test_release_identity_verifier_requires_artifact_when_supplied() -> None:
    verifier = FHD_ROOT / "scripts/deploy/lib/verify_release_identity.sh"
    payload = json.dumps(
        {
            "build": {
                "artifact_sha256": "a" * 64,
                "git_sha": "b" * 40,
                "image_digest": "sha256:" + "c" * 64,
            }
        }
    )
    command = (
        f"source {verifier!s}; "
        'verify_release_identity_payload "$PAYLOAD" '
        f"{'b' * 40} sha256:{'c' * 64} {'a' * 64}"
    )
    passed = _run_bash("-c", command, env={"PAYLOAD": payload})
    failed = _run_bash("-c", command.replace("a" * 64, "d" * 64), env={"PAYLOAD": payload})

    assert passed.returncode == 0, passed.stderr
    assert failed.returncode != 0
    assert "artifact SHA256 mismatch" in failed.stderr


def test_ci_requires_explicit_manual_opt_in_for_image_archive() -> None:
    source = (FHD_ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8")
    published = (REPO_ROOT / ".github/workflows/fhd-ci-cd.yml").read_text(encoding="utf-8")

    for workflow in (source, published):
        assert "Stamp production environment approval into manifest" not in workflow
        assert "Could not resolve the production environment reviewer" not in workflow
        assert "autonomy_approval" not in workflow
        assert "\n    environment:" not in workflow
        assert "push_image_tar:" in workflow
        assert (
            "group: cvm-push-release-${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.release_channel || (contains(github.ref, '-rc') "
            "&& 'staging' || 'stable') }}"
        ) in workflow
        assert "cancel-in-progress: false" in workflow
        assert (
            "FHD_PUSH_IMAGE_TAR: ${{ github.event_name == 'workflow_dispatch' "
            "&& inputs.push_image_tar && '1' || '0' }}"
        ) in workflow
        assert "FHD_PUSH_APPLY_NOW:" in workflow
        assert "== 'staging' && '1' || '0'" in workflow
        assert 'FHD_CVM_PUSH_TIMEOUT: "75m"' in workflow
        assert "timeout-minutes: 90" in workflow
        assert "security_scan_run_id:" in workflow
        assert "previous_security_scan_run_id:" in workflow
        assert "verify_security_scan_pair.py" in workflow
        assert "inputs.release_channel == 'stable'" in workflow
        cvm_job = workflow.split("  cvm-push-release:", 1)[1].split(
            "  dispatch-evolution-after-cvm:", 1
        )[0]
        assert "startsWith(github.ref, 'refs/tags/FHD/v')" not in cvm_job


@pytest.mark.parametrize(
    "overrides,valid",
    [
        ({}, True),
        ({"RELEASE_SHA": ""}, False),
        ({"RELEASE_SHA": "main"}, False),
        ({"RELEASE_SHA": "A" * 40}, False),
        ({"RELEASE_SHA": "a" * 39}, False),
        ({"CURRENT_SECURITY_SCAN_RUN_ID": ""}, False),
        ({"PREVIOUS_SECURITY_SCAN_RUN_ID": ""}, False),
        ({"CURRENT_SECURITY_SCAN_RUN_ID": "0"}, False),
        ({"PREVIOUS_SECURITY_SCAN_RUN_ID": "-1"}, False),
        ({"CURRENT_SECURITY_SCAN_RUN_ID": "123; exit 0"}, False),
        ({"RELEASE_CHANNEL": ""}, False),
        ({"RELEASE_CHANNEL": "preview"}, False),
        (
            {
                "RELEASE_CHANNEL": "staging",
                "CURRENT_SECURITY_SCAN_RUN_ID": "",
                "PREVIOUS_SECURITY_SCAN_RUN_ID": "",
            },
            True,
        ),
        ({"RELEASE_CHANNEL": "staging", "RELEASE_SHA": ""}, False),
    ],
)
def test_cvm_inputs_fail_before_checkout_and_expensive_jobs(tmp_path, overrides, valid):
    for path in (
        FHD_ROOT / ".github/workflows/ci-cd.yml",
        REPO_ROOT / ".github/workflows/fhd-ci-cd.yml",
    ):
        jobs = yaml.safe_load(path.read_text())["jobs"]
        step = jobs["guard-temp-scripts"]["steps"][0]
        assert step["name"] == "Validate explicit CVM release inputs"
        assert (
            step["if"] == "github.event_name == 'workflow_dispatch' && inputs.push_to_cvm == true"
        )
        assert step["working-directory"] == "."
        assert "guard-temp-scripts" in jobs["backend-test"]["needs"]
        result = _run_bash(
            "-c",
            step["run"],
            cwd=tmp_path,
            env={
                "RELEASE_SHA": "a" * 40,
                "RELEASE_CHANNEL": "stable",
                "CURRENT_SECURITY_SCAN_RUN_ID": "123",
                "PREVIOUS_SECURITY_SCAN_RUN_ID": "123",
                **overrides,
            },
        )
        assert (result.returncode == 0) is valid, result.stdout + result.stderr
        if not valid:
            assert "::error::" in result.stdout


def test_evolution_dispatch_runs_before_any_checkout_directory_exists() -> None:
    source = yaml.safe_load((FHD_ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8"))
    published = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/fhd-ci-cd.yml").read_text(encoding="utf-8")
    )

    for workflow in (source, published):
        events = workflow.get("on", workflow.get(True))
        dispatch_input = events["workflow_dispatch"]["inputs"]["dispatch_evolution"]
        assert dispatch_input["type"] == "boolean"
        assert dispatch_input["default"] is True
        job = workflow["jobs"]["dispatch-evolution-after-cvm"]
        assert job["needs"] == ["cvm-push-release"]
        assert job["if"].split(" && ") == [
            "github.event_name == 'workflow_dispatch'",
            "github.ref == 'refs/heads/main'",
            "inputs.push_to_cvm == true",
            "inputs.dispatch_evolution == true",
            "needs.cvm-push-release.result == 'success'",
        ]
        assert job["steps"][0]["working-directory"] == "."
        assert "actions/checkout" not in str(job["steps"])


def test_autonomous_ci_workflows_have_no_environment_approval_gate() -> None:
    workflow_paths = [
        REPO_ROOT / ".github/workflows/fhd-ci-cd.yml",
        REPO_ROOT / ".github/workflows/fhd-employee-smoke-gate.yml",
        REPO_ROOT / ".github/workflows/fhd-release-gate-ci.yml",
        REPO_ROOT / ".github/workflows/modstore-prod-deploy.yml",
        FHD_ROOT / ".github/workflows/ci-cd.yml",
        FHD_ROOT / ".github/workflows/employee-smoke-gate.yml",
        FHD_ROOT / ".github/workflows/release-gate-ci.yml",
    ]

    for path in workflow_paths:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (workflow.get("jobs") or {}).items():
            assert "environment" not in job, f"{path}:{job_name} still has an approval gate"


def test_deploy_validates_autonomy_without_rewriting_server_configuration(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/fhd-deploy.yml").read_text())
    events = workflow.get("on", workflow.get(True))
    preserve = events["workflow_dispatch"]["inputs"]["preserve_release_history"]
    assert (preserve["type"], preserve["default"]) == ("boolean", False)
    steps = workflow["jobs"]["cvm-rolling"]["steps"]
    apply = next(s for s in steps if s["name"] == "SSH rolling restart / apply")
    assert apply["env"]["PRESERVE_RELEASE_HISTORY"] == (
        "${{ inputs.preserve_release_history && '1' || '0' }}"
    )
    assert (
        'case "${PRESERVE_RELEASE_HISTORY}" in 0|1) export XCMAX_PRESERVE_RELEASE_HISTORY='
        in apply["run"]
    )
    assert 'export FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS="360"' in apply["run"]
    updater = (FHD_ROOT / "scripts/deploy/fhd-auto-update.sh").read_text()
    assert 'case "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" in 0|1)' in updater
    assert '"XCMAX_PRESERVE_RELEASE_HISTORY=${XCMAX_PRESERVE_RELEASE_HISTORY:-0}"' in updater
    assert 'if XCMAX_PRESERVE_RELEASE_HISTORY="${XCMAX_PRESERVE_RELEASE_HISTORY:-0}"' in updater
    check = next(
        s for s in steps if s["name"] == "Validate existing autonomy runtime configuration"
    )
    assert "production" in check["if"] and "apply-latest" in check["if"]
    remote = tmp_path / "fhd-full.env"
    original = (
        "AUTONOMY_WEBHOOK_TOKEN=server-only\nXCAGI_AUTONOMY_MEDIUM_RISK_POLICY=require_human\n"
    )
    remote.write_text(original)
    for name, body in {
        "ssh": 'bash -c "${@: -1}"',
        "systemctl": 'test "$*" = "is-active --quiet fhd-full.service"',
        "curl": 'exit "${HEALTH_EXIT:-0}"',
    }.items():
        executable = tmp_path / name
        executable.write_text("#!/bin/bash\n" + body + "\n")
        executable.chmod(0o700)
    script = check["run"].replace("/root/fhd-full.env", str(remote))
    env = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "FHD_PUSH_SSH_KEY_RAW": "test-only",
        "AUTONOMY_WEBHOOK_TOKEN": "callback-only",
    }
    for token, health, expected in (
        ("callback-only", "0", 0),
        ("", "0", 1),
        ("callback-only", "1", 1),
    ):
        result = _run_bash(
            "-c",
            script,
            env={**env, "AUTONOMY_WEBHOOK_TOKEN": token, "HEALTH_EXIT": health},
        )
        assert result.returncode == expected
        assert remote.read_text() == original
        assert "server-only" not in result.stdout + result.stderr
    remote.unlink()
    assert _run_bash("-c", script, env=env).returncode != 0
    assert steps.index(check) < next(
        i
        for i, s in enumerate(steps)
        if s["name"] == "Authorize exact production release in autonomy ledger"
    )


def test_production_deploy_requires_human_environment_approval() -> None:
    deploy = (REPO_ROOT / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")
    assert "release_sha:" in deploy
    assert "security_scan_run_id:" in deploy
    assert "previous_security_scan_run_id:" in deploy
    assert "ref: ${{ inputs.release_sha }}" in deploy
    assert "verify_security_scan_pair.py" in deploy
    assert 'if [ "${ACTION_ID}" != "release:${RELEASE_SHA}" ]' in deploy
    assert "report-autonomy-failure:" in deploy
    assert "needs: cvm-rolling" in deploy
    assert "needs['cvm-rolling'].result != 'success'" in deploy
    assert 'decision="execution_failed"' in deploy
    assert "Autonomy action was already terminal" in deploy
    assert "\n    environment:\n      name: ${{ inputs.environment }}" in deploy
    assert "actions/runs/${GITHUB_RUN_ID}/approvals" not in deploy
    assert "Resume approved autonomy action" not in deploy
    assert "XCAGI_AUTONOMY_MEDIUM_RISK_POLICY=auto_approve" not in deploy
    assert "Authorize exact production release in autonomy ledger" in deploy
    assert "action_id=release:<40-char git sha>" in deploy
    assert 'decision:"approved",defer_execution:true' in deploy
    assert 'approval_source": "autonomy_approval_ledger"' not in deploy
    assert "fhd-deploy-bootstrap" in deploy
    assert 'tar -xzf "\\$TARBALL"' in deploy
    assert 'AUTO="\\$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"' in deploy
    assert 'export FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS="360"' in deploy
    assert 'DEPLOYED_SHA="\\$(cat "${DEPLOY_ROOT}/.deploy-git-sha"' in deploy
    assert "Health SHA not converged" in deploy


def test_forced_self_maintenance_survives_its_own_service_restart() -> None:
    script = (FHD_ROOT / "scripts/deploy/force_self_maintenance_remote.sh").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".github/workflows/fhd-force-self-maintenance.yml").read_text(
        encoding="utf-8"
    )

    inprocess_call = script.index("if run_inprocess_with_live_env; then")
    http_call = script.index("if choose_base_via_http; then")
    assert inprocess_call < http_call
    assert 'REASON_FILE="${2:?reason_file}"' in script
    assert 'TOKEN_FILE="${3:-}"' in script
    assert 'rm -f -- "$REASON_FILE"' in script
    assert 'rm -f -- "$TOKEN_FILE"' in script
    assert script.count('status == "completed" or status.startswith("completed_")') == 2
    assert "status not in fail_statuses" not in script
    assert 'print("1" if success else "0")' in script
    assert "raise SystemExit(0 if success else 3)" in script
    assert "timeout-minutes: 120" in workflow
    assert 'SSH_OPTS=(-i "$KEY_FILE"' in workflow
    assert 'SCP_OPTS=(-i "$KEY_FILE"' in workflow
    assert workflow.count("-o ServerAliveInterval=30") == 2
    assert workflow.count("-o ServerAliveCountMax=120") == 2
    assert workflow.count("-o TCPKeepAlive=yes") == 2
    assert 'ssh "${SSH_OPTS[@]}"' in workflow
    assert workflow.count('scp "${SCP_OPTS[@]}"') == 3


def test_forced_self_maintenance_does_not_put_secret_or_reason_in_ssh_argv() -> None:
    workflow = (REPO_ROOT / ".github/workflows/fhd-force-self-maintenance.yml").read_text(
        encoding="utf-8"
    )

    assert 'printf \'%s\' "$LOOP_REASON" > "$LOCAL_REASON_FILE"' in workflow
    assert 'printf \'%s\' "$OPS_TOKEN" > "$LOCAL_TOKEN_FILE"' in workflow
    assert "'${LOOP_REASON}'" not in workflow
    assert "'${OPS_TOKEN}'" not in workflow
    assert "'${REMOTE_REASON_FILE}' '${REMOTE_TOKEN_FILE}'" in workflow
