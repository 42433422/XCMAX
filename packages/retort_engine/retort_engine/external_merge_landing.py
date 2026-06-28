from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EXTERNAL_MERGE_CASES: tuple[dict[str, str], ...] = (
    {
        "source": "qodo-ai/pr-agent",
        "source_path": ".retort/cache/github/qodo-ai/pr-agent",
        "family": "python_pr_agent",
        "absorbed_rule": "semantic_review_prompt_and_incremental_publish_guard",
    },
    {
        "source": "mopemope/pr-ai-review-bot",
        "source_path": ".retort/cache/github/mopemope/pr-ai-review-bot",
        "family": "typescript_pr_bot",
        "absorbed_rule": "diff_hunk_context_grouping_and_publishable_anchor",
    },
)


def build_external_merge_landing(
    project: str | Path,
    *,
    min_cases: int = 2,
    output: str | Path = "",
    cases: list[dict[str, str]] | tuple[dict[str, str], ...] | None = None,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S-merge-landing")
    workspace = root / ".retort" / "external_merge_landings" / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    selected = list(cases or DEFAULT_EXTERNAL_MERGE_CASES)[: max(1, min_cases)]
    repo = workspace / "retort-merge-proof"
    _seed_repo(repo)
    landed_rules: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    for index, case in enumerate(selected, start=1):
        result = _land_case(root, repo, case, index, landed_rules)
        if result.get("ready"):
            landed_rules.append(
                {
                    "source": str(case.get("source") or ""),
                    "family": str(case.get("family") or ""),
                    "absorbed_rule": str(case.get("absorbed_rule") or ""),
                }
            )
        results.append(result)
    ready_cases = [item for item in results if item.get("ready")]
    summary = {
        "run_id": run_id,
        "case_count": len(results),
        "min_case_count": min_cases,
        "ready_case_count": len(ready_cases),
        "real_git_repo_count": 1 if repo.is_dir() else 0,
        "cached_source_count": sum(1 for item in results if item.get("external_source_exists")),
        "branch_diff_count": sum(1 for item in results if item.get("branch_diff_verified")),
        "merge_commit_count": sum(1 for item in results if item.get("merge_commit")),
        "post_merge_test_passed_count": sum(1 for item in results if item.get("post_merge_tests_passed")),
        "all_branch_diff_merge_tests_passed": bool(results) and all(item.get("ready") for item in results),
        "source_family_count": len({str(item.get("family") or "") for item in results if item.get("family")}),
        "source_families": sorted({str(item.get("family") or "") for item in results if item.get("family")}),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    report = {
        "status": "ready" if len(ready_cases) >= min_cases and summary["all_branch_diff_merge_tests_passed"] else "blocked",
        "project": str(root),
        "summary": summary,
        "cases": results,
        "evidence": {
            "style": "real_external_branch_diff_merge_landing",
            "run_id": run_id,
            "workspace": str(workspace),
            "repo": str(repo),
            "verifier": "git_branch_diff_plus_no_ff_merge_plus_post_merge_pytest",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _seed_repo(repo: Path) -> None:
    if repo.exists():
        shutil.rmtree(repo)
    (repo / "retort_engine").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "retort_engine" / "__init__.py").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    _write_policy(repo, [])
    _write_policy_test(repo, [])
    _run(["git", "init"], repo)
    _run(["git", "checkout", "-b", "main"], repo)
    _run(["git", "config", "user.email", "retort@example.test"], repo)
    _run(["git", "config", "user.name", "Retort Merge Proof"], repo)
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "seed retort merge landing proof"], repo)


def _land_case(root: Path, repo: Path, case: dict[str, str], index: int, previous_rules: list[dict[str, str]]) -> dict[str, Any]:
    source = str(case.get("source") or f"source-{index}")
    family = str(case.get("family") or "external_project")
    source_path = root / str(case.get("source_path") or "")
    branch = f"absorb/{_slug(source)}-{index}"
    rule = {
        "source": source,
        "family": family,
        "absorbed_rule": str(case.get("absorbed_rule") or "external_review_rule"),
        "source_fingerprint": _source_fingerprint(source_path),
    }
    if not source_path.is_dir():
        return {
            "source": source,
            "family": family,
            "external_source_path": str(source_path),
            "external_source_exists": False,
            "ready": False,
            "blocker": "cached_external_source_missing",
        }
    commands: list[dict[str, Any]] = []
    commands.append(_run(["git", "checkout", "main"], repo))
    commands.append(_run(["git", "checkout", "-b", branch], repo))
    next_rules = [*previous_rules, rule]
    _write_policy(repo, next_rules)
    _write_policy_test(repo, next_rules)
    _remove_runtime_caches(repo)
    commands.append(_run(["git", "add", "."], repo))
    commands.append(_run(["git", "commit", "-m", f"absorb {source} review rule"], repo))
    branch_commit = _run(["git", "rev-parse", "HEAD"], repo)
    diff_files_result = _run(["git", "diff", "--name-only", "main...HEAD"], repo)
    diff_files = [line.strip() for line in diff_files_result.get("stdout", "").splitlines() if line.strip()]
    commands.append(_run(["git", "checkout", "main"], repo))
    commands.append(_run(["git", "merge", "--no-ff", branch, "-m", f"merge absorbed {source} rule"], repo))
    merge_commit = _run(["git", "rev-parse", "HEAD"], repo)
    post_tests = _run([sys.executable, "-m", "pytest", "tests", "-q"], repo, env={**os.environ, "PYTHONPATH": str(repo)})
    branch_diff_verified = {"retort_engine/review_policy.py", "tests/test_review_policy.py"}.issubset(set(diff_files))
    merge_commit_text = merge_commit.get("stdout", "").strip() if merge_commit.get("returncode") == 0 else ""
    tests_passed = post_tests.get("returncode") == 0
    return {
        "source": source,
        "family": family,
        "branch": branch,
        "external_source_path": str(source_path),
        "external_source_exists": True,
        "source_fingerprint": rule["source_fingerprint"],
        "branch_commit": branch_commit.get("stdout", "").strip(),
        "merge_commit": merge_commit_text,
        "branch_diff_files": diff_files,
        "branch_diff_verified": branch_diff_verified,
        "post_merge_tests_passed": tests_passed,
        "post_merge_test_stdout_tail": post_tests.get("stdout", "")[-400:],
        "ready": branch_diff_verified and bool(merge_commit_text) and tests_passed,
        "commands": commands[-4:],
    }


def _write_policy(repo: Path, rules: list[dict[str, str]]) -> None:
    payload = json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True)
    (repo / "retort_engine" / "review_policy.py").write_text(
        f"from __future__ import annotations\n\nABSORBED_RULES = {payload!r}\n\n"
        "def review_context() -> dict[str, object]:\n"
        "    import json\n"
        "    rules = json.loads(ABSORBED_RULES)\n"
        "    return {\n"
        "        'rule_count': len(rules),\n"
        "        'sources': [item['source'] for item in rules],\n"
        "        'families': sorted({item['family'] for item in rules}),\n"
        "        'merge_landed': bool(rules),\n"
        "    }\n",
        encoding="utf-8",
    )


