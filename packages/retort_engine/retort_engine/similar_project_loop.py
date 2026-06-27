from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


DEPTH_TERMS = {
    "pr": 10,
    "pull request": 16,
    "review": 18,
    "reviewer": 20,
    "code review": 22,
    "diff": 16,
    "hunk": 18,
    "inline comment": 14,
    "github action": 8,
    "quality": 8,
    "benchmark": 10,
    "static analysis": 18,
    "security scan": 16,
    "dependency graph": 16,
    "code graph": 16,
    "semantic index": 18,
    "codebase context": 16,
    "repository context": 16,
}
BREADTH_TERMS = {
    "marketplace": 20,
    "plugin marketplace": 24,
    "model provider": 14,
    "multi provider": 12,
    "integration platform": 16,
    "slack": 8,
    "asana": 8,
}
ALLOWED_LICENSES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc"}
DEFAULT_QUERY = "AI PR reviewer"
CORE_DEPTH_SIGNALS = {
    "review_pipeline",
    "file_grouping",
    "diff_hunk_review",
    "benchmarking",
    "benchmark_eval",
    "safety_policy",
    "workflow_ci",
    "codebase_graph",
    "static_analysis",
    "context_packaging",
    "semantic_index",
}


def build_similar_project_radar(
    project: str | Path,
    *,
    candidates: list[dict[str, Any]] | None = None,
    query: str = DEFAULT_QUERY,
    limit: int = 10,
    min_score: int = 55,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    search_result: dict[str, Any] = {"status": "provided", "items": [], "returncode": 0, "stderr_tail": ""}
    if candidates is None:
        search_result = _search_github_repos(query=query, limit=max(limit * 3, 20))
        raw_candidates = list(search_result.get("items") or [])
    else:
        raw_candidates = candidates
    absorbed = _absorbed_sources(root)
    scored = [_score_candidate(item, absorbed) for item in raw_candidates]
    accepted = [item for item in scored if item["similarity_depth_score"] >= min_score and not item["already_absorbed"] and item["license_allowed"]]
    accepted = sorted(accepted, key=lambda item: (item["similarity_depth_score"], item["stars"]), reverse=True)[:limit]
    rejected = [item for item in scored if item not in accepted]
    status = "search_failed" if search_result.get("status") == "search_failed" else ("ready" if accepted else "no_candidates")
    return {
        "status": status,
        "project": str(root),
        "query": query,
        "summary": {
            "candidate_count": len(scored),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "already_absorbed_count": sum(1 for item in scored if item["already_absorbed"]),
            "min_score": min_score,
            "search_status": search_result.get("status", "provided"),
            "search_returncode": search_result.get("returncode", 0),
            "search_stderr_tail": search_result.get("stderr_tail", ""),
        },
        "candidates": accepted,
        "rejected": sorted(rejected, key=lambda item: item["similarity_depth_score"], reverse=True)[: min(20, len(rejected))],
    }


def run_similar_project_loop(
    project: str | Path,
    *,
    sources: list[str] | None = None,
    limit: int = 3,
    min_score: int = 55,
    run_local_gates: bool = True,
    branch_workflow: bool = True,
    merge_after: bool = True,
    allow_dirty_branch: bool = False,
    use_llm: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    candidates = [_candidate_from_url(source) for source in sources or []]
    radar = build_similar_project_radar(root, candidates=candidates or None, limit=limit, min_score=min_score)
    selected = radar["candidates"][:limit]
    runs: list[dict[str, Any]] = []
    if not dry_run:
        from retort_engine.core import absorb

        for candidate in selected:
            source = str(candidate["url"])
            try:
                result = absorb(
                    {
                        "own_project": str(root),
                        "github_url": source,
                        "run_local_gates": run_local_gates,
                        "branch_workflow": branch_workflow,
                        "merge_after": merge_after,
                        "allow_dirty_branch": allow_dirty_branch,
                        "refresh": True,
                        "use_llm": use_llm,
                        "employee_queue": str(root / ".retort" / "employee_queue.jsonl"),
                        "history_store": str(root / ".retort" / "retort_history.sqlite"),
                    }
                )
                runs.append(_loop_run_summary(candidate, result))
            except Exception as exc:
                runs.append(_loop_failure_summary(candidate, exc))
    else:
        runs = [{"candidate": candidate, "status": "dry_run"} for candidate in selected]
    remaining = [item for item in radar["candidates"] if item not in selected]
    saturation_candidates = remaining + list(radar.get("rejected") or [])
    saturation = build_absorption_saturation_report(
        root,
        remaining_candidates=saturation_candidates,
        min_score=min_score,
        radar_status=radar.get("status", ""),
        search_error=radar.get("summary", {}).get("search_stderr_tail", ""),
    )
    if radar.get("status") == "search_failed":
        status = "search_failed"
    elif not selected:
        status = "no_candidates"
    elif dry_run:
        status = "ready"
    else:
        status = "ready" if all(run.get("gates_passed") for run in runs) else "needs_attention"
    return {
        "status": status,
        "project": str(root),
        "summary": {
            "selected_count": len(selected),
            "completed_count": sum(1 for run in runs if run.get("status") in {"absorption_execution_applied", "dry_run"}),
            "failed_count": sum(1 for run in runs if run.get("status") == "absorption_failed"),
            "gates_passed_count": sum(1 for run in runs if run.get("gates_passed")),
            "remaining_candidate_count": len(remaining),
            "search_status": radar.get("summary", {}).get("search_status", ""),
        },
        "radar": radar,
        "runs": runs,
        "saturation": saturation,
    }


def build_absorption_saturation_report(
    project: str | Path,
    *,
    recent_limit: int = 3,
    remaining_candidates: list[dict[str, Any]] | None = None,
    min_score: int = 55,
    radar_status: str = "",
    search_error: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    radar_summary: dict[str, Any] = {}
    if remaining_candidates is None:
        radar = build_similar_project_radar(root, limit=10, min_score=min_score)
        remaining_candidates = list(radar.get("candidates") or []) + list(radar.get("rejected") or [])
        radar_summary = dict(radar.get("summary") or {})
        radar_status = str(radar.get("status") or radar_status)
        search_error = str(radar_summary.get("search_stderr_tail") or search_error)
    runs = _load_absorption_runs(root)
    seen: set[str] = set()
    enriched: list[dict[str, Any]] = []
    for run in runs:
        signals = set(_core_signals(run))
        new_signals = sorted(signals - seen)
        seen.update(signals)
        enriched.append(
            {
                "source": run.get("source", ""),
                "status": run.get("status", ""),
                "gates_passed": bool(run.get("gates_passed")),
                "core_signals": sorted(signals),
                "new_core_signal_count": len(new_signals),
                "changed_file_count": len(run.get("changed_files") or []),
            }
        )
    recent = enriched[-recent_limit:]
    consecutive_no_new = 0
    for item in reversed(enriched):
        if item["new_core_signal_count"] != 0:
            break
        consecutive_no_new += 1
    remaining_count = 0 if remaining_candidates is None else len(remaining_candidates)
    strong_remaining = [item for item in remaining_candidates or [] if _is_open_depth_candidate(item, min_score=min_score)]
    strong_remaining_count = len(strong_remaining)
    recent_green = len(recent) >= recent_limit and all(item["gates_passed"] for item in recent)
    no_new_depth = consecutive_no_new >= recent_limit
    no_strong_remaining = remaining_candidates is not None and strong_remaining_count == 0
    search_failed = radar_status == "search_failed" or str(radar_summary.get("search_status") or "") == "search_failed"
    saturated = bool(recent_green and not search_failed and (no_new_depth or no_strong_remaining))
    saturation_basis = "not_saturated"
    if search_failed:
        saturation_basis = "search_failed"
    elif saturated and no_new_depth:
        saturation_basis = "recent_absorptions_add_no_new_core_depth"
    elif saturated and no_strong_remaining:
        saturation_basis = "remaining_candidates_below_min_score"
    return {
        "status": "search_failed" if search_failed else ("saturated" if saturated else "not_saturated"),
        "project": str(root),
        "summary": {
            "absorption_run_count": len(enriched),
            "recent_limit": recent_limit,
            "recent_gate_green_count": sum(1 for item in recent if item["gates_passed"]),
            "consecutive_no_new_core_depth_count": consecutive_no_new,
            "remaining_candidate_count": remaining_count,
            "remaining_strong_depth_candidate_count": strong_remaining_count,
            "remaining_low_depth_candidate_count": max(0, remaining_count - strong_remaining_count),
            "min_score": min_score,
            "radar_candidate_count": radar_summary.get("candidate_count", ""),
            "radar_accepted_count": radar_summary.get("accepted_count", ""),
            "radar_status": radar_status,
            "search_error": search_error,
            "saturated": saturated,
            "saturation_basis": saturation_basis,
        },
        "recent_runs": recent,
        "requirements": [
            "latest similar-project absorptions keep gates green",
            "recent projects add no new core-depth signal OR remaining candidates are below the depth threshold",
            "GitHub search failure is never treated as saturation",
            "marketplace candidates remain closed until saturation",
        ],
    }


def _search_github_repos(*, query: str, limit: int) -> dict[str, Any]:
    cmd = ["gh", "search", "repos", query, "--limit", str(limit), "--json", "fullName,description,stargazersCount,updatedAt,url,license"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"status": "search_failed", "items": [], "returncode": -1, "stderr_tail": _tail(exc.stderr or "gh search timed out")}
    except OSError as exc:
        return {"status": "search_failed", "items": [], "returncode": -1, "stderr_tail": _tail(str(exc))}
    if result.returncode != 0:
        return {"status": "search_failed", "items": [], "returncode": result.returncode, "stderr_tail": _tail(result.stderr)}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "search_failed", "items": [], "returncode": result.returncode, "stderr_tail": _tail(result.stderr or result.stdout)}
    return {"status": "ready", "items": [item for item in payload if isinstance(item, dict)], "returncode": result.returncode, "stderr_tail": _tail(result.stderr)}


def _score_candidate(item: dict[str, Any], absorbed: set[str]) -> dict[str, Any]:
    url = str(item.get("url") or "")
    full_name = str(item.get("fullName") or _full_name_from_url(url))
    description = str(item.get("description") or "")
    license_key = str(((item.get("license") or {}) if isinstance(item.get("license"), dict) else {}).get("key") or "").lower()
    text = _candidate_text(full_name, description)
    depth_score = sum(weight for term, weight in DEPTH_TERMS.items() if _term_present(text, term))
    breadth_penalty = sum(weight for term, weight in BREADTH_TERMS.items() if _term_present(text, term))
    license_allowed = not license_key or license_key in ALLOWED_LICENSES
    if license_allowed:
        depth_score += 8
    if _term_present(text, "pr") or _term_present(text, "pull"):
        depth_score += 10
    score = max(0, min(100, depth_score - breadth_penalty))
    source_url = url or f"https://github.com/{full_name}"
    return {
        "full_name": full_name,
        "url": source_url,
        "description": description,
        "license": license_key,
        "license_allowed": license_allowed,
        "stars": int(item.get("stargazersCount") or item.get("stars") or 0),
        "updated_at": str(item.get("updatedAt") or ""),
        "similarity_depth_score": score,
        "breadth_penalty": breadth_penalty,
        "already_absorbed": source_url.lower() in absorbed or full_name.lower() in absorbed,
        "reason": _score_reason(score, breadth_penalty, license_allowed),
    }


def _score_reason(score: int, breadth_penalty: int, license_allowed: bool) -> str:
    if not license_allowed:
        return "license_not_allowed_for_auto_absorption"
    if breadth_penalty:
        return "same_direction_with_breadth_penalty"
    if score >= 70:
        return "strong_same_direction_pr_review_depth"
    return "weak_or_partial_similarity"


def _candidate_from_url(source: str) -> dict[str, Any]:
    return {
        "url": source,
        "fullName": _full_name_from_url(source),
        "description": "AI PR reviewer for pull request code review",
        "stargazersCount": 0,
        "license": {"key": "mit"},
    }


def _candidate_text(full_name: str, description: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", f"{full_name} {description}".lower()).strip()


def _term_present(text: str, term: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
    if not normalized:
        return False
    if normalized == "review":
        return re.search(r"(?<![a-z0-9])review(?:s|er|ing)?(?![a-z0-9])", text) is not None
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in normalized.split()) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _is_open_depth_candidate(item: dict[str, Any], *, min_score: int) -> bool:
    if "similarity_depth_score" not in item:
        return True
    score = int(item.get("similarity_depth_score") or 0)
    license_allowed = bool(item.get("license_allowed", True))
    already_absorbed = bool(item.get("already_absorbed", False))
    return score >= min_score and license_allowed and not already_absorbed


def _tail(value: object, limit: int = 500) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    return text.strip()[-limit:]


def _full_name_from_url(url: str) -> str:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s#?]+)/(?P<repo>[^/\s#?]+)", url)
    if not match:
        return url.strip()
    return f"{match.group('owner')}/{match.group('repo').removesuffix('.git')}"


def _absorbed_sources(root: Path) -> set[str]:
    values: set[str] = set()
    for run in _load_absorption_runs(root):
        source = str(run.get("source") or "").lower()
        if source:
            values.add(source)
            values.add(_full_name_from_url(source).lower())
    return values


def _load_absorption_runs(root: Path) -> list[dict[str, Any]]:
    runs_dir = root / ".retort" / "real_absorption_runs"
    rows: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _core_signals(run: dict[str, Any]) -> list[str]:
    signals = [str(item) for item in ((run.get("external_profile") or {}).get("signals") or [])]
    return [signal for signal in signals if signal in CORE_DEPTH_SIGNALS]


def _loop_run_summary(candidate: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    return {
        "candidate": candidate,
        "status": result.get("status"),
        "execution_status": execution.get("status"),
        "gates_passed": bool(execution.get("gates_passed")),
        "changed_file_count": len(execution.get("changed_files") or []),
        "branch_status": (result.get("branch_workflow") or {}).get("status") if isinstance(result.get("branch_workflow"), dict) else "",
        "task_count": len(result.get("tasks") or []),
    }


def _loop_failure_summary(candidate: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "status": "absorption_failed",
        "execution_status": "failed",
        "gates_passed": False,
        "changed_file_count": 0,
        "branch_status": "",
        "task_count": 0,
        "error": str(exc),
    }
