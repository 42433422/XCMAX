from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import runpy
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

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
                ["python3", "-c", code, str(path), release_sha, "production", "apply-latest"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(
                valid.stdout.strip(),
                "|".join(
                    (
                        release_sha,
                        manifest["artifact"],
                        manifest["sha256"],
                        manifest["archive_verifier_sha256"],
                    )
                ),
            )

            wrong_sha = subprocess.run(
                ["python3", "-c", code, str(path), "c" * 40, "production", "apply-latest"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(wrong_sha.returncode, 0)
            manifest["artifact"] = "../fhd-full-1.2.3.tar.gz"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            unsafe_path = subprocess.run(
                ["python3", "-c", code, str(path), release_sha, "production", "apply-latest"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(unsafe_path.returncode, 0)

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
