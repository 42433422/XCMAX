from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


class BootstrapPreflightTests(unittest.TestCase):
    def test_workflow_manifest_gate_rejects_wrong_sha_and_unsafe_artifact(self) -> None:
        workflow = (ROOT / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")
        match = re.search(
            r"RELEASE_FIELDS=.*?<<'PY'\n(.*?)\n\s*PY\n\s*\)\"",
            workflow,
            re.S,
        )
        self.assertIsNotNone(match, "could not extract the bootstrap manifest verifier")
        code = textwrap.dedent(match.group(1))
        release_sha = "a" * 40
        manifest = {
            "git_sha": release_sha,
            "artifact": "fhd-full-1.2.3-aaaaaaaaaaaa.tar.gz",
            "sha256": "b" * 64,
            "archive_verifier_sha256": "d" * 64,
        }
        with tempfile.TemporaryDirectory(prefix="fhd-bootstrap-preflight-") as td:
            path = Path(td) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            valid = subprocess.run(
                [
                    "python3",
                    "-c",
                    code,
                    str(path),
                    release_sha,
                    "production",
                    "apply-latest",
                    manifest["sha256"],
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(
                valid.stdout.strip().rsplit("|", 1)[0],
                "|".join(
                    (
                        release_sha,
                        manifest["artifact"],
                        manifest["sha256"],
                        manifest["archive_verifier_sha256"],
                    )
                ),
            )

            self.assertEqual(
                json.loads(base64.b64decode(valid.stdout.strip().rsplit("|", 1)[1])), manifest
            )

            wrong_sha = subprocess.run(
                [
                    "python3",
                    "-c",
                    code,
                    str(path),
                    "c" * 40,
                    "production",
                    "apply-latest",
                    manifest["sha256"],
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(wrong_sha.returncode, 0)
            self.assertIn("manifest git_sha differs from authorized release_sha", wrong_sha.stderr)
            wrong_artifact = subprocess.run(
                [
                    "python3",
                    "-c",
                    code,
                    str(path),
                    release_sha,
                    "production",
                    "apply-latest",
                    "e" * 64,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(wrong_artifact.returncode, 0)
            self.assertIn(
                "manifest artifact differs from dispatched release_artifact_sha256",
                wrong_artifact.stderr,
            )
            manifest["artifact"] = "../fhd-full-1.2.3.tar.gz"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            unsafe_path = subprocess.run(
                [
                    "python3",
                    "-c",
                    code,
                    str(path),
                    release_sha,
                    "production",
                    "apply-latest",
                    manifest["sha256"],
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(unsafe_path.returncode, 0)
            self.assertIn(
                "manifest artifact is not a safe FHD tarball basename", unsafe_path.stderr
            )

    def test_staging_apply_never_substitutes_a_queued_release(self) -> None:
        """Execute the workflow's SSH body and real updater; only the host/apply boundary is local."""
        workflow = yaml.safe_load((ROOT / ".github/workflows/fhd-deploy.yml").read_text())
        steps = workflow["jobs"]["cvm-rolling"]["steps"]
        script = next(
            step["run"] for step in steps if step["name"] == "SSH rolling restart / apply"
        )
        verifier = ROOT / "FHD/scripts/deploy/lib/verify_release_archive.py"
        verifier_source = verifier.read_bytes()
        required = runpy.run_path(str(verifier))["REQUIRED_RUNTIME_MEMBERS"]
        updater = (ROOT / "FHD/scripts/deploy/fhd-auto-update.sh").read_bytes()
        selected_sha, next_sha = "a" * 40, "c" * 40

        with tempfile.TemporaryDirectory(prefix="fhd-staging-bound-release-") as td:
            for drift in ("while_queued", "while_waiting_for_lock", "frozen"):
                with self.subTest(drift=drift):
                    root = Path(td) / drift
                    channel, runtime, bin_dir = (
                        root / name for name in ("channel", "runtime", "bin")
                    )
                    for directory in (channel, runtime, bin_dir):
                        directory.mkdir(parents=True)
                    trusted = runtime / "scripts/deploy/lib/verify_release_archive.py"
                    trusted.parent.mkdir(parents=True)
                    trusted.write_bytes(verifier_source)
                    sources = {
                        "scripts/deploy/lib/verify_release_archive.py": verifier_source,
                        "scripts/deploy/fhd-auto-update.sh": updater,
                        "scripts/deploy/lib/dora_event.sh": b"dora_emit_deployment() { return 0; }\n",
                        "scripts/deploy/fhd-apply-release.sh": (
                            b'#!/bin/bash\nset -eu\nprintf "%s\\n" "$FHD_GIT_SHA" >> "$APPLY_MARKER"\n'
                            b'printf "%s\\n" "$FHD_GIT_SHA" > "$FHD_DEPLOY_ROOT/.deploy-git-sha"\n'
                        ),
                    }
                    manifests = []
                    for sha in (selected_sha, next_sha):
                        artifact = channel / f"fhd-full-1.2.3-{sha[:12]}.tar.gz"
                        with tarfile.open(artifact, "w:gz") as archive:
                            for name in ("scripts", "scripts/deploy", "scripts/deploy/lib"):
                                member = tarfile.TarInfo("./" + name)
                                member.type, member.mode = tarfile.DIRTYPE, 0o755
                                archive.addfile(member)
                            for name in sorted(required | sources.keys()):
                                data = sources.get(name, sha.encode())
                                member = tarfile.TarInfo("./" + name)
                                member.size, member.mode = len(data), 0o755
                                archive.addfile(member, io.BytesIO(data))
                        manifests.append(
                            {
                                "git_sha": sha,
                                "artifact": artifact.name,
                                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                                "archive_verifier_sha256": hashlib.sha256(
                                    verifier_source
                                ).hexdigest(),
                                "admin_console_sha256": "d" * 64,
                                "channel": "staging",
                                "version": "1.2.3",
                            }
                        )
                    manifest, advance = channel / "fhd-manifest.json", root / "next-manifest.json"
                    manifest.write_text(json.dumps(manifests[int(drift == "while_queued")]))
                    advance.write_text(json.dumps(manifests[1]))
                    if drift == "frozen":
                        Path(str(manifest) + ".frozen").touch()
                    env_file = root / "staging.env"
                    env_file.write_text(
                        "".join(
                            f"XCAGI_NEURO_BUS_{name}=1\n"
                            for name in (
                                "DEDUP",
                                "CIRCUIT",
                                "RATE_LIMIT",
                                "TRACE",
                                "LIFELINE",
                                "DLQ_AUTO",
                                "SLA_LOG",
                            )
                        )
                    )
                    for name, body in {
                        "ssh": "exec bash -s",
                        "curl": 'printf \'{"git_sha":"%s"}\\n\' "$(cat "$FHD_DEPLOY_ROOT/.deploy-git-sha")"',
                        "flock": (
                            '[ "$ADVANCE_ON_LOCK" != "1" ] || cp "$ADVANCE_MANIFEST" "$LATEST_MANIFEST"\n'
                            f'exec "{shutil.which("flock")}" "$@"'
                        ),
                    }.items():
                        executable = bin_dir / name
                        executable.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
                        executable.chmod(0o755)
                    local = script
                    for before, after in {
                        "/opt/fhd-staging": runtime,
                        "/var/www/update/releases/staging/server/fhd-manifest.json": manifest,
                        "/root/fhd-staging.env": env_file,
                        "/tmp/fhd-staging-auto-update.lock": root / "update.lock",
                        "/tmp/health.json": root / "health.json",
                    }.items():
                        local = local.replace(before, str(after))
                    marker = root / "applied-shas"
                    result = subprocess.run(
                        ["bash", "-c", local],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                        env={
                            **os.environ,
                            "PATH": f"{bin_dir}:{os.environ['PATH']}",
                            "TARGET_ENV": "staging",
                            "ACTION": "apply-latest",
                            "ACTION_ID": "loop:test",
                            "RELEASE_SHA": selected_sha,
                            "RELEASE_ARTIFACT_SHA256": manifests[0]["sha256"],
                            "PRESERVE_RELEASE_HISTORY": "0",
                            "FHD_PUSH_HOST": "fixture.invalid",
                            "FHD_PUSH_USER": "fixture",
                            "FHD_PUSH_SSH_KEY_RAW": "fixture-only",
                            "RUNNER_TEMP": str(root),
                            "FHD_DEPLOY_ROOT": str(runtime),
                            "FHD_DEPLOY_LOG": str(root / "deploy.log"),
                            "APPLY_MARKER": str(marker),
                            "ADVANCE_MANIFEST": str(advance),
                            "LATEST_MANIFEST": str(manifest),
                            "ADVANCE_ON_LOCK": str(int(drift == "while_waiting_for_lock")),
                        },
                    )
                    if drift == "while_waiting_for_lock":
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(marker.read_text().splitlines(), [selected_sha])
                        self.assertEqual(json.loads(manifest.read_text())["git_sha"], next_sha)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(marker.exists(), result.stdout + result.stderr)

    def test_workflow_hashes_archive_before_extract_and_preserves_old_sha_stamp(self) -> None:
        workflow = (ROOT / ".github/workflows/fhd-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("RELEASE_SHA: ${{ inputs.release_sha }}", workflow)
        self.assertLess(
            workflow.index("manifest git_sha differs from authorized release_sha"),
            workflow.index(r'tar -xzf "\$TARBALL"'),
        )
        self.assertLess(
            workflow.index(r'sha256sum -- "\$TARBALL"'), workflow.index(r'tar -xzf "\$TARBALL"')
        )
        self.assertIn("FHD_FORCE_APPLY=1 bash", workflow)
        self.assertNotIn(
            'rm -f "${DEPLOY_ROOT}/.deploy-image-digest" "${DEPLOY_ROOT}/.deploy-sha256"', workflow
        )

    def test_remote_push_rechecks_uploaded_tarball_before_channel_promotion(self) -> None:
        push = (ROOT / "FHD/scripts/deploy/fhd-push-release.sh").read_text(encoding="utf-8")
        match = re.search(r"<<'REMOTE_PROMOTE'\n(.*?)\nREMOTE_PROMOTE", push, re.S)
        self.assertIsNotNone(match, "could not extract remote promotion script")
        remote = match.group(1)
        self.assertLess(
            remote.index("uploaded artifact SHA256 differs"),
            remote.index("channel_dir.mkdir"),
        )

        with tempfile.TemporaryDirectory(prefix="fhd-remote-promote-") as td:
            root = Path(td)
            immutable = root / "immutable"
            channel = root / "channel"
            immutable.mkdir()
            channel.mkdir()
            artifact_name = "fhd-full-1.2.3-aaaaaaaaaaaa.tar.gz"
            artifact_path = immutable / artifact_name
            verifier_path = ROOT / "FHD/scripts/deploy/lib/verify_release_archive.py"
            verifier_source = verifier_path.read_bytes()
            required = runpy.run_path(str(verifier_path))["REQUIRED_RUNTIME_MEMBERS"]
            with tarfile.open(artifact_path, "w:gz") as archive:
                for name in sorted(required):
                    data = (
                        verifier_source
                        if name == "scripts/deploy/lib/verify_release_archive.py"
                        else b"fixture runtime"
                    )
                    member = tarfile.TarInfo("./" + name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            original_archive = artifact_path.read_bytes()
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            manifest = {
                "artifact": artifact_name,
                "sha256": digest,
                "git_sha": "a" * 40,
                "version": "1.2.3",
                "archive_verifier_sha256": hashlib.sha256(verifier_source).hexdigest(),
            }
            manifest_path = immutable / "fhd-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            def run_remote() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        "bash",
                        "-s",
                        "--",
                        str(immutable),
                        str(channel),
                        artifact_name,
                        "0",
                        "staging",
                        str(root / "runtime"),
                        "a" * 40,
                        digest,
                        "e30=",
                        "0",
                        base64.b64encode(verifier_source).decode(),
                    ],
                    input=remote,
                    check=False,
                    capture_output=True,
                    text=True,
                )

            artifact_path.write_bytes(b"tampered")
            rejected = run_remote()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((channel / "fhd-manifest.json").exists())
            self.assertFalse((channel / artifact_name).exists())

            artifact_path.write_bytes(original_archive)
            accepted = run_remote()
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual((channel / artifact_name).read_bytes(), original_archive)
            self.assertEqual(json.loads((channel / "fhd-manifest.json").read_text()), manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
