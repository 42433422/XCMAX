"""Measure required checks from offline GitHub REST snapshots; never authorize a merge.

Input: repository, head_sha, event, required (required_status_checks), runs (exact
run objects), checks (check-runs page or all pages), jobs (one page collection per
run). PR snapshots also require pull_request_number and base_sha. Optional
triggered_at/trigger_kind records a caller's request_sent or event_received time;
otherwise the earliest workflow created_at is explicitly only a CI-start proxy.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result


def _rows(collection: dict | list, key: str) -> list[dict]:
    pages = collection if isinstance(collection, list) else [collection]
    rows = [row for page in pages for row in page[key]]
    totals = {page["total_count"] for page in pages}
    if len(totals) != 1 or totals != {len(rows)}:
        raise ValueError(f"Incomplete or inconsistent {key} pagination")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError(f"Duplicate {key} IDs")
    return rows


def _check_id(job: dict, repository: str) -> int:
    url = urlparse(job["check_run_url"])
    prefix = f"/repos/{repository}/check-runs/"
    if url.scheme != "https" or url.netloc != "api.github.com" or not url.path.startswith(prefix):
        raise ValueError("Foreign or invalid check_run_url")
    return int(url.path[len(prefix) :])


def _identity(run: dict, snapshot: dict) -> list[str]:
    if run["head_sha"] != snapshot["head_sha"] or run["event"] != snapshot["event"]:
        raise ValueError("Foreign head SHA or event in workflow run")
    if run["repository"]["full_name"] != snapshot["repository"]:
        raise ValueError("Foreign repository in workflow run")
    issues = []
    if snapshot["event"] == "pull_request":
        prs = [
            p
            for p in run.get("pull_requests", [])
            if p["number"] == snapshot["pull_request_number"]
        ]
        if not run.get("pull_requests"):
            issues.append(f"run {run['id']}: PR/base association unavailable")
        elif (
            len(prs) != 1
            or prs[0]["head"]["sha"] != snapshot["head_sha"]
            or prs[0]["base"]["sha"] != snapshot["base_sha"]
        ):
            raise ValueError("Foreign or missing PR/base identity")
    if type(run["run_attempt"]) is not int or run["run_attempt"] < 1:
        raise ValueError("Missing or invalid workflow attempt")
    return issues


def _analyze(snapshot: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", snapshot["head_sha"]):
        raise ValueError("A full head SHA is required")
    required = snapshot["required"]
    rules = required["checks"]
    if not rules or any(
        not r.get("context") or type(r.get("app_id")) is not int or r["app_id"] <= 0 for r in rules
    ):
        raise ValueError("Every required context needs a known positive App ID")
    keys = [(r["context"], r["app_id"]) for r in rules]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate required contexts")
    if set(required.get("contexts", [])) - {name for name, _ in keys}:
        raise ValueError("Required context has no App-bound rule")
    runs = {run["id"]: run for run in snapshot["runs"]}
    if not runs or len(runs) != len(snapshot["runs"]):
        raise ValueError("Missing or duplicate workflow runs")
    identity_issues = [issue for run in runs.values() for issue in _identity(run, snapshot)]
    checks = _rows(snapshot["checks"], "check_runs")
    jobs = [job for pages in snapshot["jobs"] for job in _rows(pages, "jobs")]
    if len({job["id"] for job in jobs}) != len(jobs):
        raise ValueError("Duplicate job IDs")
    by_check = {}
    runner_seconds = 0.0
    resource_incomplete = False
    seen_attempts: dict[int, set[int]] = {run_id: set() for run_id in runs}
    for job in jobs:
        run = runs.get(job["run_id"])
        if run is None or job["head_sha"] != snapshot["head_sha"]:
            raise ValueError("Foreign job SHA or workflow run")
        attempt = job["run_attempt"]
        if type(attempt) is not int or not 1 <= attempt <= run["run_attempt"]:
            raise ValueError("Foreign or invalid job attempt")
        seen_attempts[run["id"]].add(attempt)
        check_id = _check_id(job, snapshot["repository"])
        if check_id in by_check:
            raise ValueError("Multiple jobs claim the same check run")
        by_check[check_id] = job
        if job.get("started_at") and job.get("completed_at"):
            duration = (_time(job["completed_at"]) - _time(job["started_at"])).total_seconds()
            if duration < 0:
                raise ValueError("Negative job duration")
            runner_seconds += duration
        elif job.get("conclusion") != "skipped":
            resource_incomplete = True
    history_complete = all(
        seen_attempts[run_id] == set(range(1, run["run_attempt"] + 1))
        for run_id, run in runs.items()
    )
    start = min(_time(run["created_at"]) for run in runs.values())
    start_kind = "workflow_created_proxy"
    if snapshot.get("triggered_at"):
        start_kind = snapshot.get("trigger_kind")
        if start_kind not in {"request_sent", "event_received"}:
            raise ValueError("Explicit trigger time needs request_sent or event_received kind")
        trigger = _time(snapshot["triggered_at"])
        if trigger > start:
            raise ValueError("Trigger time is after workflow creation")
        start = trigger
    results, issues, ignored_old_attempts = [], [], []
    for context, app_id in keys:
        matches = []
        for check in checks:
            if check["name"] != context or check.get("app", {}).get("id") != app_id:
                continue
            if check["head_sha"] != snapshot["head_sha"]:
                raise ValueError(f"Foreign check SHA: {context}")
            job = by_check.get(check["id"])
            if job is None:
                issues.append(f"{context}: missing job/attempt evidence")
                continue
            run = runs[job["run_id"]]
            if job["run_attempt"] != run["run_attempt"]:
                ignored_old_attempts.append(check["id"])
                continue
            if job["name"] != context or any(
                job.get(field) != check.get(field) for field in ("status", "conclusion")
            ):
                raise ValueError(f"Inconsistent check/job snapshot: {context}")
            if check["check_suite"]["id"] != run["check_suite_id"]:
                raise ValueError(f"Foreign check suite: {context}")
            matches.append((check, job))
        row = {"context": context, "app_id": app_id}
        if len(matches) != 1:
            issues.append(f"{context}: expected one current check, found {len(matches)}")
            row["status"] = "missing" if not matches else "ambiguous"
        else:
            check, job = matches[0]
            row.update(
                check_run_id=check["id"],
                run_id=job["run_id"],
                run_attempt=job["run_attempt"],
                status=check["status"],
                conclusion=check.get("conclusion"),
                completed_at=check.get("completed_at"),
                skipped_steps=sum(s.get("conclusion") == "skipped" for s in job.get("steps") or []),
            )
            if check["status"] == "completed":
                if not all(
                    (check.get("completed_at"), check.get("conclusion"), job.get("completed_at"))
                ):
                    issues.append(f"{context}: incomplete terminal check")
                else:
                    finished = max(_time(check["completed_at"]), _time(job["completed_at"]))
                    if min(_time(check["completed_at"]), _time(job["completed_at"])) < start:
                        raise ValueError(f"Check completed before trigger: {context}")
                    row["completed_at"] = finished.isoformat()
        results.append(row)
    observed_complete = not issues and all(r["status"] == "completed" for r in results)
    terminal = observed_complete and not identity_issues
    success = terminal and all(r["conclusion"] == "success" for r in results)
    end = max(_time(r["completed_at"]) for r in results) if observed_complete else None
    duration = (end - start).total_seconds() if end else None
    return {
        "schema": 1,
        "scope": "github_required_checks_observation",
        "merge_authorized": False,
        "test_source_sha_verified": False,
        "repository": snapshot["repository"],
        "head_sha": snapshot["head_sha"],
        "base_sha": snapshot.get("base_sha"),
        "cache_state": snapshot.get("cache_state", "unknown"),
        "observed_at": snapshot.get("observed_at"),
        "status": "success" if success else "not_successful" if terminal else "incomplete",
        "measurement_complete": terminal,
        "observed_checks_complete": observed_complete,
        "required_count": len(keys),
        "started_at": start.isoformat(),
        "start_kind": start_kind,
        "completed_at": end.isoformat() if end else None,
        "completion_seconds": duration if terminal else None,
        "observed_completion_seconds": duration,
        "success_seconds": duration if success else None,
        "completed_runner_minutes_observed": round(runner_seconds / 60, 3),
        "runner_cost_scope": "all_supplied_jobs_in_selected_workflows",
        "runner_cost_complete": history_complete and not resource_incomplete,
        "ignored_old_attempt_check_ids": ignored_old_attempts,
        "checks": results,
        "issues": identity_issues + issues,
    }


def analyze_snapshot(snapshot: dict) -> dict:
    """Invalid or incomplete evidence never yields a successful latency sample."""
    try:
        return _analyze(snapshot)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return {
            "schema": 1,
            "status": "invalid",
            "measurement_complete": False,
            "issues": [str(exc)],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Offline snapshot JSON; no API calls are made")
    parser.add_argument("--output", type=Path, help="Default: write JSON to stdout")
    args = parser.parse_args()
    report = analyze_snapshot(json.loads(args.input.read_text(encoding="utf-8")))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
