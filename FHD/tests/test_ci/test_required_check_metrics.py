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

from scripts.ci.measure_required_checks import analyze_snapshot

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
        for fault in ("check", "app", "job", "attempt", "pagination", "rule_app", "duplicate"):
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
        for fault in ("run_sha", "job_sha", "check_sha", "base", "suite", "repository", "result"):
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
            source, output = Path(directory) / "input.json", Path(directory) / "report.json"
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


if __name__ == "__main__":
    unittest.main()
