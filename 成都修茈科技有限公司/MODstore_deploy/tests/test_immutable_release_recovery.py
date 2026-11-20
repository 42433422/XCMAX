from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location(
    "immutable_release_recovery", SCRIPTS / "immutable_release_recovery.py"
)
assert spec and spec.loader
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def build_identity(char):
    sha = char * 40
    return {
        "git_sha": sha,
        "artifact_sha256": char * 64,
        "image_digest": "",
        "product_version": "1.0.0.7",
        "release_id": f"xcagi-1.0.0.7-{sha}",
    }


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "_payment_present", lambda: False)
    expected, target = build_identity("a"), build_identity("b")
    releases = tmp_path / "releases"
    for value in (expected, target, build_identity("c")):
        root = releases / value["git_sha"]
        root.mkdir(parents=True)
        (root / ".xcmax-release.json").write_text(json.dumps(value))
    current = tmp_path / "current"
    current.symlink_to(releases / expected["git_sha"])
    env_dir = tmp_path / "environment"
    env_dir.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (env_dir / "modstore-release.env").write_text(
        f"MODMAN_LIBRARY={runtime}/library\nMODSTORE_CATALOG_DIR={runtime}/catalog\nMODSTORE_RUNTIME_DIR={runtime}\nMODSTORE_CAPABILITY_PROPOSAL_REPO=42433422/XCMAX\n"
    )
    env = {
        "RELEASE_BASE": str(tmp_path),
        "RELEASES_DIR": str(releases),
        "CURRENT_LINK": str(current),
        "RUNTIME_DIR": str(runtime),
        "ENV_DIR": str(env_dir),
        "LOCK_FILE": str(tmp_path / "release.lock"),
        "XCMAX_ALLOW_CUSTOM_RELEASE_BASE": "1",
        "HEALTH_URL": "http://test/api",
        "SCHEDULER_HEALTH_URL": "http://test/scheduler",
        "PUBLIC_HEALTH_URL": "https://test/public",
    }
    payload = {
        "request_id": "retort:test:rollback",
        "expected_identity": expected,
        "target_identity": target,
        "reason": "experiment_regression",
    }
    calls, reads = [], []

    def native(native_env, lock_fd):
        # A separate process must observe the same deployment kernel lock.
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import fcntl,sys; f=open(sys.argv[1],'a+'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",
                env["LOCK_FILE"],
            ],
            capture_output=True,
        )
        assert probe.returncode != 0
        assert os.fstat(lock_fd).st_ino == os.stat(env["LOCK_FILE"]).st_ino
        assert native_env["PREVIOUS_LIBRARY_DIR"] == str(runtime / "library")
        link = tmp_path / "next"
        link.symlink_to(native_env["PREVIOUS_ROOT"])
        link.replace(current)
        calls.append(native_env)

    def health(url):
        reads.append(url)
        return {**target, "ok": True, "deploy_tier": "production"}

    return payload, env, native, health, calls, reads


def test_exact_rollback_and_durable_replay_do_not_execute_twice(harness):
    payload, env, native, health, calls, reads = harness
    first = recovery.recover(
        {"event_id": 3, "payload": payload},
        env=env,
        run_native=native,
        read_health=health,
    )
    assert first["status"] == "rollback_verified" and first["replayed"] is False
    second = recovery.recover(payload, env=env, run_native=native, read_health=health)
    assert second["replayed"] is True and second["identity"] == payload["target_identity"]
    assert len(calls) == 1 and len(reads) == 6


def test_production_advanced_since_experiment_never_rolls_back(harness):
    payload, env, native, health, calls, reads = harness
    current = Path(env["CURRENT_LINK"])
    current.unlink()
    current.symlink_to(Path(env["RELEASES_DIR"]) / ("c" * 40))
    with pytest.raises(recovery.RecoveryError, match="production_identity_changed"):
        recovery.recover(payload, env=env, run_native=native, read_health=health)
    assert calls == reads == []


