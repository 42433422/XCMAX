from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


GitHubFetcher = Callable[[str], dict[str, Any]]

DEFAULT_UPSTREAM_PR_TARGETS: tuple[dict[str, Any], ...] = (
    {"repo": "psf/requests", "pr_number": 7536},
    {"repo": "pytest-dev/pytest", "pr_number": 14657},
    {"repo": "encode/httpx", "pr_number": 3773},
    {"repo": "fastapi/fastapi", "pr_number": 15852},
    {"repo": "django/django", "pr_number": 19810},
)


def build_upstream_pr_ci_probe(
    project: str | Path,
    *,
    repo: str = "",
    pr_number: int = 0,
    targets: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    output: str | Path = "",
    fetcher: GitHubFetcher | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    fetch = fetcher or _gh_api
    selected_targets = _targets(repo=repo, pr_number=pr_number, targets=targets)
    probes = [_probe_target(target, fetch=fetch) for target in selected_targets]
    ready_probes = [probe for probe in probes if probe["ready"]]
    primary = probes[0] if probes else _empty_probe()
    successful_check_count = sum(int(probe["summary"]["successful_check_run_count"]) for probe in probes)
    check_count = sum(int(probe["summary"]["check_run_count"]) for probe in probes)
    failed_check_count = sum(int(probe["summary"]["failed_check_run_count"]) for probe in probes)
    distinct_repos = {probe["summary"]["repo"] for probe in probes if probe["summary"].get("repo")}
    all_check_runs_successful = bool(probes) and len(ready_probes) == len(probes)
    summary = {
        **primary["summary"],
        "target_count": len(probes),
        "ready_target_count": len(ready_probes),
        "distinct_repo_count": len(distinct_repos),
        "target_repositories": sorted(distinct_repos),
        "total_check_run_count": check_count,
        "total_successful_check_run_count": successful_check_count,
        "total_failed_check_run_count": failed_check_count,
        "all_target_prs_merged": bool(probes) and all(probe["summary"]["merged"] is True for probe in probes),
        "all_target_check_runs_successful": all_check_runs_successful,
        "all_targets_real_remote_api": fetcher is None,
        "multi_repo_ci_generalization": len(distinct_repos) >= 3 and len(ready_probes) >= 3 and all_check_runs_successful,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = summary["multi_repo_ci_generalization"] if len(probes) >= 3 else primary["ready"]
    result = {
        "status": "ready" if ready else "needs_upstream_pr_ci_evidence",
        "project": str(root),
        "summary": summary,
        "pull_request": primary["pull_request"],
        "pull_requests": [probe["pull_request"] for probe in probes],
        "check_runs": primary["check_runs"],
        "target_check_runs": [{"repo": probe["summary"]["repo"], "pr_number": probe["summary"]["pr_number"], "check_runs": probe["check_runs"]} for probe in probes],
        "probes": probes,
        "evidence": {
            "style": "readonly_real_upstream_merged_pr_and_ci_probe",
            "transport": "gh_api" if fetcher is None else "injected_fetcher",
            "acceptance": "three_public_merged_prs_with_all_check_runs_successful",
            "default_targets": DEFAULT_UPSTREAM_PR_TARGETS,
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _probe_target(target: dict[str, Any], *, fetch: GitHubFetcher) -> dict[str, Any]:
    repo = str(target["repo"])
    pr_number = int(target["pr_number"])
    pr = fetch(f"repos/{repo}/pulls/{pr_number}")
    merge_sha = str(pr.get("merge_commit_sha") or "")
    checks = fetch(f"repos/{repo}/commits/{merge_sha}/check-runs?per_page=100") if merge_sha else {}
    runs = [run for run in checks.get("check_runs") or [] if isinstance(run, dict)]
    successful = [run for run in runs if run.get("status") == "completed" and run.get("conclusion") == "success"]
    failed = [run for run in runs if run.get("conclusion") not in {"success", None}]
    summary = {
        "repo": repo,
        "pr_number": pr_number,
        "pr_url": pr.get("html_url", ""),
        "merged": pr.get("merged") is True,
        "merged_at": pr.get("merged_at", ""),
        "merge_commit_sha": merge_sha,
        "check_run_count": len(runs),
        "successful_check_run_count": len(successful),
        "failed_check_run_count": len(failed),
        "all_check_runs_successful": bool(runs) and len(successful) == len(runs),
        "real_remote_api": fetch is _gh_api,
    }
    ready = summary["merged"] and bool(merge_sha) and summary["check_run_count"] > 0 and summary["all_check_runs_successful"]
    return {
        "status": "ready" if ready else "needs_upstream_pr_ci_evidence",
        "ready": ready,
        "summary": summary,
        "pull_request": pr,
        "check_runs": [
            {
                "name": str(run.get("name") or ""),
                "status": str(run.get("status") or ""),
                "conclusion": str(run.get("conclusion") or ""),
                "html_url": str(run.get("html_url") or ""),
            }
            for run in runs
        ],
    }


def _targets(
    *,
    repo: str,
    pr_number: int,
    targets: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> list[dict[str, Any]]:
    if targets is not None:
        return [{"repo": str(item["repo"]), "pr_number": int(item["pr_number"])} for item in targets]
    if repo or pr_number:
        return [{"repo": repo or DEFAULT_UPSTREAM_PR_TARGETS[0]["repo"], "pr_number": int(pr_number or DEFAULT_UPSTREAM_PR_TARGETS[0]["pr_number"])}]
    return [dict(item) for item in DEFAULT_UPSTREAM_PR_TARGETS]


def _empty_probe() -> dict[str, Any]:
    return {
        "ready": False,
        "summary": {
            "repo": "",
            "pr_number": 0,
            "pr_url": "",
            "merged": False,
            "merged_at": "",
            "merge_commit_sha": "",
            "check_run_count": 0,
            "successful_check_run_count": 0,
            "failed_check_run_count": 0,
            "all_check_runs_successful": False,
            "real_remote_api": False,
        },
        "pull_request": {},
        "check_runs": [],
    }


def _gh_api(path: str) -> dict[str, Any]:
    completed = subprocess.run(["gh", "api", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    if completed.returncode != 0:
        return {"error": completed.stderr[-500:], "path": path}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "path": path, "stdout_tail": completed.stdout[-500:]}
    return payload if isinstance(payload, dict) else {"items": payload}
