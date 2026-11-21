from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import shutil
import stat
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


@pytest.mark.parametrize(
    "code,state,expected",
    [
        (0, "loaded", True),
        (0, "not-found", False),
        (4, "not-found", False),
        (1, "", None),
        (1, "loaded", None),
        (0, "masked", None),
        (0, "error", None),
    ],
)
def test_payment_presence_requires_an_explicit_systemd_answer(monkeypatch, code, state, expected):
    def query(argv, **kwargs):
        assert argv == [
            "systemctl",
            "show",
            "modstore-payment.service",
            "--property=LoadState",
            "--value",
        ]
        return subprocess.CompletedProcess(argv, code, state + "\n", "")

    monkeypatch.setattr(recovery.subprocess, "run", query)
    if expected is None:
        with pytest.raises(recovery.RecoveryError, match="rollback_payment_presence_unknown"):
            recovery._payment_present()
    else:
        assert recovery._payment_present() is expected


@pytest.mark.parametrize(
    "failure", [FileNotFoundError(), subprocess.TimeoutExpired("systemctl", 10)]
)
def test_payment_presence_transport_failure_is_unknown(monkeypatch, failure):
    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(recovery.subprocess, "run", unavailable)
    with pytest.raises(recovery.RecoveryError, match="rollback_payment_presence_unknown"):
        recovery._payment_present()


def test_three_healthy_surfaces_cannot_hide_an_unreadable_payment_unit(monkeypatch):
    target = build_identity("b")
    monkeypatch.setattr(
        recovery.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, "", "Failed to connect to bus: Permission denied"
        ),
    )
    env = {key: key for key in ("HEALTH_URL", "SCHEDULER_HEALTH_URL", "PUBLIC_HEALTH_URL")}
    with pytest.raises(recovery.RecoveryError, match="rollback_payment_presence_unknown"):
        recovery._verify_health(
            target, env, lambda _url: {**target, "ok": True, "deploy_tier": "production"}
        )


@pytest.mark.parametrize("state", ["loaded", "not-found", "unknown"])
def test_native_rollback_uses_the_same_strict_payment_presence_contract(monkeypatch, state):
    native_calls = []

    def invoke(argv, **kwargs):
        if argv[0] == "systemctl":
            return subprocess.CompletedProcess(argv, 1 if state == "unknown" else 0, state, "")
        native_calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(recovery.subprocess, "run", invoke)
    if state == "unknown":
        with pytest.raises(recovery.RecoveryError, match="rollback_payment_presence_unknown"):
            recovery._run_native({}, 0)
        assert native_calls == []
    else:
        recovery._run_native({}, 0)
        argv, kwargs = native_calls[0]
        assert kwargs["env"]["PAYMENT_SERVICE_PRESENT"] == ("1" if state == "loaded" else "0")
        assert "systemctl cat modstore-payment.service" not in argv[2]


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


def test_readback_rechecks_live_health_under_the_deploy_lock_without_writes(harness, monkeypatch):
    payload, env, native, health, calls, _ = harness
    verified = recovery.recover(payload, env=env, run_native=native, read_health=health)
    receipt = next((Path(env["RUNTIME_DIR"]) / "release-recovery").glob("*.json"))
    before = receipt.read_bytes(), receipt.stat().st_mtime_ns

    def no_write(*args, **kwargs):
        pytest.fail("readback must not write recovery state or run a native rollback")

    monkeypatch.setattr(recovery, "_save", no_write)
    monkeypatch.setattr(recovery, "_run_native", no_write)

    def locked_health(url):
        with open(env["LOCK_FILE"]) as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return health(url)

    assert recovery.readback(payload, env=env, read_health=locked_health) == verified
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
    assert len(calls) == 1


