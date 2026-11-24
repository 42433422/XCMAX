"""A quick old green result must never become a complete required-check sample."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.ci.measure_required_checks import analyze_snapshot, collect_release_checks

CONTEXTS = [
    "guard-temp-scripts",
    "arch-fitness",
    "security-scan",
    "gitleaks",
    "analyze (python)",
    "analyze (javascript-typescript)",
    "SSOT Drift Gate",
    "Release gate (hard block)",
    "backend-test",
    "frontend-test",
    "mutation-smoke",
]


def timestamp(seconds: int) -> str:
    return (datetime(2026, 10, 22, tzinfo=UTC) + timedelta(seconds=seconds)).isoformat()


def snapshot() -> dict:
    runs = [
        {
            "id": n,
            "head_sha": "a" * 40,
            "event": "pull_request",
            "run_attempt": 1,
            "created_at": timestamp(0),
            "check_suite_id": 100 + n,
            "repository": {"full_name": "owner/repo"},
            "pull_requests": [{"number": 7, "head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}}],
        }
        for n in range(1, 6)
    ]
    checks, jobs = [], [[] for _ in runs]
    for i, context in enumerate(CONTEXTS):
        check = {
            "id": 1000 + i,
            "name": context,
            "head_sha": "a" * 40,
            "app": {"id": 123},
            "check_suite": {"id": 101 + i % 5},
            "status": "completed",
            "conclusion": "success",
            "completed_at": timestamp(60 + 10 * i),
        }
        checks.append(check)
        jobs[i % 5].append(
            {
                **check,
                "run_id": 1 + i % 5,
                "run_attempt": 1,
                "started_at": timestamp(10),
                "check_run_url": f"https://api.github.com/repos/owner/repo/check-runs/{check['id']}",
                "steps": [{"conclusion": "skipped"}],
            }
        )
    return {
        "repository": "owner/repo",
        "head_sha": "a" * 40,
        "base_sha": "b" * 40,
        "pull_request_number": 7,
        "event": "pull_request",
        "required": {
            "contexts": CONTEXTS,
            "checks": [{"context": c, "app_id": 123} for c in CONTEXTS],
        },
        "runs": runs,
        "checks": {"total_count": len(checks), "check_runs": checks},
        "jobs": [{"total_count": len(group), "jobs": group} for group in jobs],
    }


class RequiredCheckMetricsTests(unittest.TestCase):
    def test_all_required_checks_determine_finish_not_backend_alone(self):
        report = analyze_snapshot(snapshot())
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["success_seconds"], 160)
        self.assertEqual(report["start_kind"], "workflow_created_proxy")
        self.assertEqual(report["required_count"], 11)
        self.assertTrue(report["runner_cost_complete"])
        self.assertFalse(report["merge_authorized"])
        self.assertFalse(report["test_source_sha_verified"])
        self.assertEqual(report["checks"][0]["skipped_steps"], 1)

    def test_explicit_trigger_includes_dispatch_delay(self):
        data = snapshot()
        data.update(triggered_at=timestamp(-20), trigger_kind="request_sent")
        self.assertEqual(analyze_snapshot(data)["success_seconds"], 180)
        data["triggered_at"] = timestamp(5)
        self.assertEqual(analyze_snapshot(data)["status"], "invalid")

    def test_unassigned_skipped_api_job_has_zero_runner_cost(self):
        data = snapshot()
        baseline = analyze_snapshot(data)["completed_runner_minutes_observed"]
        # PR #2506 migration-progress-badge: GitHub returned start 18:24:19Z,
        # completion 18:24:18Z, no steps and null runner metadata.
        skipped = {
            **data["jobs"][0]["jobs"][0],
            "id": 2000,
            "name": "migration-progress-badge",
            "check_run_url": "https://api.github.com/repos/owner/repo/check-runs/2000",
            "conclusion": "skipped",
            "created_at": timestamp(1),
            "started_at": timestamp(1),
            "completed_at": timestamp(0),
            "steps": [],
            "runner_id": None,
            "runner_name": None,
        }
        data["jobs"][0]["jobs"].append(skipped)
        data["jobs"][0]["total_count"] += 1
        for runner_id, runner_name in ((None, None), (0, "")):
            with self.subTest(runner_id=runner_id, runner_name=runner_name):
                skipped.update(runner_id=runner_id, runner_name=runner_name)
                report = analyze_snapshot(data)
                self.assertEqual(report["status"], "success")
                self.assertTrue(report["runner_cost_complete"])
                self.assertEqual(report["completed_runner_minutes_observed"], baseline)
        for changes in (
            {"runner_id": 123},
            {"runner_name": "allocated-runner"},
            {"steps": [{"name": "Set up job", "conclusion": "success"}]},
            {"status": "in_progress"},
            {"conclusion": "success"},
        ):
            with self.subTest(changes=changes):
                data["jobs"][0]["jobs"][-1] = {**skipped, **changes}
                self.assertEqual(analyze_snapshot(data)["status"], "invalid")
        for missing in ("runner_id", "runner_name"):
            with self.subTest(missing=missing):
                partial = {**skipped}
                del partial[missing]
                data["jobs"][0]["jobs"][-1] = partial
                self.assertEqual(analyze_snapshot(data)["status"], "invalid")
        del skipped["runner_id"], skipped["runner_name"]
        data["jobs"][0]["jobs"][-1] = skipped
        self.assertEqual(analyze_snapshot(data)["status"], "invalid")
        skipped.update(started_at=None, completed_at=None)
        self.assertFalse(analyze_snapshot(data)["runner_cost_complete"])

    def test_unassigned_skipped_required_job_is_still_unsuccessful(self):
        data = snapshot()
        check, job = data["checks"]["check_runs"][0], data["jobs"][0]["jobs"][0]
        check.update(conclusion="skipped", completed_at=timestamp(0))
        job.update(
            conclusion="skipped",
            started_at=timestamp(1),
            completed_at=timestamp(0),
            steps=[],
            runner_id=None,
            runner_name=None,
        )
        report = analyze_snapshot(data)
        self.assertEqual(report["status"], "not_successful")
        self.assertTrue(report["measurement_complete"])
        self.assertIsNone(report["success_seconds"])

    def test_merged_pr_without_run_association_is_observation_only(self):
        data = snapshot()
        for run in data["runs"]:
            run["pull_requests"] = []
        report = analyze_snapshot(data)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["observed_checks_complete"])
        self.assertFalse(report["measurement_complete"])
        self.assertEqual(report["observed_completion_seconds"], 160)
        self.assertIsNone(report["success_seconds"])
        self.assertIsNone(report["completion_seconds"])

    def test_failed_cancelled_neutral_or_skipped_are_not_success_latency(self):
        for conclusion in ("failure", "cancelled", "neutral", "skipped"):
            with self.subTest(conclusion=conclusion):
                data = snapshot()
                data["checks"]["check_runs"][0]["conclusion"] = conclusion
                data["jobs"][0]["jobs"][0]["conclusion"] = conclusion
                report = analyze_snapshot(data)
                self.assertEqual(report["status"], "not_successful")
                self.assertTrue(report["measurement_complete"])
                self.assertIsNone(report["success_seconds"])
                self.assertGreater(report["completed_runner_minutes_observed"], 0)

    def test_old_green_cannot_hide_current_failure(self):
        data = snapshot()
        old = copy.deepcopy(data["checks"]["check_runs"][0])
        old_job = copy.deepcopy(data["jobs"][0]["jobs"][0])
        old["id"] = old_job["id"] = 2000
        old_job["check_run_url"] = "https://api.github.com/repos/owner/repo/check-runs/2000"
        data["runs"][0]["run_attempt"] = 2
        for job in data["jobs"][0]["jobs"]:
            job["run_attempt"] = 2
        data["checks"]["check_runs"][0]["conclusion"] = "failure"
        data["jobs"][0]["jobs"][0]["conclusion"] = "failure"
        data["checks"]["check_runs"].append(old)
        data["checks"]["total_count"] += 1
        data["jobs"][0]["jobs"].append(old_job)
        data["jobs"][0]["total_count"] += 1
        report = analyze_snapshot(data)
        self.assertEqual(report["status"], "not_successful")
        self.assertEqual(report["ignored_old_attempt_check_ids"], [2000])

    def test_missing_unknown_or_old_evidence_cannot_pass(self):
        for fault in (
            "check",
            "app",
            "job",
            "attempt",
            "pagination",
            "rule_app",
            "duplicate",
        ):
            with self.subTest(fault=fault):
                data = snapshot()
                if fault == "check":
                    data["checks"]["check_runs"].pop()
                    data["checks"]["total_count"] -= 1
                elif fault == "app":
                    data["checks"]["check_runs"][0]["app"]["id"] = 456
                elif fault == "job":
                    data["jobs"].pop()
                elif fault == "attempt":
                    data["runs"][0]["run_attempt"] = 2
                elif fault == "pagination":
                    data["checks"]["total_count"] += 1
                elif fault == "rule_app":
                    data["required"]["checks"][0]["app_id"] = None
                else:
                    duplicate = copy.deepcopy(data["checks"]["check_runs"][0])
                    duplicate["id"] = 2000
                    job = copy.deepcopy(data["jobs"][0]["jobs"][0])
                    job.update(
                        id=2000,
                        check_run_url="https://api.github.com/repos/owner/repo/check-runs/2000",
                    )
                    data["checks"]["check_runs"].append(duplicate)
                    data["checks"]["total_count"] += 1
                    data["jobs"][0]["jobs"].append(job)
                    data["jobs"][0]["total_count"] += 1
                self.assertNotEqual(analyze_snapshot(data)["status"], "success")

    def test_foreign_identity_and_inconsistent_snapshot_are_invalid(self):
        for fault in (
            "run_sha",
            "job_sha",
            "check_sha",
            "base",
            "suite",
            "repository",
            "result",
        ):
            with self.subTest(fault=fault):
                data = snapshot()
                if fault == "run_sha":
                    data["runs"][0]["head_sha"] = "c" * 40
                elif fault == "job_sha":
                    data["jobs"][0]["jobs"][0]["head_sha"] = "c" * 40
                elif fault == "check_sha":
                    data["checks"]["check_runs"][0]["head_sha"] = "c" * 40
                elif fault == "base":
                    data["runs"][0]["pull_requests"][0]["base"]["sha"] = "c" * 40
                elif fault == "suite":
                    data["checks"]["check_runs"][0]["check_suite"]["id"] = 999
                elif fault == "repository":
                    data["jobs"][0]["jobs"][0]["check_run_url"] = (
                        "https://api.github.com/repos/other/repo/check-runs/1000"
                    )
                else:
                    data["checks"]["check_runs"][0]["conclusion"] = "failure"
                self.assertEqual(analyze_snapshot(data)["status"], "invalid")

    def test_pending_and_absent_prior_attempt_costs_stay_incomplete(self):
        data = snapshot()
        for record in (data["checks"]["check_runs"][0], data["jobs"][0]["jobs"][0]):
            record.update(status="in_progress", conclusion=None, completed_at=None)
        report = analyze_snapshot(data)
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["runner_cost_complete"])
        data = snapshot()
        data["runs"][0]["run_attempt"] = 2
        for job in data["jobs"][0]["jobs"]:
            job["run_attempt"] = 2
        report = analyze_snapshot(data)
        self.assertEqual(report["status"], "success")
        self.assertFalse(report["runner_cost_complete"])

    def test_cli_writes_report_and_returns_nonzero_for_missing_check(self):
        script = Path(__file__).resolve().parents[2] / "scripts/ci/measure_required_checks.py"
        with tempfile.TemporaryDirectory() as directory:
            source, output = (
                Path(directory) / "input.json",
                Path(directory) / "report.json",
            )
            data = snapshot()
            data["checks"]["check_runs"].pop()
            data["checks"]["total_count"] -= 1
            source.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(script), str(source), "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(output.read_text())["status"], "incomplete")


class ReleaseChecksTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot()
        self.calls = []
        for run in self.data["runs"]:
            run.update(
                head_branch="main",
                head_repository={"full_name": "owner/repo"},
                event="push" if run["id"] % 2 else "workflow_dispatch",
                workflow_id=run["id"],
                path=f".github/workflows/test-{run['id']}.yml",
                status="completed",
                conclusion="success",
                updated_at=timestamp(180),
            )

    def api(self, path, **options):
        self.calls.append(path)
        if path.endswith("/git/ref/heads/main"):
            return {"ref": "refs/heads/main", "object": {"sha": "a" * 40}}
        if path.endswith("/required_status_checks"):
            self.assertEqual(options, {"protection": True})
            return copy.deepcopy(self.data["required"])
        if "/check-runs?" in path:
            self.assertTrue(options["paginate"])
            return copy.deepcopy([self.data["checks"]])
        if "/actions/runs?" in path:
            event = path.split("event=")[1].split("&")[0]
            runs = [row for row in self.data["runs"] if row["event"] == event]
            return copy.deepcopy(
                [
                    {
                        "total_count": len(runs),
                        "workflow_runs": runs,
                    }
                ]
            )
        if "/jobs?" in path:
            self.assertIn("filter=latest", path)
            run_id = int(path.split("/runs/")[1].split("/")[0])
            rows = [
                job for page in self.data["jobs"] for job in page["jobs"] if job["run_id"] == run_id
            ]
            return copy.deepcopy([{"total_count": len(rows), "jobs": rows}])
        if "/actions/runs/" in path:
            return copy.deepcopy(
                next(row for row in self.data["runs"] if row["id"] == int(path.rsplit("/", 1)[1]))
            )
        self.fail(f"Unexpected API route (commit statuses must never be read): {path}")

    def test_original_events_and_app_bound_checks_are_reused(self):
        report = collect_release_checks("owner/repo", "a" * 40, api=self.api)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["events"], ["push", "workflow_dispatch"])
        self.assertEqual({row["context"] for row in report["checks"]}, set(CONTEXTS))
        self.assertFalse(report["test_source_sha_verified"])
        self.assertFalse(any("/statuses" in path for path in self.calls))

    def test_failed_or_pending_workflow_cannot_use_older_green(self):
        for status, conclusion in (("queued", None), ("completed", "failure")):
            with self.subTest(status=status):
                old = self.data["runs"][0]
                newer = {
                    **old,
                    "id": 100,
                    "check_suite_id": 300,
                    "created_at": timestamp(200),
                    "status": status,
                    "conclusion": conclusion,
                }
                self.data["runs"].append(newer)
                with self.assertRaisesRegex(ValueError, "current attempt is not successful"):
                    collect_release_checks("owner/repo", "a" * 40, api=self.api)
                self.data["runs"].pop()

    def test_new_attempt_requires_its_own_jobs(self):
        self.data["runs"][0]["run_attempt"] = 2
        report = collect_release_checks("owner/repo", "a" * 40, api=self.api)
        self.assertNotEqual(report["status"], "success")
        self.assertTrue(any("expected one current check" in issue for issue in report["issues"]))
        for job in self.data["jobs"][0]["jobs"]:
            job["run_attempt"] = 2
        verified = collect_release_checks("owner/repo", "a" * 40, api=self.api)
        self.assertEqual(verified["status"], "success")
        self.assertEqual(verified["checks"][0]["run_attempt"], 2)

    def test_wrong_app_foreign_run_and_truncated_check_pages_fail_closed(self):
        original = copy.deepcopy(self.data)
        for fault in ("app", "head_repository", "event", "pagination", "no_app_rule"):
            with self.subTest(fault=fault):
                self.data = copy.deepcopy(original)
                if fault == "app":
                    self.data["checks"]["check_runs"][0]["app"]["id"] = 999
                elif fault == "head_repository":
                    self.data["runs"][0]["head_repository"]["full_name"] = "fork/repo"
                elif fault == "event":
                    self.data["runs"][0]["event"] = "pull_request"
                elif fault == "pagination":
                    self.data["checks"]["total_count"] += 1
                else:
                    self.data["required"]["checks"][0]["app_id"] = None
                with self.assertRaises(ValueError):
                    collect_release_checks("owner/repo", "a" * 40, api=self.api)

    def test_same_context_from_two_workflows_is_ambiguous(self):
        check = copy.deepcopy(self.data["checks"]["check_runs"][0])
        check.update(id=2000, check_suite={"id": 102})
        self.data["checks"]["check_runs"].append(check)
        self.data["checks"]["total_count"] += 1
        with self.assertRaisesRegex(ValueError, "ambiguous main workflow"):
            collect_release_checks("owner/repo", "a" * 40, api=self.api)

    def test_current_failed_check_is_not_replaced_by_status_success(self):
        self.data["checks"]["check_runs"][0]["conclusion"] = "failure"
        self.data["jobs"][0]["jobs"][0]["conclusion"] = "failure"
        self.assertNotEqual(
            collect_release_checks("owner/repo", "a" * 40, api=self.api)["status"],
            "success",
        )

    def test_new_run_started_during_readback_invalidates_snapshot(self):
        calls = 0

        def changing_api(path, **options):
            nonlocal calls
            if "/actions/runs?" in path and "event=push&" in path:
                calls += 1
                if calls == 2:
                    old = self.data["runs"][0]
                    self.data["runs"].append(
                        {
                            **old,
                            "id": 100,
                            "check_suite_id": 300,
                            "created_at": timestamp(200),
                            "status": "queued",
                            "conclusion": None,
                        }
                    )
            return self.api(path, **options)

        with self.assertRaisesRegex(ValueError, "changed during readback"):
            collect_release_checks("owner/repo", "a" * 40, api=changing_api)

    def test_frozen_main_ancestor_needs_exact_authorization_and_all_checks(self):
        def frozen_api(path, **options):
            if path.endswith("/git/ref/heads/main"):
                return {"ref": "refs/heads/main", "object": {"sha": "b" * 40}}
            if "/compare/" in path:
                self.assertTrue(path.endswith(f"{'a' * 40}...{'b' * 40}"))
                return {"status": "ahead", "merge_base_commit": {"sha": "a" * 40}}
            return self.api(path, **options)

        with self.assertRaisesRegex(ValueError, "not current main"):
            collect_release_checks("owner/repo", "a" * 40, api=frozen_api)
        with self.assertRaisesRegex(ValueError, "authorization does not match"):
            collect_release_checks(
                "owner/repo", "a" * 40, authorized_frozen_sha="c" * 40, api=frozen_api
            )
        report = collect_release_checks(
            "owner/repo", "a" * 40, authorized_frozen_sha="a" * 40, api=frozen_api
        )
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["source_policy"], "authorized_frozen_main")
        self.assertEqual(report["main_sha"], "b" * 40)
        self.data["checks"]["check_runs"][0]["app"]["id"] = 999
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            collect_release_checks(
                "owner/repo", "a" * 40, authorized_frozen_sha="a" * 40, api=frozen_api
            )

    def test_frozen_authorization_does_not_admit_nonmain_or_moving_main(self):
        for fault in ("diverged", "wrong_ancestor", "main_changed"):
            with self.subTest(fault=fault):
                reads = 0

                def frozen_api(path, **options):
                    nonlocal reads
                    if path.endswith("/git/ref/heads/main"):
                        reads += 1
                        sha = "c" * 40 if fault == "main_changed" and reads > 1 else "b" * 40
                        return {"ref": "refs/heads/main", "object": {"sha": sha}}
                    if "/compare/" in path:
                        return {
                            "status": "diverged" if fault == "diverged" else "ahead",
                            "merge_base_commit": {
                                "sha": "c" * 40 if fault == "wrong_ancestor" else "a" * 40
                            },
                        }
                    return self.api(path, **options)

                with self.assertRaises(ValueError):
                    collect_release_checks(
                        "owner/repo", "a" * 40, authorized_frozen_sha="a" * 40, api=frozen_api
                    )


if __name__ == "__main__":
    unittest.main()
