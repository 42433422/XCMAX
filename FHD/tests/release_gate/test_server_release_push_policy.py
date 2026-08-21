import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = FHD_ROOT.parent


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
    assert "xcagi_vendored_langgraph.pth" in apply
    assert "assert_vendored_sources" in apply
    assert "FHD_SERVICE_PYTHON" in apply


def test_normal_cvm_release_skips_optional_image_archive() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert 'PUSH_IMAGE_TAR="${FHD_PUSH_IMAGE_TAR:-auto}"' in script
    assert '"${DEPLOY_MODE:-tarball}" == "image"' in script
    assert '[[ -f "$IMAGE_TAR" && "$PUSH_IMAGE_TAR" == "1" ]]' in script
    assert 'deploy_emit push skipped "artifact=fhd-api-image.tar.gz reason=optional"' in script


def test_cvm_upload_prefers_resumable_rsync_and_retains_partial() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert "rsync --archive --partial --append-verify --timeout=180" in script
    assert 'transfer_mode="rsync"' in script
    assert "partial retained" in script
    assert "RSYNC_SHELL" in script


def test_tarball_push_does_not_scp_optional_image_archive(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    artifact = out_dir / "fhd-full-1.0.0.0-test.tar.gz"
    artifact.write_bytes(b"server-release")
    (out_dir / "fhd-api-image.tar.gz").write_bytes(b"optional-image")
    (out_dir / "fhd-manifest.json").write_text(
        json.dumps(
            {
                "artifact": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "version": "1.0.0.0",
                "git_sha": "test-sha",
                "deploy_mode": "tarball",
                "admin_console_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    calls = tmp_path / "calls.log"
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    for name, body in {
        "scp": '#!/usr/bin/env bash\nprintf "scp %s\\n" "$*" >> "$CALLS_LOG"\n',
        "rsync": '#!/usr/bin/env bash\nprintf "rsync %s\\n" "$*" >> "$CALLS_LOG"\n',
        "ssh": (
            '#!/usr/bin/env bash\nprintf "ssh %s\\n" "$*" >> "$CALLS_LOG"\nprintf \'OK_MOVED\\n\'\n'
        ),
    }.items():
        executable = mock_bin / name
        executable.write_text(body, encoding="utf-8")
        executable.chmod(0o755)

    result = subprocess.run(
        ["bash", str(FHD_ROOT / "scripts/deploy/fhd-push-release.sh")],
        cwd=FHD_ROOT,
        env={
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "CALLS_LOG": str(calls),
            "FHD_SKIP_PACK": "1",
            "FHD_RELEASE_OUT_DIR": str(out_dir),
            "FHD_PUSH_HOST": "example.invalid",
            "FHD_PUSH_IMAGE_TAR": "0",
            "FHD_PUSH_APPLY_NOW": "0",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    call_log = calls.read_text(encoding="utf-8")
    assert artifact.name in call_log
    assert "fhd-manifest.json" in call_log
    assert "fhd-api-image.tar.gz" not in call_log
    assert "跳过可选镜像归档" in result.stdout


def test_strict_push_applies_and_verifies_exact_sha() -> None:
    script = (FHD_ROOT / "scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")

    assert "FHD_PUSH_APPLY_NOW:-" in script
    assert "FHD_CVM_PUSH_STRICT:-false" in script
    assert "FHD_MANIFEST_PATH=%q" in script
    assert "fhd-release-bootstrap" in script
    assert "verify_release_identity_payload" in script
    assert '"$SHA256"' in script
    assert '"${DEPLOY_MODE:-tarball}" == "image"' in script
    assert '"$EXPECTED_RUNTIME_IMAGE_DIGEST"' in script
    assert '"$ADMIN_CONSOLE_SHA256"' in script
    assert "FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS=%q" in script
    assert 'HEALTH_RETRIES="${FHD_PUSH_HEALTH_RETRIES:-120}"' in script
    assert "for ((attempt = 1; attempt <= HEALTH_RETRIES; attempt++))" in script
    assert "remote_identity_mismatch" in script


def test_tarball_apply_ignores_optional_image_digest_but_verifies_artifact(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    artifact = out_dir / "fhd-full-1.0.0.0-test.tar.gz"
    artifact.write_bytes(b"server-release")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (out_dir / "fhd-manifest.json").write_text(
        json.dumps(
            {
                "artifact": artifact.name,
                "sha256": artifact_sha,
                "version": "1.0.0.0",
                "git_sha": "b" * 40,
                "deploy_mode": "tarball",
                "image": "ghcr.io/example/fhd-api",
                "image_digest": "sha256:" + "c" * 64,
                "admin_console_sha256": "d" * 64,
            }
        ),
        encoding="utf-8",
    )

    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    scp = mock_bin / "scp"
    scp.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    scp.chmod(0o755)
    rsync = mock_bin / "rsync"
    rsync.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    rsync.chmod(0o755)
    ssh = mock_bin / "ssh"
    ssh.write_text(
        "#!/usr/bin/env bash\n"
        "cmd=${!#}\n"
        'case "$cmd" in\n'
        "  *curl*)\n"
        "    attempts=$(cat \"$HEALTH_ATTEMPTS\" 2>/dev/null || printf '0')\n"
        "    attempts=$((attempts + 1))\n"
        '    printf \'%s\' "$attempts" > "$HEALTH_ATTEMPTS"\n'
        '    if [ "$attempts" -lt 2 ]; then exit 1; fi\n'
        "    printf '%s\\n' \"$HEALTH_PAYLOAD\"\n"
        "    ;;\n"
        "  *REMOTE_SZ*) printf 'OK_MOVED\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    health_payload = json.dumps(
        {
            "build": {
                "git_sha": "b" * 40,
                "artifact_sha256": artifact_sha,
                "admin_console_sha256": "d" * 64,
            }
        }
    )
    health_attempts = tmp_path / "health-attempts"

    result = subprocess.run(
        ["bash", str(FHD_ROOT / "scripts/deploy/fhd-push-release.sh")],
        cwd=FHD_ROOT,
        env={
            **os.environ,
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "HEALTH_PAYLOAD": health_payload,
            "HEALTH_ATTEMPTS": str(health_attempts),
            "FHD_SKIP_PACK": "1",
            "FHD_RELEASE_OUT_DIR": str(out_dir),
            "FHD_PUSH_HOST": "example.invalid",
            "FHD_PUSH_IMAGE_TAR": "0",
            "FHD_PUSH_APPLY_NOW": "1",
            "FHD_PUSH_HEALTH_RETRIES": "3",
            "FHD_PUSH_HEALTH_INTERVAL": "0",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert health_attempts.read_text(encoding="utf-8") == "2"
    assert '"git_sha": "' + "b" * 40 in result.stdout
    assert "image digest mismatch" not in result.stderr


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
    passed = subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, "PAYLOAD": payload},
        check=False,
        capture_output=True,
        text=True,
    )
    failed = subprocess.run(
        ["bash", "-c", command.replace("a" * 64, "d" * 64)],
        env={**os.environ, "PAYLOAD": payload},
        check=False,
        capture_output=True,
        text=True,
    )

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


def test_evolution_dispatch_runs_before_any_checkout_directory_exists() -> None:
    source = yaml.safe_load((FHD_ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8"))
    published = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/fhd-ci-cd.yml").read_text(encoding="utf-8")
    )

    for workflow in (source, published):
        job = workflow["jobs"]["dispatch-evolution-after-cvm"]
        assert job["steps"][0]["working-directory"] == "."
        assert "actions/checkout" not in str(job["steps"])


def test_autonomous_ci_workflows_have_no_environment_approval_gate() -> None:
    workflow_paths = [
        REPO_ROOT / ".github/workflows/fhd-ci-cd.yml",
        REPO_ROOT / ".github/workflows/fhd-deploy.yml",
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


def test_autonomy_resume_waits_for_http_ready_after_secret_sync() -> None:
    workflow = (REPO_ROOT / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")

    sync_step = workflow.split("- name: Sync autonomy runtime configuration", 1)[1].split(
        "- name: SSH rolling restart / apply", 1
    )[0]
    assert "systemctl restart fhd-full.service" in sync_step
    assert "for attempt in $(seq 1 30)" in sync_step
    assert ('curl --noproxy "*" -sf --max-time 5 http://127.0.0.1:5100/api/health') in sync_step
    assert "did not become HTTP-ready after autonomy config sync" in sync_step


def test_autonomy_deploy_has_no_human_environment_approval() -> None:
    deploy = (REPO_ROOT / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")
    assert "report-autonomy-failure:" in deploy
    assert "needs: cvm-rolling" in deploy
    assert "needs['cvm-rolling'].result != 'success'" in deploy
    assert 'decision="execution_failed"' in deploy
    assert "Autonomy action was already terminal" in deploy
    assert "\n    environment:\n" not in deploy
    assert "actions/runs/${GITHUB_RUN_ID}/approvals" not in deploy
    assert "Resume approved autonomy action" not in deploy
    assert "XCAGI_AUTONOMY_MEDIUM_RISK_POLICY=auto_approve" in deploy
    assert "Authorize exact production release in autonomy ledger" in deploy
    assert "action_id=release:<40-char git sha>" in deploy
    assert 'decision:"approved",defer_execution:true' in deploy
    assert 'approval_source": "autonomy_approval_ledger"' not in deploy
    assert "fhd-deploy-bootstrap" in deploy
    assert 'tar -xzf "\\$TARBALL"' in deploy
    assert 'AUTO="\\$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"' in deploy


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