def test_same_request_cannot_be_rebound_to_another_approved_reason(harness):
    payload, env, native, health, calls, _ = harness
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    with pytest.raises(recovery.RecoveryError, match="rollback_request_conflict"):
        recovery.recover(
            {**payload, "reason": "original_customer_reopened"},
            env=env,
            run_native=native,
            read_health=health,
        )
    assert len(calls) == 1


def test_lost_native_response_reads_target_on_retry_without_repeating_switch(harness):
    payload, env, native, health, calls, _ = harness

    def interrupted(native_env, lock_fd):
        native(native_env, lock_fd)
        raise OSError("connection lost after switching")

    with pytest.raises(OSError):
        recovery.recover(payload, env=env, run_native=interrupted, read_health=health)
    receipt = next((Path(env["RUNTIME_DIR"]) / "release-recovery").glob("*.json"))
    assert json.loads(receipt.read_text())["status"] == "readback_required"
    result = recovery.recover(payload, env=env, run_native=interrupted, read_health=health)
    assert result["status"] == "rollback_verified" and result["replayed"] is True
    assert len(calls) == 1


@pytest.mark.parametrize(
    "surface", ["http://test/api", "http://test/scheduler", "https://test/public"]
)
def test_every_runtime_surface_must_read_back_the_target(harness, surface):
    payload, env, native, health, calls, _ = harness

    def stale(url):
        return {
            **health(url),
            **(payload["expected_identity"] if url == surface else {}),
        }

    with pytest.raises(recovery.RecoveryError, match="rollback_health_identity_mismatch"):
        recovery.recover(payload, env=env, run_native=native, read_health=stale)
    result = recovery.recover(payload, env=env, run_native=native, read_health=health)
    assert result["replayed"] is True and len(calls) == 1


def test_receipt_is_not_success_when_payment_has_a_different_release(harness, monkeypatch):
    payload, env, native, health, _, _ = harness
    monkeypatch.setattr(recovery, "_payment_present", lambda: True)
    with pytest.raises(recovery.RecoveryError, match="rollback_payment_identity_mismatch"):
        recovery.recover(payload, env=env, run_native=native, read_health=health)


def test_target_artifact_must_match_the_frozen_experiment(harness):
    payload, env, native, health, calls, _ = harness
    wrong = {**payload["target_identity"], "artifact_sha256": "c" * 64}
    with pytest.raises(recovery.RecoveryError, match="rollback_target_identity_mismatch"):
        recovery.recover(
            {**payload, "target_identity": wrong},
            env=env,
            run_native=native,
            read_health=health,
        )
    assert calls == []


def test_other_deployment_holds_the_same_kernel_lock(harness):
    payload, env, native, health, calls, _ = harness
    with open(env["LOCK_FILE"], "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(recovery.RecoveryError, match="immutable_release_busy"):
            recovery.recover(payload, env=env, run_native=native, read_health=health)
    assert calls == []


@pytest.mark.parametrize("request_id", ["../other", 2, "", "a" * 201])
def test_invalid_request_ids_do_not_touch_runtime(harness, request_id):
    payload, env, native, health, calls, _ = harness
    with pytest.raises(recovery.RecoveryError, match="invalid_rollback_request_id"):
        recovery.recover(
            {**payload, "request_id": request_id},
            env=env,
            run_native=native,
            read_health=health,
        )
    assert calls == []


def test_shell_rollback_entry_does_not_enter_build_or_schema_migration(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "xcmax-immutable-release.sh"), "--rollback-json"],
        input="{}",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "XCMAX_SOURCE_ROOT": str(tmp_path / "missing-source"),
            "XCMAX_RELEASE_BASE": str(tmp_path / "runtime"),
        },
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"] == "invalid_rollback_request_id"
    assert "source Git mirror" not in result.stderr
    assert not (tmp_path / "runtime").exists()
