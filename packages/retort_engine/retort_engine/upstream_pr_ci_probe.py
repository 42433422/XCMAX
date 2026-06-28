from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


GitHubFetcher = Callable[[str], dict[str, Any]]


def build_upstream_pr_ci_probe(
    project: str | Path,
    *,
    repo: str = "psf/requests",
    pr_number: int = 7539,
    output: str | Path = "",
    fetcher: GitHubFetcher | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    fetch = fetcher or _gh_api
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
        "real_remote_api": fetcher is None,
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = summary["merged"] and bool(merge_sha) and summary["check_run_count"] > 0 and summary["all_check_runs_successful"]
    result = {
        "status": "ready" if ready else "needs_upstream_pr_ci_evidence",
        "project": str(root),
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
        "evidence": {
            "style": "readonly_real_upstream_merged_pr_and_ci_probe",
            "transport": "gh_api" if fetcher is None else "injected_fetcher",
            "acceptance": "public_merged_pr_with_all_check_runs_successful",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _gh_api(path: str) -> dict[str, Any]:
    completed = subprocess.run(["gh", "api", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    if completed.returncode != 0:
        return {"error": completed.stderr[-500:], "path": path}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "path": path, "stdout_tail": completed.stdout[-500:]}
    return payload if isinstance(payload, dict) else {"items": payload}
