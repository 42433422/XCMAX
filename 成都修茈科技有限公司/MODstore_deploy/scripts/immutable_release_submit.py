"""Submit the existing CAS rollback in an independent systemd transient service."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import immutable_release_recovery as recovery

SCRIPT_PATH = Path(__file__).absolute()
DEPLOY_SUBDIR = "成都修茈科技有限公司/MODstore_deploy"
SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"}
CONTROLLER_FILES = (
    "immutable_release_submit.py",
    "immutable_release_recovery.py",
    "immutable_release_runtime.sh",
    "xcmax-immutable-release.sh",
    "sync_site_download_release.py",
)


def _path(value: str, *, link: bool = False) -> str:
    # systemd expands percent specifiers and ExecStart dollar references. None
    # are part of the supported runtime paths or health endpoints.
    if not value or any(ord(char) < 32 or char in "%$" for char in value):
        raise recovery.RecoveryError("unsafe_rollback_runtime_value")
    path = Path(value)
    recovery._plain_path(path.parent if link else path)
    return str(path)


def _controller(releases: Path) -> tuple[Path, dict]:
    script = recovery._plain_path(SCRIPT_PATH)
    root = script.parents[3]
    if script != root / DEPLOY_SUBDIR / "scripts" / SCRIPT_PATH.name:
        raise recovery.RecoveryError("rollback_controller_path_mismatch")
    identity = recovery._release(root, releases)
    files = {}
    for path in script.relative_to(root).parents:
        # Only inspect actual controller ancestors, never unrelated host paths.
        directory = root / path
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o222:
            raise recovery.RecoveryError("rollback_controller_not_immutable")
    for name in CONTROLLER_FILES:
        path = recovery._plain_path(script.parent / name)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o222:
            raise recovery.RecoveryError("rollback_controller_not_immutable")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return script.parent, {"identity": identity, "files": files}


def _environment(env: dict[str, str], scripts: Path) -> dict[str, str]:
    selected = dict(SAFE_ENV)
    for key in (
        "RELEASE_BASE",
        "RELEASES_DIR",
        "CURRENT_LINK",
        "RUNTIME_DIR",
        "ENV_DIR",
        "ENV_FILE",
        "SCHEDULER_ENV_FILE",
        "SITE_LINK",
        "LOCK_FILE",
        "PUBLICATION_LOCK",
    ):
        selected[key] = _path(env[key], link=key in ("CURRENT_LINK", "SITE_LINK"))
    for key in ("HEALTH_URL", "SCHEDULER_HEALTH_URL", "PUBLIC_HEALTH_URL"):
        value = env[key]
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or any(ord(char) < 32 or char in "%$" for char in value)
        ):
            raise recovery.RecoveryError("invalid_rollback_health_url")
        selected[key] = value
    selected.update(
        SITE_SUBDIR="成都修茈科技有限公司",
        MODSTORE_SUBDIR=DEPLOY_SUBDIR,
        POINTER_SYNC=str(scripts / "sync_site_download_release.py"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    if env.get("XCMAX_ALLOW_CUSTOM_RELEASE_BASE") == "1":
        selected["XCMAX_ALLOW_CUSTOM_RELEASE_BASE"] = "1"
    return selected


def _private(path: Path, *, directory: bool = False) -> None:
    recovery._plain_path(path)
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise recovery.RecoveryError("rollback_submission_permissions")


def _run(argv: list[str]):
    return subprocess.run(
        argv, env=SAFE_ENV, capture_output=True, text=True, timeout=15, check=False
    )


def _unit(unit: str, description: str, run) -> str:
    try:
        result = run(
            [
                "/usr/bin/systemctl",
                "--system",
                "--no-ask-password",
                "show",
                unit,
                "--property=LoadState,ActiveState,Description,Transient,Slice",
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if values.get("LoadState") == "not-found":
        return "missing"
    if result.returncode or not values.get("LoadState"):
        return "unavailable"
    if (
        values.get("Description") != description
        or values.get("Transient") != "yes"
        or values.get("Slice") != "system.slice"
    ):
        raise recovery.RecoveryError("rollback_systemd_unit_conflict")
    return values.get("ActiveState", "unknown")


def protected_releases(env: dict[str, str]) -> list[str]:
    """Read fixed controller references only; the caller holds the deployment lock."""
    releases = recovery._plain_path(Path(env["RELEASES_DIR"]))
    state = recovery._plain_path(Path(env["RUNTIME_DIR"]) / "release-recovery")
    protected = set()
    commands = [env.get("MODSTORE_AUTO_ROLLBACK_COMMAND", "")]
    for name in ("ENV_FILE", "SCHEDULER_ENV_FILE"):
        path = recovery._plain_path(Path(env[name]))
        if path.exists():
            for line in path.read_text().splitlines():
                key, separator, value = line.strip().partition("=")
                if separator and key == "MODSTORE_AUTO_ROLLBACK_COMMAND":
                    parsed = shlex.split(value)
                    commands.append(parsed[0] if len(parsed) == 1 else value)
    for command in commands:
        parts = shlex.split(command)
        if "--submit-rollback-json" not in parts:
            continue
        if len(parts) == 3 and parts[0] in ("bash", "/bin/bash", "/usr/bin/bash"):
            parts = parts[1:]
        if len(parts) != 2 or parts[1] != "--submit-rollback-json":
            raise recovery.RecoveryError("rollback_controller_configuration_invalid")
        script = recovery._plain_path(Path(parts[0]))
        if len(script.parents) < 4:
            raise recovery.RecoveryError("rollback_controller_configuration_invalid")
        root = script.parents[3]
        if (
            script != root / DEPLOY_SUBDIR / "scripts/xcmax-immutable-release.sh"
            or root.parent != releases
            or not re.fullmatch(r"[0-9a-f]{40}", root.name)
        ):
            raise recovery.RecoveryError("rollback_controller_configuration_invalid")
        protected.add(str(root))
    submissions = recovery._plain_path(state / "submissions")
    if submissions.exists():
        _private(submissions, directory=True)
        for path in submissions.glob("*.submission.json"):
            _private(path)
            submission = json.loads(path.read_text())
            if submission.get("attempted") is not True:
                continue
            binding = submission["binding"]
            request = recovery.request_payload(binding)
            key = hashlib.sha256(request["request_id"].encode()).hexdigest()
            digest = recovery._request_digest(request)
            if path.name != f"{key}.submission.json" or binding.get("request_sha256") != digest:
                raise recovery.RecoveryError("rollback_submission_conflict")
            frozen = recovery._plain_path(submissions / f"{key}.request.json")
            _private(frozen)
            if json.loads(frozen.read_text()) != request:
                raise recovery.RecoveryError("rollback_request_conflict")
            receipt = recovery._plain_path(state / f"{key}.json")
            if receipt.exists():
                _private(receipt)
                record = json.loads(receipt.read_text())
                if (
                    record.get("status") == "rollback_verified"
                    and recovery.request_payload(record) == request
                    and record.get("request_sha256") == digest
                    and record.get("identity") == request["target_identity"]
                ):
                    continue
            controller = recovery.identity(binding["controller"]["identity"])
            root = releases / controller["git_sha"]
            if binding["command"][-1] != str(
                root / DEPLOY_SUBDIR / "scripts/immutable_release_recovery.py"
            ):
                raise recovery.RecoveryError("rollback_controller_path_mismatch")
            protected.add(str(root))
            for name in ("expected_identity", "target_identity"):
                protected.add(str(releases / request[name]["git_sha"]))
    return sorted(protected)


def submit(value, *, env: dict[str, str], run=_run) -> dict:
    request = recovery.request_payload(value)
    _releases, _state, _receipt, lock_path = recovery._recovery_paths(request, env)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recovery.RecoveryError("immutable_release_busy") from exc
        return _submit_locked(request, env=env, run=run, deployment_lock=lock.fileno())


def _submit_locked(value, *, env: dict[str, str], run, deployment_lock: int) -> dict:
    request = recovery.request_payload(value)
    releases, state, receipt, _lock = recovery._recovery_paths(request, env)
    scripts, controller = _controller(releases)
    worker_env = _environment(env, scripts)
    digest = recovery._request_digest(request)
    key = hashlib.sha256(request["request_id"].encode()).hexdigest()
    submissions = recovery._plain_path(state / "submissions")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private(state, directory=True)
    submissions.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private(submissions, directory=True)
    frozen = recovery._plain_path(submissions / f"{key}.request.json")
    record_path = recovery._plain_path(submissions / f"{key}.submission.json")
    lock_path = recovery._plain_path(submissions / f"{key}.lock")
    unit = f"xcmax-rollback-{key}-{digest}.service"
    command = [
        "/usr/bin/env",
        "-i",
        *(f"{name}={value}" for name, value in sorted(worker_env.items())),
        "/usr/bin/python3",
        "-I",
        str(scripts / "immutable_release_recovery.py"),
    ]
    binding = {
        **request,
        "request_sha256": digest,
        "controller": controller,
        "command": command,
        "unit": unit,
        "uid": os.geteuid(),
        "gid": os.getegid(),
    }
    binding_hash = recovery._request_digest(binding)
    description = f"XCMAX immutable rollback {binding_hash}"
    answer = {"request_id": request["request_id"], "request_sha256": digest, "unit": unit}
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
        _private(lock_path)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise recovery.RecoveryError("rollback_submission_busy") from exc
        previous = None
        if record_path.exists():
            _private(record_path)
            previous = json.loads(record_path.read_text())
            if not isinstance(previous, dict) or previous.get("binding") != binding:
                raise recovery.RecoveryError("rollback_submission_conflict")
        if frozen.exists():
            _private(frozen)
            if json.loads(frozen.read_text()) != request:
                raise recovery.RecoveryError("rollback_request_conflict")
        elif previous:
            raise recovery.RecoveryError("rollback_frozen_request_missing")
        else:
            recovery._save(frozen, request)
        # A recovery receipt, even a failed/unknown one, forbids another unit.
        # Only recovery.readback may turn its evidence into verified completion.
        if receipt.exists():
            record = json.loads(receipt.read_text())
            if (
                recovery.request_payload(record) != request
                or record.get("request_sha256") != digest
            ):
                raise recovery.RecoveryError("rollback_request_conflict")
            return {**answer, "status": "accepted", "reason": "recovery_receipt_present"}
        observed = _unit(unit, description, run)
        if observed not in ("missing", "unavailable"):
            if not previous:
                raise recovery.RecoveryError("rollback_systemd_unit_unowned")
            status = "accepted" if observed in ("active", "activating") else "waiting"
            return {**answer, "status": status, "reason": f"recovery_unit_{observed}"}
        if previous and previous.get("attempted"):
            return {**answer, "status": "waiting", "reason": "systemd_submission_unknown"}
        if observed == "unavailable":
            return {**answer, "status": "waiting", "reason": "systemd_unavailable"}
        # Durable intent precedes the D-Bus call. Losing either process or its
        # response may never lead to replay, even after transient units disappear.
        record = {"binding": binding, "attempted": True, "status": "submitting"}
        recovery._save(record_path, record)
        argv = [
            "/usr/bin/systemd-run",
            "--system",
            "--no-ask-password",
            "--quiet",
            "--no-block",
            f"--unit={unit}",
            f"--description={description}",
            "--service-type=oneshot",
            "--remain-after-exit",
            "--slice=system.slice",
            f"--uid={os.geteuid()}",
            f"--gid={os.getegid()}",
            "--property=UMask=0077",
            "--property=Restart=no",
            "--property=TimeoutStartSec=720s",
            f"--property=StandardInput=file:{frozen}",
            "--property=StandardOutput=journal",
            "--property=StandardError=journal",
            "--",
            *command,
        ]
        # Pruning now sees the durable controller binding. Let the independent
        # worker take the same deployment lock before asking systemd to start it.
        fcntl.flock(deployment_lock, fcntl.LOCK_UN)
        try:
            accepted = run(argv).returncode == 0
        except (OSError, subprocess.SubprocessError):
            accepted = False
        if not accepted:
            accepted = _unit(unit, description, run) in ("active", "activating")
        status = "accepted" if accepted else "waiting"
        recovery._save(record_path, {**record, "status": status})
        return {
            **answer,
            "status": status,
            "reason": "awaiting_recovery_readback" if accepted else "systemd_submission_unknown",
        }


def main() -> int:
    try:
        if sys.argv[1:] == ["--protected-releases"]:
            print("\n".join(protected_releases(dict(os.environ))))
            return 0
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise recovery.RecoveryError("rollback_request_too_large")
        result = submit(json.loads(raw), env=dict(os.environ))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        result = {
            "status": "waiting",
            "reason": str(exc) if isinstance(exc, recovery.RecoveryError) else type(exc).__name__,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
