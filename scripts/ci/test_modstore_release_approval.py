import copy
import unittest

from scripts.ci.verify_modstore_release_approval import verify


class ReleaseApprovalTest(unittest.TestCase):
    def test_binding_fails_closed(self):
        sha = "a" * 40
        approval = dict(
            git_sha=sha,
            product_version="1.0.0.6",
            expected_production_sha="b" * 40,
            approval_reference="human",
            approval_scope="modstore",
            ci_run_id=1,
            security_scan_run_id=2,
        )
        runs = {
            key: dict(
                id=approval[key],
                head_sha=sha,
                path=path,
                status="completed",
                conclusion="success",
                head_branch="main",
            )
            for key, path in [
                ("ci_run_id", ".github/workflows/fhd-ci-cd.yml"),
                (
                    "security_scan_run_id",
                    ".github/workflows/fhd-security-full-scan.yml",
                ),
            ]
        }
        verify(approval, sha, "1.0.0.6", runs)
        for field, value in [
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