def test_readback_never_promotes_unknown_rollback_after_the_pointer_moved(harness):
    payload, env, native, health, calls, _ = harness
    with pytest.raises(recovery.RecoveryError, match="rollback_health_not_ready"):
        recovery.recover(
            payload, env=env, run_native=native, read_health=lambda _url: {"ok": False}
        )
    assert Path(env["CURRENT_LINK"]).resolve().name == payload["target_identity"]["git_sha"]
    receipt = next((Path(env["RUNTIME_DIR"]) / "release-recovery").glob("*.json"))
    before = receipt.read_bytes()
    with pytest.raises(recovery.RecoveryError, match="rollback_receipt_not_verified"):
        recovery.readback(payload, env=env, read_health=health)
    assert receipt.read_bytes() == before and len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"status": "submitted"},
        {"request_sha256": "0" * 64},
        {"reason": "original_customer_reopened"},
        {"identity": build_identity("a")},
    ],
)
def test_readback_requires_complete_matching_durable_receipt(harness, change):
    payload, env, native, health, calls, _ = harness
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    receipt = next((Path(env["RUNTIME_DIR"]) / "release-recovery").glob("*.json"))
    if change is None:
        receipt.unlink()
    else:
        receipt.write_text(json.dumps({**json.loads(receipt.read_text()), **change}))
    with pytest.raises(recovery.RecoveryError):
        recovery.readback(payload, env=env, read_health=health)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "surface", ["http://test/api", "http://test/scheduler", "https://test/public"]
)
def test_readback_rejects_unhealthy_surface_despite_verified_receipt(harness, surface):
    payload, env, native, health, calls, _ = harness
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    with pytest.raises(recovery.RecoveryError, match="rollback_health_not_ready"):
        recovery.readback(
            payload,
            env=env,
            read_health=lambda url: {**health(url), "ok": url != surface},
        )
    assert len(calls) == 1


def test_readback_rejects_superseded_receipt_and_contending_deployment(harness):
    payload, env, native, health, calls, _ = harness
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    with open(env["LOCK_FILE"]) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(recovery.RecoveryError, match="immutable_release_busy"):
            recovery.readback(payload, env=env, read_health=health)
    current = Path(env["CURRENT_LINK"])
    current.unlink()
    current.symlink_to(Path(env["RELEASES_DIR"]) / ("c" * 40))
    with pytest.raises(recovery.RecoveryError, match="rollback_receipt_superseded"):
        recovery.readback(payload, env=env, read_health=health)
    assert len(calls) == 1


def test_readback_without_prior_command_does_not_create_runtime_state(harness):
    payload, env, _native, health, calls, reads = harness
    with pytest.raises(recovery.RecoveryError, match="rollback_readback_unavailable"):
        recovery.readback(payload, env=env, read_health=health)
    assert not Path(env["LOCK_FILE"]).exists()
    assert not (Path(env["RUNTIME_DIR"]) / "release-recovery").exists()
    assert calls == reads == []


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


def test_recovery_preserves_the_explicit_installed_runtime_in_a_clean_service_env(harness):
    payload, env, native, health, calls, _ = harness
    runtime = Path(sys.executable).resolve()
    release_env = Path(env["ENV_DIR"]) / "modstore-release.env"
    with release_env.open("a") as stream:
        stream.write(f"MODSTORE_NODE_EXECUTABLE={runtime}\n")
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    assert calls[0]["MODSTORE_NODE_EXECUTABLE"] == str(runtime)


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


@pytest.fixture
def submission(harness, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import immutable_release_submit as submitter

    monkeypatch.setattr(submitter, "recovery", recovery)
    payload, env, *_ = harness
    controller = Path(env["RELEASES_DIR"]) / ("c" * 40)
    scripts = controller / submitter.DEPLOY_SUBDIR / "scripts"
    scripts.mkdir(parents=True)
    for name in submitter.CONTROLLER_FILES:
        shutil.copyfile(SCRIPTS / name, scripts / name)
        (scripts / name).chmod(0o444)
    for path in (scripts, scripts.parent, scripts.parent.parent, controller):
        path.chmod(0o555)
    monkeypatch.setattr(submitter, "SCRIPT_PATH", scripts / "immutable_release_submit.py")
    env = {
        **env,
        "ENV_FILE": env["ENV_DIR"] + "/modstore.env",
        "SCHEDULER_ENV_FILE": env["ENV_DIR"] + "/modstore-scheduler.env",
        "SITE_LINK": str(controller.parent.parent / "site"),
        "PUBLICATION_LOCK": str(controller.parent.parent / "publication.lock"),
        "OPENCODE_API_KEY": "must-never-enter-the-controller",
        "BASH_ENV": "/untrusted/startup.sh",
        "PATH": "/untrusted/bin",
    }

    class Manager:
        state = "missing"
        state_after_start = "active"
        result = 0
        description = ""

        def __init__(self):
            self.calls = []

        @property
        def starts(self):
            return [call for call in self.calls if call[0] == "/usr/bin/systemd-run"]

        def __call__(self, argv):
            self.calls.append(argv)
            if argv[0] == "/usr/bin/systemctl":
                if self.state == "missing":
                    return subprocess.CompletedProcess(argv, 4, "LoadState=not-found\n", "")
                if self.state == "unavailable":
                    return subprocess.CompletedProcess(argv, 1, "", "Access denied")
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "LoadState=loaded\nTransient=yes\nSlice=system.slice\n"
                    f"ActiveState={self.state}\nDescription={self.description}\n",
                    "",
                )
            assert argv[0] == "/usr/bin/systemd-run"
            records = list(
                (Path(env["RUNTIME_DIR"]) / "release-recovery/submissions").glob(
                    "*.submission.json"
                )
            )
            assert len(records) == 1
            assert json.loads(records[0].read_text())["attempted"] is True
            self.description = next(
                arg.split("=", 1)[1] for arg in argv if arg.startswith("--description=")
            )
            self.state = self.state_after_start
            if isinstance(self.result, Exception):
                raise self.result
            return subprocess.CompletedProcess(
                argv, self.result, "", "untrusted manager diagnostic"
            )

    return submitter, payload, env, Manager()


