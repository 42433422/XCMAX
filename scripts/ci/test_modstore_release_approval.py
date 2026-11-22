import copy
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

from scripts.ci.verify_modstore_release_approval import (
    _archive,
    read_source_evidence,
    verify,
    verify_running_release,
)


class ReleaseApprovalTest(unittest.TestCase):
    def setUp(self):
        sha = "a" * 40
        approval = {
            "git_sha": sha,
            "product_version": "1.0.0.6",
            "expected_production_sha": "b" * 40,
            "approval_reference": "human",
            "approval_scope": "modstore",
            "ci_run_id": 1,
            "security_scan_run_id": 2,
        }
        runs = {
            key: {
                "id": approval[key],
                "head_sha": sha,
                "path": path,
                "status": "completed",
                "conclusion": "success",
                "head_branch": "main",
                "event": "push" if key == "ci_run_id" else "workflow_dispatch",
                "display_title": (
                    f"CI/CD {sha}"
                    if key == "ci_run_id"
                    else "Security full release scan"
                ),
            }
            for key, path in [
                ("ci_run_id", ".github/workflows/fhd-ci-cd.yml"),
                (
                    "security_scan_run_id",
                    ".github/workflows/fhd-security-full-scan.yml",
                ),
            ]
        }
        self.sha, self.approval, self.runs = sha, approval, runs

    def test_binding_fails_closed(self):
        sha, approval, runs = self.sha, self.approval, self.runs
        verify(approval, sha, "1.0.0.6", runs)
        for field, value in [
            ("id", 99),
            ("head_sha", "c" * 40),
            ("conclusion", "failure"),
            ("status", "in_progress"),
            ("path", "other.yml"),
            ("head_branch", "feature"),
        ]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                changed = copy.deepcopy(runs)
                changed["ci_run_id"][field] = value
                verify(approval, sha, "1.0.0.6", changed)
        for target, version in [
            (sha[:8], "1.0.0.6"),
            ("c" * 40, "1.0.0.6"),
            (sha, "1.0.0.1"),
        ]:
            with self.assertRaises(ValueError):
                verify(approval, target, version, runs)

    def test_ci_events_bind_the_actual_checkout_source(self):
        for event, title in [
            ("push", f"CI/CD {self.sha}"),
            ("push", "Legacy push commit message"),
            ("schedule", "Nightly full CI"),
            ("workflow_dispatch", f"CI/CD {self.sha}"),
            (
                "workflow_dispatch",
                f"CI/CD {self.sha} [delivery:749f8800-080f-5f7a-8c94-1c51db98f8b4]",
            ),
        ]:
            with self.subTest(event=event, title=title):
                runs = copy.deepcopy(self.runs)
                runs["ci_run_id"].update(event=event, display_title=title)
                verify(self.approval, self.sha, "1.0.0.6", runs)

    def test_newer_controller_reads_exact_native_source_before_approval(self):
        controller = "c" * 40
        run = {
            **self.runs["ci_run_id"],
            "head_sha": controller,
            "run_attempt": 2,
            "event": "workflow_dispatch",
            "run_started_at": "2026-11-22T00:00:00Z",
            "updated_at": "2026-11-22T00:10:00Z",
        }
        report = {
            "source_sha": self.sha,
            "test_sha": self.sha,
            "run_id": "1",
            "run_attempt": "2",
            "execution_environment": "github-actions",
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            bundle.writestr("business-contract-evidence.json", json.dumps(report))
        raw = stream.getvalue()
        artifact = {
            "id": 91,
            "name": "backend-combined-2",
            "expired": False,
            "workflow_run": {"id": 1, "head_sha": controller},
            "size_in_bytes": len(raw),
            "created_at": "2026-11-22T00:05:00Z",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }

        def api(path):
            return (
                {"artifacts": [artifact], "total_count": 1}
                if "/artifacts?" in path
                else run
            )

        with patch("subprocess.check_output", return_value=raw):
            proof = read_source_evidence(
                "owner/repo",
                "ci_run_id",
                run,
                self.sha,
                api=api,
                read_archive=lambda a: _archive("owner/repo", a),
            )
        runs = {**self.runs, "ci_run_id": run}
        contains = lambda a, b: (a, b) in {(self.sha, controller), (controller, "main")}
        verify(
            self.approval,
            self.sha,
            "1.0.0.6",
            runs,
            source_evidence={"ci_run_id": proof},
            contains=contains,
        )
        for bad_proof, bad_ancestor in (
            (None, contains),
            (proof, lambda *_: False),
            ({**proof, "run_attempt": 1}, contains),
            ({**proof, "source_sha": controller}, contains),
        ):
            with self.assertRaises(ValueError):
                verify(
                    self.approval,
                    self.sha,
                    "1.0.0.6",
                    runs,
                    source_evidence={"ci_run_id": bad_proof},
                    contains=bad_ancestor,
                )
        artifact["digest"] = "sha256:" + "0" * 64
        with patch("subprocess.check_output", return_value=raw), self.assertRaises(
            ValueError
        ):
            read_source_evidence(
                "owner/repo",
                "ci_run_id",
                run,
                self.sha,
                api=api,
                read_archive=lambda a: _archive("owner/repo", a),
            )

    def test_same_metadata_cannot_attest_different_manual_source(self):
        for event, title in [
            ("workflow_dispatch", "CI/CD " + "b" * 40),
            ("workflow_dispatch", f"CI/CD {self.sha} candidate"),
            ("workflow_dispatch", "CI/CD main"),
            ("workflow_dispatch", None),
            ("pull_request", f"CI/CD {self.sha}"),
            ("workflow_run", f"CI/CD {self.sha}"),
            (None, f"CI/CD {self.sha}"),
        ]:
            with self.subTest(event=event, title=title), self.assertRaises(ValueError):
                runs = copy.deepcopy(self.runs)
                # GitHub's dispatch head_sha identifies the main controller even
                # when release_sha makes every CI job check out an older commit.
                runs["ci_run_id"].update(event=event, display_title=title)
                verify(self.approval, self.sha, "1.0.0.6", runs)

    def test_release_acceptance_requires_signature_and_exact_independent_runtime(self):
        sha = self.sha
        version = self.approval["product_version"]
        digest = "d" * 64
        release_id = f"xcagi-{version}-{sha}"
        controller = "e" * 40
        admission = {
            **self.approval,
            "merge_sha": sha,
            "controller_sha": controller,
            "workflow_run_id": "482",
            "signed_run_attempt": "1",
            "environment": "production",
            "artifact_sha256": digest,
            "signature_verified": True,
            "signature_verifier": "github-artifact-attestations",
            "attestation_id": "991",
        }
        health = {
            "ok": True,
            "deploy_tier": "production",
            "git_sha": sha,
            "artifact_sha256": digest,
            "release_id": release_id,
        }

        def finalize(proof, runtime):
            return verify_running_release(
                proof,
                runtime,
                digest,
                controller_sha=controller,
                workflow_run_id="482",
                signed_attempt="1",
                workflow_attempt="2",
            )

        receipt = finalize(admission, health)
        self.assertEqual(receipt["release_id"], release_id)
        self.assertEqual(receipt["workflow_run_attempt"], "2")
        self.assertEqual(receipt["runtime_git_sha"], sha)
        self.assertEqual(receipt["runtime_artifact_sha256"], digest)
        self.assertEqual(receipt["runtime_release_id"], release_id)
        for field, value in (
            ("signature_verified", "true"),
            ("signature_verifier", "checksum_only"),
            ("attestation_id", ""),
            ("workflow_run_id", "483"),
            ("signed_run_attempt", "2"),
            ("controller_sha", sha),
            ("product_version", "1.0.0.7"),
            ("artifact_sha256", "a" * 64),
            ("merge_sha", "b" * 40),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                finalize({**admission, field: value}, health)
        for field, value in (
            ("ok", False),
            ("git_sha", "b" * 40),
            ("artifact_sha256", "f" * 64),
            ("release_id", f"xcagi-1.0.0.7-{sha}"),
            ("deploy_tier", "staging"),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                finalize(admission, {**health, field: value})
