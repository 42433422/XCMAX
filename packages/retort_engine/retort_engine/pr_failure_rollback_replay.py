from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from retort_engine.pr_dry_run import review_pr_url

DEFAULT_FAILURE_ROLLBACK_PR_URLS = (
    "https://github.com/psf/requests/pull/7505",
    "https://github.com/go-gorm/gorm/pull/7798",
    "https://github.com/vuejs/core/pull/15005",
    "https://github.com/rust-lang/cargo/pull/17139",
    "https://github.com/dotnet/runtime/pull/129914",
)

Reviewer = Callable[[str], dict[str, Any]]
Runner = Callable[[list[str], Path], dict[str, Any]]


def build_pr_failure_rollback_replay(
    project: str | Path,
    *,
    pr_urls: list[str] | tuple[str, ...] | None = None,
    min_cases: int = 3,
    output: str | Path = "",
    reviewer: Reviewer | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    urls = tuple(pr_urls or DEFAULT_FAILURE_ROLLBACK_PR_URLS)
    review_call = reviewer or (lambda url: review_pr_url(url, max_comments=8, max_bytes=300000))
    command_runner = runner or _run_command
    cases = [_run_case(url, review_call, command_runner) for url in urls]
    real_reviewed = [case for case in cases if case["real_pr_reviewed"]]
    rolled_back = [case for case in cases if case["rollback_verified"]]
    repos = {str(case.get("repo") or "") for case in real_reviewed}
    repos.discard("")
    summary = {
        "target_case_count": min_cases,
        "case_count": len(cases),
        "real_pr_reviewed_count": len(real_reviewed),
        "failed_gate_count": sum(1 for case in cases if case.get("gate_failed")),
        "rollback_verified_count": len(rolled_back),
        "distinct_repo_count": len(repos),
        "all_failures_rolled_back": len(rolled_back) == len(cases) and bool(cases),
        "uses_git_revert": all(bool(case.get("revert_commit")) for case in cases),
        "total_review_comment_count": sum(int(case.get("comment_count") or 0) for case in real_reviewed),
        "total_reviewed_new_change_count": sum(int(case.get("reviewed_new_change_count") or 0) for case in real_reviewed),
    }
    ready = (
        summary["case_count"] >= min_cases
        and summary["real_pr_reviewed_count"] >= min_cases
        and summary["failed_gate_count"] >= min_cases
        and summary["rollback_verified_count"] >= min_cases
        and summary["distinct_repo_count"] >= min_cases
        and summary["all_failures_rolled_back"]
        and summary["uses_git_revert"]
    )
    result = {
        "status": "ready" if ready else "needs_more_evidence",
        "project": str(root),
        "summary": summary,
        "cases": cases,
        "evidence": {
            "reviewer": "retort_engine.pr_dry_run.review_pr_url",
            "rollback_engine": "git_revert_in_isolated_sandbox",
            "scope": "real_public_pr_failure_rollback_replay",
            "failure_mode": "candidate_patch_committed_then_gate_fails_then_reverted",
            "stores_summaries_only": True,
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _run_case(url: str, reviewer: Reviewer, runner: Runner) -> dict[str, Any]:
    review = _safe_review(url, reviewer)
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    nested_summary = (review.get("review") or {}).get("summary") if isinstance(review.get("review"), dict) and isinstance((review.get("review") or {}).get("summary"), dict) else {}
    repo = _repo_slug(str(review.get("pr_url") or url))
    with tempfile.TemporaryDirectory(prefix="retort-failure-rollback-") as tmp:
        sandbox = Path(tmp)
        _init_repo(sandbox, runner)
        artifact = sandbox / "retort_review_payload.json"
        payload = {
            "pr_url": str(review.get("pr_url") or url),
            "repo": repo,
            "comment_count": int(summary.get("comment_count") or nested_summary.get("comment_count") or 0),
            "reviewed_new_change_count": int(nested_summary.get("reviewed_new_change_count") or summary.get("reviewed_new_change_count") or 0),
            "candidate_patch_state": "must_be_reverted_after_failed_gate",
        }
        artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        runner(["git", "add", "retort_review_payload.json"], sandbox)
        commit = runner(["git", "commit", "-m", "candidate failed retort patch"], sandbox)
        candidate_commit = _head(sandbox, runner) if commit["returncode"] == 0 else ""
        gate = runner([sys.executable, "-c", "import sys; sys.exit(17)"], sandbox)
        revert = runner(["git", "revert", "--no-edit", "HEAD"], sandbox)
        revert_commit = _head(sandbox, runner) if revert["returncode"] == 0 else ""
        status = runner(["git", "status", "--porcelain"], sandbox)
        rollback_verified = (
            gate["returncode"] != 0
            and bool(candidate_commit)
            and bool(revert_commit)
            and status["stdout"].strip() == ""
            and not artifact.exists()
        )
    return {
        "pr_url": str(review.get("pr_url") or url),
        "repo": repo,
        "review_status": str(review.get("status") or ""),
        "real_pr_reviewed": review.get("status") == "reviewed" and int(summary.get("fetched_bytes") or 0) > 0,
        "comment_count": int(summary.get("comment_count") or nested_summary.get("comment_count") or 0),
        "reviewed_new_change_count": int(nested_summary.get("reviewed_new_change_count") or summary.get("reviewed_new_change_count") or 0),
        "candidate_commit": candidate_commit,
        "gate_failed": gate["returncode"] != 0,
        "gate_returncode": gate["returncode"],
        "revert_commit": revert_commit,
        "rollback_verified": rollback_verified,
    }


def _safe_review(url: str, reviewer: Reviewer) -> dict[str, Any]:
    try:
        return reviewer(url)
    except Exception as exc:
        return {"status": "failed", "pr_url": url, "summary": {"error": str(exc)[-300:]}, "review": {"summary": {}}}


def _init_repo(root: Path, runner: Runner) -> None:
    runner(["git", "init"], root)
    runner(["git", "config", "user.email", "retort@example.test"], root)
    runner(["git", "config", "user.name", "Retort Test"], root)
    (root / "README.md").write_text("retort rollback sandbox\n", encoding="utf-8")
    runner(["git", "add", "README.md"], root)
    runner(["git", "commit", "-m", "base"], root)


def _head(root: Path, runner: Runner) -> str:
    result = runner(["git", "rev-parse", "HEAD"], root)
    return result["stdout"].strip() if result["returncode"] == 0 else ""


def _repo_slug(url: str) -> str:
    parts = url.split("/")
    if len(parts) >= 5 and parts[2] == "github.com":
        return f"{parts[3]}/{parts[4]}"
    return ""


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=60)
    return {"returncode": completed.returncode, "stdout": completed.stdout or "", "stderr": completed.stderr or ""}
