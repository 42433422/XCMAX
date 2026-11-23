"""Exercise native DR activation against real HTTP and isolated file state.

Only the host's systemd and prepare commands are replaced. Bash, curl, identity
verification, atomic symlink moves, marker writes and compensation run unchanged.
"""

from __future__ import annotations

import fcntl
import http.server
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "xcmax_dr_apply_release.sh"
ORDER = SCRIPT.with_name("xcmax_release_order.py")


class ReleaseActivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.runtime = self.root / "runtime"
        self.bin = self.root / "bin"
        for directory in (self.state, self.runtime, self.bin):
            directory.mkdir()
        self.order = self.bin / "xcmax-release-order"
        shutil.copyfile(ORDER, self.order)
        self.order.chmod(0o755)  # Same executable installation as xcmax_dr_install.sh.
        self.component = "modstore"
        self.old_sha, self.new_sha = "a" * 40, "b" * 40
        self.old = self.make_release(self.old_sha)
        self.new = self.make_release(self.new_sha)
        self.current = self.runtime / "source"
        self.current.symlink_to(self.old, target_is_directory=True)
        self.active = self.root / "active"
        self.active.touch()
        self.events = self.root / "events"
        self.events.touch()
        self.write_marker("sha", self.old_sha)
        self.write_marker("created_at", "100")
        (self.state / "release_applied_sha").write_text(self.old_sha + "\n")
        self.bad_sha: set[str] = set()
        self.bad_components: set[str] = set()
        self.observed: list[str] = []
        self.health_change = lambda _component: None
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                component = (
                    "fhd" if self.path.endswith("?component=fhd") else "modstore"
                )
                current = owner.runtime / ("fhd" if component == "fhd" else "source")
                manifest_name = (
                    "fhd-manifest.json" if component == "fhd" else ".xcmax-release.json"
                )
                manifest = json.loads((current.resolve() / manifest_name).read_text())
                sha = manifest["git_sha"]
                owner.observed.append(sha)
                identity = {
                    "git_sha": sha,
                    "release_id": manifest["release_id"],
                    "artifact_sha256": manifest.get(
                        "artifact_sha256", manifest.get("sha256")
                    ),
                }
                if sha in owner.bad_sha or component in owner.bad_components:
                    identity["artifact_sha256"] = "0" * 64
                if component == "fhd":
                    identity["product_version"] = manifest["version"]
                    payload = {
                        "status": "healthy",
                        "degradedReasons": [],
                        "build": identity,
                        "git_sha": sha,
                        "release_id": manifest["release_id"],
                    }
                else:
                    payload = {"ok": True, **identity}
                data = json.dumps(payload).encode()
                owner.health_change(component)
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args: object) -> None:
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.env = dict(
            os.environ,
            FIXTURE_ROOT=str(self.root),
            HEALTH_URL=f"http://127.0.0.1:{server.server_port}/api/health",
            REAL_CURL=shutil.which("curl") or "/usr/bin/curl",
            OPS_DR_HEALTH_WAIT_SECONDS="1",
        )
        self.env["PATH"] = f"{self.bin}:{os.environ['PATH']}"
        self.executable(
            "curl",
            """#!/usr/bin/env python3
import os, sys
args = [os.environ['HEALTH_URL'] + ('?component=fhd' if ':15100/' in arg else '?component=modstore')
        if arg.startswith('http://127.0.0.1:') else arg for arg in sys.argv[1:]]
os.execv(os.environ['REAL_CURL'], [os.environ['REAL_CURL'], *args])
""",
        )
        self.executable(
            "systemctl",
            """#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
with (root / 'events').open('a') as handle:
    handle.write('systemctl ' + ' '.join(sys.argv[1:]) + '\\n')
active = root / 'active'
if sys.argv[1] == 'is-active':
    raise SystemExit(0 if active.exists() else 3)
if sys.argv[1] == 'stop':
    active.unlink(missing_ok=True)
elif sys.argv[1] in ('restart', 'start'):
    active.touch()
""",
        )
        self.executable(
            "prepare",
            """#!/usr/bin/env python3
import os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
with (root / 'events').open('a') as handle:
    handle.write('prepare ' + ' '.join(sys.argv[1:]) + '\\n')
current = root / 'runtime' / os.environ.get('CURRENT_NAME', 'source')
if current.resolve().name == os.environ.get('PREPARE_FAIL_SHA'):
    if os.environ.get('COMPETING_TARGET'):
        current.unlink()
        current.symlink_to(os.environ['COMPETING_TARGET'], target_is_directory=True)
    raise SystemExit(17)
""",
        )

    def executable(self, name: str, content: str) -> None:
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def manifest(self, target: Path) -> Path:
        return target / (
            ".xcmax-release.json"
            if self.component == "modstore"
            else "fhd-manifest.json"
        )

    def make_release(self, sha: str) -> Path:
        target = self.root / sha
        target.mkdir(exist_ok=True)
        payload = {"git_sha": sha, "release_id": f"xcagi-1.2.3-{sha}"}
        if self.component == "modstore":
            payload.update(product_version="1.2.3", artifact_sha256=sha[0] * 64)
        else:
            payload.update(version="1.2.3", sha256=sha[0] * 64)
        self.manifest(target).write_text(json.dumps(payload))
        return target

    def write_marker(self, suffix: str, value: str) -> None:
        (self.state / f"release_applied_{self.component}_{suffix}").write_text(
            value + "\n"
        )

    def add_fhd_release(self, sha: str) -> None:
        self.component = "fhd"
        target = self.make_release(sha)
        (self.runtime / "fhd").symlink_to(target, target_is_directory=True)
        self.write_marker("sha", sha)
        self.component = "modstore"

    def run_function(
        self, name: str, *args: str, extra: str = ""
    ) -> subprocess.CompletedProcess[str]:
        values = {
            "STATE": self.state,
            "RUNTIME": self.runtime,
            "INCOMING": self.root / "incoming",
            "LOG": self.root / "apply.log",
            "LOCK": self.root / "release.lock",
            "PREPARE_RUNTIME": self.bin / "prepare",
            "RELEASE_ORDER": self.order,
        }
        command = f"source {shlex.quote(str(SCRIPT))}\n"
        command += "\n".join(
            f"{key}={shlex.quote(str(value))}" for key, value in values.items()
        )
        command += "\n" + extra + "\n" + name + " " + " ".join(map(shlex.quote, args))
        return subprocess.run(
            ["bash", "-c", command],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=20,
        )

    def activate(self) -> subprocess.CompletedProcess[str]:
        return self.run_function(
            "activate_component",
            self.component,
            str(self.new),
            str(self.manifest(self.new)),
            self.new_sha,
            "200",
            extra="VERIFY_CURRENT=0\nacquire_release_lock",
        )

    @property
    def pending(self) -> Path:
        return self.state / f"release_apply_{self.component}.pending"

    def assert_old_markers(self) -> None:
        for suffix, value in (("sha", self.old_sha), ("created_at", "100")):
            self.assertEqual(
                (self.state / f"release_applied_{self.component}_{suffix}")
                .read_text()
                .strip(),
                value,
            )

    def test_success_requires_http_identity_before_markers_advance(self) -> None:
        result = self.activate()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.current.resolve(), self.new)
        self.assertIn(self.new_sha, self.observed)
        self.assertEqual(
            (self.state / "release_applied_modstore_sha").read_text().strip(),
            self.new_sha,
        )
        self.assertFalse(self.pending.exists())
        self.assertIn("prepare --release-update", self.events.read_text())
        self.assertFalse((self.state / "release_applied_sha").exists())

    def test_promotion_readback_requires_applied_identity_and_no_pending_attempt(
        self,
    ) -> None:
        verified = self.run_function("verify_current_component", self.component)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.pending.mkdir()
        pending = self.run_function("verify_current_component", self.component)
        self.assertNotEqual(pending.returncode, 0)
        self.pending.rmdir()
        self.bad_sha.add(self.old_sha)
        wrong = self.run_function("verify_current_component", self.component)
        self.assertNotEqual(wrong.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()

    def test_paired_release_accepts_matching_aggregate_and_both_live_identities(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        result = self.run_function("verify_current_release_pair")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.observed, [self.old_sha, self.old_sha])

    def test_paired_release_rejects_independently_healthy_different_commits(
        self,
    ) -> None:
        self.add_fhd_release(self.new_sha)
        for component in ("modstore", "fhd"):
            result = self.run_function("verify_current_component", component)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.observed, [self.old_sha, self.new_sha])
        self.observed.clear()
        result = self.run_function("verify_current_release_pair")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("发布组件 SHA 不一致", result.stdout)
        self.assertEqual(self.observed, [])

    def test_paired_release_rejects_missing_invalid_or_unrelated_aggregate(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        aggregate = self.state / "release_applied_sha"
        for value in (None, "invalid", "c" * 40):
            with self.subTest(aggregate=value):
                aggregate.unlink(missing_ok=True)
                if value is not None:
                    aggregate.write_text(value + "\n")
                result = self.run_function("verify_current_release_pair")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stdout)
                self.assertEqual(self.observed, [])

    def test_healthy_components_require_a_matching_release_pair(self) -> None:
        fhd_marker = self.state / "release_applied_fhd_sha"
        pair_marker = self.state / "release_applied_sha"
        health = 'verify_current_component() { printf "%s\n" "$1"; }'
        fhd_marker.write_text(self.new_sha + "\n")
        self.assertNotEqual(
            self.run_function("verify_current_release_pair", extra=health).returncode, 0
        )
        pair_marker.unlink()
        self.assertNotEqual(
            self.run_function("verify_current_release_pair", extra=health).returncode, 0
        )
        fhd_marker.write_text(self.old_sha + "\n")
        pair_marker.write_text(self.old_sha + "\n")
        paired = self.run_function("verify_current_release_pair", extra=health)
        self.assertEqual(paired.returncode, 0, paired.stderr)
        self.assertEqual(paired.stdout.splitlines(), ["modstore", "fhd"])
        inactive = self.run_function(
            "verify_current_release_pair",
            extra='verify_current_component() { [[ "$1" == modstore ]]; }',
        )
        self.assertNotEqual(inactive.returncode, 0)

    def test_promotion_readback_cannot_report_success_when_apply_lock_is_busy(
        self,
    ) -> None:
        path = self.root / "release.lock"
        with path.open("w") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for verify, expected in ((1, 1), (0, 0)):
                with self.subTest(verify=verify):
                    result = self.run_function(
                        "acquire_release_lock",
                        extra=(
                            f"LOCK={shlex.quote(str(path))}\nVERIFY_CURRENT={verify}"
                        ),
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(self.events.read_text(), "")

    def test_status_exposes_pending_without_advertising_old_aggregate(self) -> None:
        self.pending.mkdir()
        self.executable("docker", "#!/bin/sh\nexit 1\n")
        result = subprocess.run(
            ["bash", str(SCRIPT.with_name("xcmax_dr_status.sh"))],
            env={
                **self.env,
                "OPS_DR_ROOT": str(self.root),
                "OPS_DR_STATE": str(self.state),
            },
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = dict(line.split("=", 1) for line in result.stdout.splitlines())
        self.assertEqual(status["release_modstore_pending"], "1")
        self.assertEqual(status["release_sha"], "")

    def test_http_200_with_wrong_artifact_restores_and_verifies_previous(self) -> None:
        self.add_fhd_release(self.old_sha)
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        self.bad_sha.add(self.new_sha)
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertTrue(self.active.exists())
        self.assertIn(self.new_sha, self.observed)
        self.assertEqual(self.observed[-1], self.old_sha)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())
        restored = self.run_function("verify_current_release_pair")
        self.assertEqual(restored.returncode, 0, restored.stderr + restored.stdout)

    def test_failed_candidate_restores_verified_previous_release_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        before = self.run_function("verify_current_release_pair")
        self.assertEqual(before.returncode, 0, before.stderr + before.stdout)
        self.env["PREPARE_FAIL_SHA"] = self.new_sha
        result = self.activate()
        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())
        after = self.run_function("verify_current_release_pair")
        self.assertEqual(after.returncode, 0, after.stderr + after.stdout)

    def test_failed_candidate_does_not_commit_a_mixed_previous_pair(self) -> None:
        self.add_fhd_release("c" * 40)
        self.bad_sha.add(self.new_sha)
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())
        self.assertNotEqual(
            self.run_function("verify_current_release_pair").returncode, 0
        )

    def test_failed_candidate_does_not_commit_an_unverified_partner(self) -> None:
        self.add_fhd_release(self.old_sha)
        manifest = self.old / "fhd-manifest.json"
        payload = json.loads(manifest.read_text())
        payload["git_sha"] = "c" * 40
        manifest.write_text(json.dumps(payload))
        self.bad_sha.add(self.new_sha)
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())
        self.assertNotEqual(
            self.run_function("verify_current_release_pair").returncode, 0
        )

    def test_verified_pair_receipt_survives_compensated_candidate_failure(self) -> None:
        self.add_fhd_release(self.old_sha)
        (self.state / "release_apply_last_success").write_text("123\n")
        before = {path.name: path.read_bytes() for path in self.state.iterdir()}
        self.assertEqual(self.run_function("verify_current_release_pair").returncode, 0)
        self.bad_sha.add(self.new_sha)

        failed = self.activate()

        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.state.iterdir()}, before
        )
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.bad_sha.clear()
        retried = self.activate()
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertEqual(self.current.resolve(), self.new)
        self.assertFalse((self.state / "release_applied_sha").exists())
        self.assertNotEqual(
            self.run_function("verify_current_release_pair").returncode, 0
        )

    def test_failed_activation_before_switch_retains_verified_pair_receipt(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        self.current.unlink()
        shutil.copytree(self.old, self.current)
        Path(str(self.current) + ".previous").mkdir()
        self.assertEqual(self.run_function("verify_current_release_pair").returncode, 0)

        failed = self.activate()

        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.current.is_symlink())
        self.assertFalse(self.pending.exists())
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_failed_fhd_prepare_preserves_verified_original_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        self.component = "fhd"
        self.make_release(self.new_sha)
        self.current = self.runtime / "fhd"
        self.env["CURRENT_NAME"] = "fhd"
        self.write_marker("created_at", "100")
        before = self.run_function("verify_current_release_pair")
        self.assertEqual(before.returncode, 0, before.stdout + before.stderr)
        self.env["PREPARE_FAIL_SHA"] = self.new_sha

        failed = self.activate()

        self.assertEqual(failed.returncode, 17, failed.stdout + failed.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(
            (self.state / "release_applied_sha").read_text().strip(), self.old_sha
        )
        self.assertEqual(self.observed[-2:], [self.old_sha, self.old_sha])

    def test_compensation_does_not_restore_a_mixed_release_receipt(self) -> None:
        self.add_fhd_release(self.new_sha)
        for failure in ("prepare", "identity"):
            with self.subTest(failure=failure):
                (self.state / "release_applied_sha").write_text(self.old_sha + "\n")
                if failure == "prepare":
                    self.env["PREPARE_FAIL_SHA"] = self.new_sha
                else:
                    self.env.pop("PREPARE_FAIL_SHA", None)
                    self.bad_sha.add(self.new_sha)
                failed = self.activate()
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(self.current.resolve(), self.old)
                self.assert_old_markers()
                self.assertFalse(self.pending.exists())
                self.assertFalse((self.state / "release_applied_sha").exists())
                self.assertNotEqual(
                    self.run_function("verify_current_release_pair").returncode, 0
                )

    def test_compensation_keeps_other_pending_or_unverified_component_blocked(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        self.bad_sha.add(self.new_sha)
        other_pending = self.state / "release_apply_fhd.pending"
        for failure in ("pending", "identity"):
            with self.subTest(failure=failure):
                (self.state / "release_applied_sha").write_text(self.old_sha + "\n")
                if failure == "pending":
                    other_pending.mkdir()
                else:
                    self.bad_components.add("fhd")
                self.assertNotEqual(self.activate().returncode, 0)
                self.assertEqual(self.current.resolve(), self.old)
                self.assert_old_markers()
                self.assertFalse(self.pending.exists())
                self.assertFalse((self.state / "release_applied_sha").exists())
                self.assertNotEqual(
                    self.run_function("verify_current_release_pair").returncode, 0
                )
                if failure == "pending":
                    self.assertTrue(other_pending.exists())
                    other_pending.rmdir()

    def test_compensation_never_invents_a_missing_original_pair_receipt(self) -> None:
        self.add_fhd_release(self.old_sha)
        (self.state / "release_applied_sha").unlink()
        self.bad_sha.add(self.new_sha)

        self.assertNotEqual(self.activate().returncode, 0)

        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())
        self.assertNotEqual(
            self.run_function("verify_current_release_pair").returncode, 0
        )

    def test_pair_restoration_rejects_changes_during_health_readback(self) -> None:
        self.add_fhd_release(self.old_sha)
        receipt = self.state / "release_applied_sha"
        for change in ("component", "pending", "receipt", "directory"):
            with self.subTest(change=change):
                receipt.unlink(missing_ok=True)
                self.write_marker("sha", self.old_sha)

                def change_during_health(component: str) -> None:
                    if component == "fhd":
                        if change == "component":
                            self.write_marker("sha", self.new_sha)
                        elif change == "pending":
                            self.pending.mkdir()
                        elif change == "directory":
                            receipt.mkdir()
                        else:
                            receipt.write_text(self.new_sha + "\n")

                self.health_change = change_during_health
                result = self.run_function(
                    "restore_previous_release_pair", self.old_sha
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                if change == "receipt":
                    self.assertEqual(receipt.read_text().strip(), self.new_sha)
                elif change == "directory":
                    self.assertEqual(list(receipt.iterdir()), [])
                    receipt.rmdir()
                else:
                    self.assertFalse(receipt.exists())
                self.assertEqual(list(self.state.glob(".release_applied_sha.*")), [])
                if change == "pending":
                    self.pending.rmdir()

    def assert_failed_candidate_preserves_pair(self, component: str) -> None:
        self.add_fhd_release(self.old_sha)
        self.component = component
        self.current = self.runtime / ("fhd" if component == "fhd" else "source")
        self.make_release(self.new_sha)
        self.write_marker("created_at", "100")
        self.env["CURRENT_NAME"] = self.current.name
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        self.bad_sha.add(self.new_sha)
        failed = self.activate()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())
        restored = self.run_function("verify_current_release_pair")
        self.assertEqual(restored.returncode, 0, restored.stderr + restored.stdout)

    def test_failed_modstore_candidate_restores_verified_pair(self) -> None:
        self.assert_failed_candidate_preserves_pair("modstore")

    def test_failed_fhd_candidate_restores_verified_pair(self) -> None:
        self.assert_failed_candidate_preserves_pair("fhd")

    def test_untouched_bootstrap_failure_preserves_verified_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        self.current.unlink()
        shutil.copytree(self.old, self.current)
        Path(str(self.current) + ".previous").mkdir()
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.current.is_dir())
        self.assertFalse(self.current.is_symlink())
        self.assertFalse(self.pending.exists())
        verified = self.run_function("verify_current_release_pair")
        self.assertEqual(verified.returncode, 0, verified.stderr + verified.stdout)
        self.assertNotIn("systemctl stop", self.events.read_text())

    def test_compensation_does_not_invent_a_previous_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        self.bad_sha.add(self.new_sha)
        aggregate = self.state / "release_applied_sha"
        for original in (None, "invalid", "c" * 40):
            with self.subTest(original=original):
                aggregate.unlink(missing_ok=True)
                if original is not None:
                    aggregate.write_text(original + "\n")
                self.assertNotEqual(self.activate().returncode, 0)
                self.assertEqual(self.current.resolve(), self.old)
                self.assertFalse(self.pending.exists())
                self.assertFalse(aggregate.exists())

    def test_compensation_rechecks_peer_health_before_restoring_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        self.bad_sha.add(self.new_sha)
        self.bad_components.add("fhd")
        self.assertNotEqual(self.activate().returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())

    def test_compensation_does_not_commit_a_mixed_release_pair(self) -> None:
        self.add_fhd_release(self.new_sha)
        self.env["PREPARE_FAIL_SHA"] = self.new_sha
        self.assertNotEqual(self.activate().returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertEqual((self.runtime / "fhd").resolve(), self.new)
        self.assertFalse(self.pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())

    def test_compensation_preserves_unresolved_peer_switch(self) -> None:
        self.add_fhd_release(self.old_sha)
        peer_pending = self.state / "release_apply_fhd.pending"
        peer_pending.mkdir()
        self.bad_sha.add(self.new_sha)
        self.assertNotEqual(self.activate().returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse(self.pending.exists())
        self.assertTrue(peer_pending.exists())
        self.assertFalse((self.state / "release_applied_sha").exists())

    def test_compensation_never_reinstates_an_invalid_original_pair_receipt(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        aggregate = self.state / "release_applied_sha"
        aggregate.write_text("invalid\n")
        self.env["PREPARE_FAIL_SHA"] = self.new_sha

        failed = self.activate()

        self.assertEqual(failed.returncode, 17, failed.stdout + failed.stderr)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())
        self.assertFalse(aggregate.exists())
        self.assertNotEqual(
            self.run_function("verify_current_release_pair").returncode, 0
        )

    def test_prepare_failure_restores_without_accepting_candidate(self) -> None:
        self.env["PREPARE_FAIL_SHA"] = self.new_sha
        result = self.activate()
        self.assertEqual(result.returncode, 17)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertEqual(self.observed, [self.old_sha])
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())

    def test_failed_candidate_restores_verified_release_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        for failure in ("identity", "prepare"):
            with self.subTest(failure=failure):
                self.bad_sha.clear()
                self.env.pop("PREPARE_FAIL_SHA", None)
                if failure == "identity":
                    self.bad_sha.add(self.new_sha)
                else:
                    self.env["PREPARE_FAIL_SHA"] = self.new_sha
                result = self.activate()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.current.resolve(), self.old)
                self.assert_old_markers()
                self.assertFalse(self.pending.exists())
                verified = self.run_function("verify_current_release_pair")
                self.assertEqual(
                    verified.returncode, 0, verified.stdout + verified.stderr
                )
                self.assertEqual(
                    (self.state / "release_applied_sha").read_text().strip(),
                    self.old_sha,
                )

    def test_compensation_does_not_certify_an_unverified_or_mixed_pair(self) -> None:
        self.add_fhd_release(self.old_sha)
        aggregate = self.state / "release_applied_sha"
        other = self.state / "release_applied_fhd_sha"
        pending = self.state / "release_apply_fhd.pending"
        for case in ("missing", "invalid", "mixed", "pending", "unhealthy"):
            with self.subTest(case=case):
                aggregate.write_text(self.old_sha + "\n")
                other.write_text(self.old_sha + "\n")
                if pending.exists():
                    pending.rmdir()
                self.bad_components.clear()
                if case == "missing":
                    aggregate.unlink()
                elif case == "invalid":
                    aggregate.write_text("unknown\n")
                elif case == "mixed":
                    other.write_text(self.new_sha + "\n")
                elif case == "pending":
                    pending.mkdir()
                else:
                    self.bad_components.add("fhd")
                self.bad_sha.add(self.new_sha)
                result = self.activate()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.current.resolve(), self.old)
                self.assertFalse(aggregate.exists())
                self.assertNotEqual(
                    self.run_function("verify_current_release_pair").returncode, 0
                )

    def test_pair_receipt_replacement_failure_leaves_no_unverified_receipt(
        self,
    ) -> None:
        self.add_fhd_release(self.old_sha)
        self.bad_sha.add(self.new_sha)
        real_ln = shutil.which("ln")
        self.assertIsNotNone(real_ln)
        self.executable(
            "ln",
            "#!/bin/bash\n"
            'if [[ "${!#}" == "$FIXTURE_ROOT/state/release_applied_sha" ]]; then\n'
            '  touch "$FIXTURE_ROOT/receipt-publish-attempted"\n'
            "  exit 23\n"
            "fi\n"
            f'exec {shlex.quote(real_ln)} "$@"\n',
        )
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assert_old_markers()
        self.assertTrue((self.root / "receipt-publish-attempted").is_file())
        self.assertFalse((self.state / "release_applied_sha").exists())
        self.assertEqual(list(self.state.glob(".release_applied_sha.*")), [])

    def test_unverified_previous_retains_pending_and_rejects_retry(self) -> None:
        self.bad_sha.update((self.old_sha, self.new_sha))
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertTrue(self.pending.is_dir())
        self.assert_old_markers()
        events = self.events.read_text()
        self.assertNotEqual(self.activate().returncode, 0)
        self.assertEqual(self.events.read_text(), events)

    def test_competing_pointer_is_not_overwritten_by_compensation(self) -> None:
        competitor = self.make_release("c" * 40)
        self.env.update(PREPARE_FAIL_SHA=self.new_sha, COMPETING_TARGET=str(competitor))
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), competitor)
        self.assertTrue(self.pending.is_dir())
        self.assert_old_markers()
        self.assertNotIn("systemctl stop", self.events.read_text())

    def test_invalid_previous_identity_refuses_before_service_change(self) -> None:
        self.manifest(self.old).write_text(json.dumps({"git_sha": self.old_sha}))
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertEqual(self.events.read_text(), "")
        self.assertFalse(self.pending.exists())

    def test_directory_bootstrap_retains_recoverable_previous(self) -> None:
        self.current.unlink()
        shutil.copytree(self.old, self.current)
        self.bad_sha.add(self.new_sha)
        result = self.activate()
        self.assertNotEqual(result.returncode, 0)
        previous = Path(str(self.current) + ".previous")
        self.assertEqual(self.current.resolve(), previous)
        self.assertTrue(self.manifest(previous).is_file())
        self.assertTrue(self.active.exists())
        self.assertEqual(self.observed[-1], self.old_sha)
        self.assert_old_markers()
        self.assertFalse(self.pending.exists())

    def test_fhd_standby_stays_stopped_without_claiming_live_readback(self) -> None:
        self.component = "fhd"
        self.make_release(self.old_sha)
        self.make_release(self.new_sha)
        self.current = self.runtime / "fhd"
        self.current.symlink_to(self.old, target_is_directory=True)
        self.active.unlink()
        self.env["CURRENT_NAME"] = "fhd"
        self.write_marker("sha", self.old_sha)
        self.write_marker("created_at", "100")
        result = self.activate()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.current.resolve(), self.new)
        self.assertFalse(self.active.exists())
        self.assertEqual(self.observed, [])
        self.assertNotIn("systemctl restart", self.events.read_text())
        self.assertIn("运行身份仍待 promotion 验证", result.stdout)

    def test_copied_environment_does_not_mutate_rollback_dependencies(self) -> None:
        source, destination = self.root / "old-venv", self.root / "new-venv"
        (source / "bin").mkdir(parents=True)
        python = source / "bin/python"
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o755)
        package = source / "package.py"
        package.write_text("old dependency")
        command = f"source {shlex.quote(str(SCRIPT))}\ncopy_release_environment "
        command += " ".join(
            map(shlex.quote, [str(source), "/nonexistent", str(destination)])
        )
        subprocess.run(
            ["bash", "-c", command], check=True, capture_output=True, timeout=10
        )
        (destination / "package.py").write_text("new dependency")
        self.assertEqual(package.read_text(), "old dependency")
        self.assertNotEqual(
            package.stat().st_ino, (destination / "package.py").stat().st_ino
        )


if __name__ == "__main__":
    unittest.main()
