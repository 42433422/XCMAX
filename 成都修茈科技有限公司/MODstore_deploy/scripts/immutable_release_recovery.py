"""CAS/idempotency adapter around the existing immutable-release rollback operation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, build_opener

IDENTITY_KEYS = (
    "git_sha",
    "artifact_sha256",
    "image_digest",
    "product_version",
    "release_id",
)
SCRIPT_DIR = Path(__file__).resolve().parent


class RecoveryError(ValueError):
    pass


def identity(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RecoveryError("release_identity_required")
    result = {key: value.get(key, "") for key in IDENTITY_KEYS}
    if not all(isinstance(item, str) for item in result.values()):
        raise RecoveryError("invalid_release_identity")
    if not re.fullmatch(r"[0-9a-f]{40}", result["git_sha"]) or not re.fullmatch(
        r"[0-9a-f]{64}", result["artifact_sha256"]
    ):
        raise RecoveryError("invalid_release_identity")
    version = result["product_version"]
    if (
        not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version)
        or result["release_id"] != f"xcagi-{version}-{result['git_sha']}"
    ):
        raise RecoveryError("invalid_release_identity")
    if result["image_digest"] and not re.fullmatch(r"sha256:[0-9a-f]{64}", result["image_digest"]):
        raise RecoveryError("invalid_release_identity")
    return result


def request_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecoveryError("rollback_request_required")
    value = value.get("payload", value)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("request_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value["request_id"])
    ):
        raise RecoveryError("invalid_rollback_request_id")
    reason = value.get("reason")
    if reason not in ("experiment_regression", "original_customer_reopened"):
        raise RecoveryError("unsupported_rollback_reason")
    expected, target = (
        identity(value.get("expected_identity")),
        identity(value.get("target_identity")),
    )
    if expected == target:
        raise RecoveryError("rollback_target_must_differ")
    return {
        "request_id": value["request_id"],
        "expected_identity": expected,
        "target_identity": target,
        "reason": reason,
    }


def _plain_path(path: Path) -> Path:
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise RecoveryError("unsafe_rollback_state_path")
    return path.resolve()


def _release(path: Path, releases: Path) -> dict[str, str]:
    path = _plain_path(path)
    if path.parent != releases or not re.fullmatch(r"[0-9a-f]{40}", path.name):
        raise RecoveryError("rollback_requires_immutable_release")
    manifest = path / ".xcmax-release.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise RecoveryError("rollback_release_manifest_missing")
    result = identity(json.loads(manifest.read_text()))
    if result["git_sha"] != path.name:
        raise RecoveryError("rollback_release_directory_mismatch")
    return result


def _current(current: Path, releases: Path) -> dict[str, str]:
    _plain_path(current.parent)
    if not current.is_symlink():
        raise RecoveryError("current_release_link_required")
    target = Path(os.readlink(current))
    return _release(target if target.is_absolute() else current.parent / target, releases)


def _save(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stream.name, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_health(url: str) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise RecoveryError("invalid_rollback_health_url")
    with build_opener(ProxyHandler({})).open(url, timeout=10) as response:
        return json.loads(response.read(1024 * 1024))


def _verify_health(target: dict[str, str], env: dict[str, str], read_health) -> None:
    for key in ("HEALTH_URL", "SCHEDULER_HEALTH_URL", "PUBLIC_HEALTH_URL"):
        if not env.get(key):
            raise RecoveryError("rollback_health_endpoint_required")
        observed = read_health(env[key])
        if (
            not isinstance(observed, dict)
            or observed.get("ok") is not True
            or observed.get("deploy_tier") != "production"
        ):
            raise RecoveryError("rollback_health_not_ready")
        for field in ("git_sha", "artifact_sha256", "release_id"):
            if observed.get(field) != target[field]:
                raise RecoveryError("rollback_health_identity_mismatch")
        if target["image_digest"] and observed.get("image_digest") != target["image_digest"]:
            raise RecoveryError("rollback_health_identity_mismatch")
    if _payment_present():
        payment = read_health("http://127.0.0.1:8080/actuator/info")
        actual = payment.get("xcmax") if isinstance(payment, dict) else None
        expected = {
            "git-sha": target["git_sha"],
            "release-id": target["git_sha"],
            "artifact-sha256": target["artifact_sha256"],
        }
        if not isinstance(actual, dict) or any(
            actual.get(key) != val for key, val in expected.items()
        ):
            raise RecoveryError("rollback_payment_identity_mismatch")


def _payment_present() -> bool:
    return (
        subprocess.run(
            ["systemctl", "cat", "modstore-payment.service"],
            capture_output=True,
            timeout=10,
        ).returncode
        == 0
    )


def _run_native(env: dict[str, str], lock_fd: int) -> None:
    program = """set -euo pipefail
. "$1"
PAYMENT_SERVICE_PRESENT=0
PAYMENT_JAVA_BIN=/usr/bin/java
if systemctl cat modstore-payment.service >/dev/null 2>&1; then
  PAYMENT_SERVICE_PRESENT=1
  resolve_java_home
  PAYMENT_JAVA_BIN="$JAVA_HOME/bin/java"