def test_transient_submission_freezes_private_input_and_exact_immutable_argv(submission, tmp_path):
    submitter, payload, env, manager = submission

    def locked_manager(argv):
        if argv[0] == "/usr/bin/systemd-run":
            lock = next((Path(env["RUNTIME_DIR"]) / "release-recovery/submissions").glob("*.lock"))
            contender = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import fcntl,sys; f=open(sys.argv[1]); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",
                    str(lock),
                ],
                capture_output=True,
            )
            assert contender.returncode != 0
            # Registration and pruning share the deployment lock, but it must
            # already be released when the independent recovery worker starts.
            with open(env["LOCK_FILE"]) as deployment:
                fcntl.flock(deployment, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert str(submitter.SCRIPT_PATH.parents[3]) in submitter.protected_releases(env)
        return manager(argv)

    result = submitter.submit(
        {"event_id": 5, "payload": {**payload, "command": "arbitrary-shell-must-be-ignored"}},
        env=env,
        run=locked_manager,
    )
    assert result["status"] == "accepted" and "identity" not in result
    argv = manager.starts[0]
    assert all(
        option in argv
        for option in (
            "--no-ask-password",
            "--no-block",
            "--service-type=oneshot",
            "--remain-after-exit",
            "--slice=system.slice",
        )
    )
    assert not any(option in argv for option in ("--scope", "--wait", "--pipe", "--collect"))
    command = argv[argv.index("--") + 1 :]
    assert command[:2] == ["/usr/bin/env", "-i"]
    assert command[-3:] == [
        "/usr/bin/python3",
        "-I",
        str(submitter.SCRIPT_PATH.parent / "immutable_release_recovery.py"),
    ]
    assert "/current/" not in command[-1]
    assert all(
        word not in " ".join(argv)
        for word in (
            "must-never-enter",
            "arbitrary-shell",
            "/untrusted/",
            "BASH_ENV",
            "OPENCODE_API_KEY",
        )
    )
    stdin = Path(
        next(
            arg.removeprefix("--property=StandardInput=file:")
            for arg in argv
            if arg.startswith("--property=StandardInput=file:")
        )
    )
    assert json.loads(stdin.read_text()) == payload
    assert stat.S_IMODE(stdin.stat().st_mode) == 0o600
    assert stat.S_IMODE(stdin.parent.stat().st_mode) == 0o700
    for path in stdin.parent.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert submitter.submit(payload, env=env, run=manager)["status"] == "accepted"
    assert len(manager.starts) == 1
    # Exercise the installed mature parser, without starting a service. The
    # subprocess runner above records the actual production argv contract.
    if shutil.which("systemd-analyze"):
        unit = tmp_path / result["unit"]
        properties = [
            arg.removeprefix("--property=") for arg in argv if arg.startswith("--property=")
        ]
        unit.write_text(
            "[Service]\nType=oneshot\nRemainAfterExit=yes\n"
            + "\n".join(properties)
            + "\nExecStart="
            + " ".join(json.dumps(arg, ensure_ascii=False) for arg in command)
            + "\n"
        )
        checked = subprocess.run(
            ["systemd-analyze", "verify", "--man=no", str(unit)], capture_output=True, text=True
        )
        assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("unit_after_timeout", ["active", "missing"])
def test_unknown_systemd_submission_reads_original_unit_and_never_replays(
    submission, unit_after_timeout
):
    submitter, payload, env, manager = submission
    manager.result = subprocess.TimeoutExpired("systemd-run", 15)
    manager.state_after_start = unit_after_timeout
    first = submitter.submit(payload, env=env, run=manager)
    assert first["status"] == ("accepted" if unit_after_timeout == "active" else "waiting")
    assert submitter.submit(payload, env=env, run=manager)["status"] == first["status"]
    assert len(manager.starts) == 1


def test_missing_systemd_authority_stays_waiting_without_privilege_escalation(submission):
    submitter, payload, env, manager = submission
    manager.state = "unavailable"
    result = submitter.submit(payload, env=env, run=manager)
    assert result["status"] == "waiting" and result["reason"] == "systemd_unavailable"
    assert manager.starts == []
    manager.state = "missing"
    manager.result, manager.state_after_start = 1, "missing"
    result = submitter.submit(payload, env=env, run=manager)
    assert result["status"] == "waiting" and result["reason"] == "systemd_submission_unknown"
    assert submitter.submit(payload, env=env, run=manager)["status"] == "waiting"
    assert len(manager.starts) == 1
    assert "sudo" not in str(manager.calls) and "polkit" not in str(manager.calls)


@pytest.mark.parametrize("change", ["reason", "environment", "controller", "permissions"])
def test_repeated_submission_rejects_changed_request_controller_or_runtime(submission, change):
    submitter, payload, env, manager = submission
    submitter.submit(payload, env=env, run=manager)
    if change == "reason":
        payload = {**payload, "reason": "original_customer_reopened"}
    elif change == "environment":
        env = {**env, "PUBLIC_HEALTH_URL": "https://other/api/health"}
    elif change == "controller":
        script = submitter.SCRIPT_PATH
        script.chmod(0o644)
        script.write_text("changed controller bytes")
        script.chmod(0o444)
    else:
        next(
            (Path(env["RUNTIME_DIR"]) / "release-recovery/submissions").glob("*.request.json")
        ).chmod(0o644)
    with pytest.raises(recovery.RecoveryError):
        submitter.submit(payload, env=env, run=manager)
    assert len(manager.starts) == 1


@pytest.mark.parametrize("change", ["current_link", "mutable_script", "specifier_path"])
def test_submission_rejects_unbound_controller_and_systemd_path_expansion(
    submission, monkeypatch, change
):
    submitter, payload, env, manager = submission
    if change == "current_link":
        alias = Path(env["RUNTIME_DIR"]) / "controller"
        alias.symlink_to(submitter.SCRIPT_PATH.parent)
        monkeypatch.setattr(submitter, "SCRIPT_PATH", alias / submitter.SCRIPT_PATH.name)
    elif change == "mutable_script":
        submitter.SCRIPT_PATH.chmod(0o644)
    else:
        env["PUBLICATION_LOCK"] += "%n"
    with pytest.raises(recovery.RecoveryError):
        submitter.submit(payload, env=env, run=manager)
    assert manager.starts == []


def test_existing_recovery_receipt_only_requests_readback_without_new_unit(submission, harness):
    submitter, payload, env, manager = submission
    _, _, native, health, calls, _ = harness
    recovery.recover(payload, env=env, run_native=native, read_health=health)
    result = submitter.submit(payload, env=env, run=manager)
    assert result["status"] == "accepted" and result["reason"] == "recovery_receipt_present"
    assert "identity" not in result and manager.calls == [] and len(calls) == 1


def test_submission_will_not_reuse_an_unrelated_systemd_unit(submission):
    submitter, payload, env, manager = submission
    manager.state, manager.description = "active", "some other command"
    with pytest.raises(recovery.RecoveryError, match="rollback_systemd_unit_conflict"):
        submitter.submit(payload, env=env, run=manager)
    assert manager.starts == []


def test_controller_registration_cannot_race_release_pruning(submission):
    submitter, payload, env, manager = submission
    with open(env["LOCK_FILE"], "a+") as deployment:
        fcntl.flock(deployment, fcntl.LOCK_EX)
        with pytest.raises(recovery.RecoveryError, match="immutable_release_busy"):
            submitter.submit(payload, env=env, run=manager)
    assert manager.calls == []


@pytest.mark.parametrize(
    "protection", ["ENV_FILE", "SCHEDULER_ENV_FILE", "process", "in_flight", "completed"]
)
def test_actual_release_pruning_keeps_only_configured_or_unfinished_controllers(
    submission, harness, protection
):
    if not shutil.which("flock"):
        pytest.skip("native release publisher requires flock")
    submitter, payload, env, manager = submission
    _, _, native, health, _, _ = harness
    submitter.submit(payload, env=env, run=manager)
    controller = submitter.SCRIPT_PATH.parents[3]
    base = Path(env["RELEASE_BASE"])
    if protection != "in_flight":
        recovery.recover(payload, env=env, run_native=native, read_health=health)
    command = f"/usr/bin/bash {controller}/{submitter.DEPLOY_SUBDIR}/scripts/xcmax-immutable-release.sh --submit-rollback-json"
    if protection in ("ENV_FILE", "SCHEDULER_ENV_FILE"):
        Path(env[protection]).write_text(f"MODSTORE_AUTO_ROLLBACK_COMMAND='{command}'\n")
    for index, char in enumerate("abcdef"):
        root = Path(env["RELEASES_DIR"]) / (char * 40)
        if not root.exists():
            root.mkdir()
            (root / ".xcmax-release.json").write_text(json.dumps(build_identity(char)))
        os.utime(root, (index + 1, index + 1))
    source = base / "source"
    (source / ".git").mkdir(parents=True)
    result = subprocess.run(
        ["bash", str(SCRIPTS / "xcmax-immutable-release.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MODSTORE_AUTO_ROLLBACK_COMMAND": command if protection == "process" else "",
            "XCMAX_ALLOW_CUSTOM_RELEASE_BASE": "1",
            "XCMAX_RELEASE_BASE": str(base),
            "XCMAX_CURRENT_LINK": env["CURRENT_LINK"],
            "XCMAX_RELEASE_LOCK": env["LOCK_FILE"],
            "XCMAX_SOURCE_ROOT": str(source),
            "XCMAX_RELEASE_PRUNE_ONLY": "1",
            "XCMAX_RELEASES_TO_KEEP": "3",
            "XCMAX_TARGET_SHA": "d" * 40,
            "XCMAX_PUBLIC_SITE_STATE_DIR": str(base / "public"),
            "MODSTORE_RUNTIME_DIR": env["RUNTIME_DIR"],
            "MODSTORE_ENV_DIR": env["ENV_DIR"],
            "MODSTORE_ENV_FILE": env["ENV_FILE"],
            "MODSTORE_SCHEDULER_ENV_FILE": env["SCHEDULER_ENV_FILE"],
        },
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert controller.exists() is (protection != "completed")
    assert len(list(Path(env["RELEASES_DIR"]).iterdir())) == (4 if protection == "in_flight" else 3)
    if protection == "in_flight":
        for name in ("expected_identity", "target_identity"):
            assert (Path(env["RELEASES_DIR"]) / payload[name]["git_sha"]).is_dir()


def test_retention_parser_never_executes_shell_configuration(submission):
    submitter, _, env, manager = submission
    marker = Path(env["RUNTIME_DIR"]) / "executed"
    Path(env["ENV_FILE"]).write_text(
        f"MODSTORE_AUTO_ROLLBACK_COMMAND='$(touch {marker}) --submit-rollback-json'\n"
    )
    with pytest.raises(recovery.RecoveryError, match="rollback_controller_configuration_invalid"):
        submitter.protected_releases(env)
    assert not marker.exists() and manager.calls == []


def test_submit_shell_entry_rejects_bad_input_before_any_host_action(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "xcmax-immutable-release.sh"), "--submit-rollback-json"],
        input="{}",
        capture_output=True,
        text=True,
        env={**os.environ, "XCMAX_RELEASE_BASE": str(tmp_path / "runtime")},
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "status": "waiting",
        "reason": "invalid_rollback_request_id",
    }
    assert not (tmp_path / "runtime").exists()