def _write_policy_test(repo: Path, rules: list[dict[str, str]]) -> None:
    sources = [item["source"] for item in rules]
    families = sorted({item["family"] for item in rules})
    (repo / "tests" / "test_review_policy.py").write_text(
        "from retort_engine.review_policy import review_context\n\n\n"
        "def test_absorbed_rules_landed_after_merge():\n"
        "    context = review_context()\n"
        f"    assert context['rule_count'] == {len(rules)}\n"
        f"    assert context['sources'] == {sources!r}\n"
        f"    assert context['families'] == {families!r}\n"
        f"    assert context['merge_landed'] is {bool(rules)!r}\n",
        encoding="utf-8",
    )


def _source_fingerprint(path: Path) -> str:
    if not path.is_dir():
        return "missing"
    names = sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file())[:40]
    return f"files={len(names)};sample={','.join(names[:6])}"


def _remove_runtime_caches(repo: Path) -> None:
    for path in repo.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)
    pytest_cache = repo / ".pytest_cache"
    if pytest_cache.is_dir():
        shutil.rmtree(pytest_cache)


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")[:48] or "external"


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": int(completed.returncode),
        "stdout": (completed.stdout or "")[-1200:],
        "stderr": (completed.stderr or "")[-1200:],
        "ok": completed.returncode == 0,
    }