fi
RUNTIME_NODE_BIN="$(command -v node)"
RUNTIME_NODE_BIN="$(readlink -f "$RUNTIME_NODE_BIN")"
[[ -x "$RUNTIME_NODE_BIN" ]] || fail "rollback Node runtime is unavailable"
acquire_publication_lock
rollback
if [[ "$PAYMENT_SERVICE_PRESENT" == 1 ]]; then
  verify_payment_identity "$PREVIOUS_SHA" "$PREVIOUS_ARTIFACT_SHA"
fi
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            program,
            "immutable-recovery",
            str(SCRIPT_DIR / "immutable_release_runtime.sh"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        pass_fds=(lock_fd,),
    )
    if result.returncode:
        raise RecoveryError("native_rollback_failed")


def recover(
    value: Any, *, env: dict[str, str], run_native=_run_native, read_health=_read_health
) -> dict[str, Any]:
    request = request_payload(value)
    base = _plain_path(Path(env["RELEASE_BASE"]))
    if str(base) != "/opt/xcmax" and env.get("XCMAX_ALLOW_CUSTOM_RELEASE_BASE") != "1":
        raise RecoveryError("custom_release_base_not_authorized")
    releases = _plain_path(Path(env["RELEASES_DIR"]))
    if releases != base / "releases":
        raise RecoveryError("invalid_releases_directory")
    state = _plain_path(Path(env["RUNTIME_DIR"])) / "release-recovery"
    if state.is_relative_to(releases):
        raise RecoveryError("rollback_state_must_survive_pruning")
    _plain_path(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(request["request_id"].encode()).hexdigest()
    receipt = state / f"{key}.json"
    _plain_path(receipt)
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    lock_path = _plain_path(Path(env["LOCK_FILE"]))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("immutable_release_busy") from exc
        previous = json.loads(receipt.read_text()) if receipt.exists() else None
        if previous is not None and not isinstance(previous, dict):
            raise RecoveryError("invalid_rollback_receipt")
        if previous and previous.get("request_sha256") != digest:
            raise RecoveryError("rollback_request_conflict")
        current = Path(env["CURRENT_LINK"])
        expected, target = request["expected_identity"], request["target_identity"]
        target_root = releases / target["git_sha"]
        if _release(target_root, releases) != target:
            raise RecoveryError("rollback_target_identity_mismatch")
        observed = _current(current, releases)
        if observed not in (expected, target):
            raise RecoveryError("production_identity_changed")
        if previous and previous.get("status") == "rollback_verified" and observed != target:
            raise RecoveryError("rollback_receipt_superseded")
        replayed = observed == target
        record = {
            **request,
            "request_sha256": digest,
            "status": "submitted",
            "submitted": True,
        }
        _save(receipt, record)
        try:
            if not replayed:
                release_env = Path(env["ENV_DIR"]) / "modstore-release.env"
                settings = dict(
                    line.split("=", 1)
                    for line in release_env.read_text().splitlines()
                    if "=" in line
                )
                native_env = {
                    **env,
                    "PREVIOUS_ROOT": str(target_root),
                    "PREVIOUS_SHA": target["git_sha"],
                    "PREVIOUS_ARTIFACT_SHA": target["artifact_sha256"],
                    "PREVIOUS_RELEASE_ID": target["release_id"],
                    "PREVIOUS_VERSION": target["product_version"],
                    "PRODUCT_VERSION": target["product_version"],
                }
                for setting, variable in (
                    ("MODMAN_LIBRARY", "LIBRARY_DIR"),
                    ("MODSTORE_CATALOG_DIR", "CATALOG_DIR"),
                    ("MODSTORE_RUNTIME_DIR", "RUNTIME_DIR"),
                ):
                    path = _plain_path(Path(settings[setting]))
                    if path.is_relative_to(releases):
                        raise RecoveryError("rollback_cannot_move_runtime_data")
                    native_env[variable] = str(path)
                native_env["PREVIOUS_LIBRARY_DIR"] = native_env["LIBRARY_DIR"]
                native_env["GITHUB_REPOSITORY_SLUG"] = settings.get(
                    "MODSTORE_CAPABILITY_PROPOSAL_REPO", ""
                )
                # The child inherits this exact kernel lock even if the parent dies.
                run_native(native_env, lock.fileno())
            if _current(current, releases) != target:
                raise RecoveryError("rollback_pointer_identity_mismatch")
            _verify_health(target, env, read_health)
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
            _save(
                receipt,
                {
                    **record,
                    "status": "readback_required",
                    "error": str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__,
                },
            )
            raise
        result = {
            **record,
            "status": "rollback_verified",
            "identity": target,
            "replayed": replayed,
        }
        _save(receipt, result)
        return result


def main() -> int:
    try:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise RecoveryError("rollback_request_too_large")
        result = recover(json.loads(raw), env=dict(os.environ))
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "status": "rollback_unverified",
                    "error": str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__,
                }
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
