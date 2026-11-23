"""Observe protected checks from GitHub REST evidence; never authorize a merge.

Input: repository, head_sha, event, required (required_status_checks), runs (exact
run objects), checks (check-runs page or all pages), jobs (one page collection per
run). PR snapshots also require pull_request_number and base_sha. Optional
triggered_at/trigger_kind records a caller's request_sent or event_received time;
otherwise the earliest workflow created_at is explicitly only a CI-start proxy.
The live release entry point collects original main workflow attempts and reuses
the same App-bound checker; it does not certify the tested source or deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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


def _required_keys(required: dict) -> list[tuple[str, int]]:
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
    return keys


def _analyze(snapshot: dict) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", snapshot["head_sha"]):
        raise ValueError("A full head SHA is required")
    keys = _required_keys(snapshot["required"])
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
        # GitHub may timestamp an unassigned skipped job's start after its end.
        # Require explicit runner metadata; missing evidence is not zero cost.
        if (
            job.get("status") == "completed"
            and job.get("conclusion") == "skipped"
            and job.get("steps") == []
            and "runner_id" in job
            and "runner_name" in job
            and job.get("runner_id") in (None, 0)
            and not job.get("runner_name")
        ):
            continue
        if job.get("started_at") and job.get("completed_at"):
            duration = (_time(job["completed_at"]) - _time(job["started_at"])).total_seconds()
            if duration < 0:
                raise ValueError("Negative job duration")
            runner_seconds += duration
        else:
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
                    (
                        check.get("completed_at"),
                        check.get("conclusion"),
                        job.get("completed_at"),
                    )
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
        "status": ("success" if success else "not_successful" if terminal else "incomplete"),
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


def _github(path: str, *, paginate: bool = False, protection: bool = False):
    env = dict(os.environ)
    if protection:
        env["GH_TOKEN"] = env["RELEASE_PROTECTION_TOKEN"]
        if not env["GH_TOKEN"]:
            raise ValueError("RELEASE_PROTECTION_TOKEN is required for App-bound rules")
    command = ["gh", "api", path]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    return json.loads(subprocess.check_output(command, env=env, timeout=60))


def collect_release_checks(
    repository: str, sha: str, *, authorized_frozen_sha: str | None = None, api=_github
) -> dict:
    """Reuse the offline checker with original events and latest workflow attempts.

    Commit statuses cannot replace App-bound checks. Paginated API collections
    are validated before partitioning by event; no synthetic event is assigned
    to a workflow. A frozen main ancestor still needs every check and the exact
    authorization supplied by the protected publication workflow. This argument
    is not itself approval. Source checkout proof remains a separate release gate.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch(
        r"[0-9a-f]{40}", sha
    ):
        raise ValueError("Repository and full release SHA are required")
    prefix = f"repos/{repository}"
    ref_route = f"{prefix}/git/ref/heads/main"
    rules_route = f"{prefix}/branches/main/protection/required_status_checks"
    main = api(ref_route)
    main_sha = main.get("object", {}).get("sha")
    if main.get("ref") != "refs/heads/main" or not re.fullmatch(r"[0-9a-f]{40}", main_sha or ""):
        raise ValueError("Invalid main reference")
    if authorized_frozen_sha is not None and authorized_frozen_sha != sha:
        raise ValueError("Frozen publication authorization does not match the release SHA")
    if main_sha != sha and authorized_frozen_sha is None:
        raise ValueError("Release SHA is not current main")
    if main_sha != sha:
        comparison = api(f"{prefix}/compare/{sha}...{main_sha}")
        if (
            comparison.get("status") != "ahead"
            or comparison.get("merge_base_commit", {}).get("sha") != sha
        ):
            raise ValueError("Authorized frozen release is not an ancestor of main")
    required = api(rules_route, protection=True)
    keys = _required_keys(required)
    checks = _rows(
        api(f"{prefix}/commits/{sha}/check-runs?filter=all&per_page=100", paginate=True),
        "check_runs",
    )
    events = ("push", "workflow_dispatch", "schedule")

    def main_runs():
        return [
            run
            for event in events
            for run in _rows(
                api(
                    f"{prefix}/actions/runs?head_sha={sha}&branch=main&event={event}&per_page=100",
                    paginate=True,
                ),
                "workflow_runs",
            )
        ]

    runs = main_runs()
    eligible = [
        run
        for run in runs
        if run.get("head_sha") == sha
        and run.get("head_branch") == "main"
        and run.get("event") in events
        and run.get("repository", {}).get("full_name") == repository
        and run.get("head_repository", {}).get("full_name") == repository
    ]
    by_suite = {run["check_suite_id"]: run for run in eligible}
    if len(by_suite) != len(eligible):
        raise ValueError("Ambiguous workflow check suites")
    owners = {}
    for key in keys:
        workflows = {
            by_suite[check["check_suite"]["id"]]["workflow_id"]
            for check in checks
            if (check.get("name"), check.get("app", {}).get("id")) == key
            and check.get("check_suite", {}).get("id") in by_suite
        }
        if len(workflows) != 1:
            raise ValueError(f"{key[0]}: missing or ambiguous main workflow identity")
        owners[key] = workflows.pop()
    identity_fields = (
        "id",
        "run_attempt",
        "head_sha",
        "head_branch",
        "event",
        "workflow_id",
        "path",
        "check_suite_id",
        "status",
        "conclusion",
        "created_at",
        "updated_at",
    )

    def same_run(left, right):
        return all(left.get(key) == right.get(key) for key in identity_fields) and all(
            left.get(key, {}).get("full_name") == right.get(key, {}).get("full_name")
            for key in ("repository", "head_repository")
        )

    selected = {}
    jobs = {}
    for workflow_id in set(owners.values()):
        candidates = [run for run in eligible if run["workflow_id"] == workflow_id]
        run = max(candidates, key=lambda row: (_time(row["created_at"]), row["id"]))
        if (
            type(workflow_id) is not int
            or workflow_id <= 0
            or not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", str(run.get("path") or ""))
        ):
            raise ValueError("Invalid required workflow identity")
        route = f"{prefix}/actions/runs/{run['id']}"
        # Read the full current object before reading its jobs. A new attempt,
        # pending rerun or failed workflow cannot be replaced by an older green.
        if not same_run(api(route), run):
            raise ValueError("Workflow changed before evidence collection")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise ValueError(f"Workflow {run['id']}: current attempt is not successful")
        selected[workflow_id] = run
        pages = api(f"{route}/jobs?filter=latest&per_page=100", paginate=True)
        _rows(pages, "jobs")
        jobs[workflow_id] = pages
    reports = []
    for event in sorted({run["event"] for run in selected.values()}):
        group = {wid: run for wid, run in selected.items() if run["event"] == event}
        group_keys = [key for key in keys if owners[key] in group]
        job_ids = {_check_id(job, repository) for wid in group for job in _rows(jobs[wid], "jobs")}
        current_checks = [check for check in checks if check["id"] in job_ids]
        reports.append(
            analyze_snapshot(
                {
                    "repository": repository,
                    "head_sha": sha,
                    "event": event,
                    "required": {
                        "checks": [{"context": c, "app_id": app} for c, app in group_keys]
                    },
                    "runs": list(group.values()),
                    "checks": {
                        "total_count": len(current_checks),
                        "check_runs": current_checks,
                    },
                    "jobs": [jobs[wid] for wid in group],
                }
            )
        )
    latest_runs = main_runs()
    if (
        api(ref_route) != main
        or api(rules_route, protection=True) != required
        or any(
            not same_run(api(f"{prefix}/actions/runs/{run['id']}"), run)
            or any(
                row.get("workflow_id") == wid
                and row.get("head_sha") == sha
                and row.get("head_branch") == "main"
                and row.get("event") in events
                and (_time(row["created_at"]), row["id"]) > (_time(run["created_at"]), run["id"])
                for row in latest_runs
            )
            for wid, run in selected.items()
        )
    ):
        raise ValueError("Main, protection or workflow attempt changed during readback")
    return {
        "schema": 1,
        "scope": "release_protected_checks",
        "status": (
            "success" if all(row["status"] == "success" for row in reports) else "incomplete"
        ),
        "repository": repository,
        "head_sha": sha,
        "main_sha": main_sha,
        "source_policy": "authorized_frozen_main"
        if authorized_frozen_sha is not None
        else "current_main",
        "merge_authorized": False,
        "test_source_sha_verified": False,
        "required_count": len(keys),
        "checks": [check for row in reports for check in row.get("checks", [])],
        "issues": [issue for row in reports for issue in row.get("issues", [])],
        "events": sorted({run["event"] for run in selected.values()}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="Offline snapshot JSON")
    parser.add_argument("--repository", help="Repository for live release checks")
    parser.add_argument("--release-sha", help="Read current main's protected checks through gh")
    parser.add_argument(
        "--authorized-frozen-sha",
        help="Exact main ancestor already authorized by the protected frozen publication workflow",
    )
    parser.add_argument("--output", type=Path, help="Default: write JSON to stdout")
    args = parser.parse_args()
    if (
        bool(args.input) == bool(args.release_sha)
        or bool(args.repository) != bool(args.release_sha)
        or (args.authorized_frozen_sha is not None and not args.release_sha)
    ):
        parser.error("Provide an offline input or both --repository and --release-sha")
    try:
        report = (
            collect_release_checks(
                args.repository, args.release_sha, authorized_frozen_sha=args.authorized_frozen_sha
            )
            if args.release_sha
            else analyze_snapshot(json.loads(args.input.read_text(encoding="utf-8")))
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        report = {"schema": 1, "status": "invalid", "issues": [str(exc)]}
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
