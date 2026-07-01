from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LANGUAGE_SUFFIXES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".tf": "terraform",
}
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "myvenv", "__pycache__", ".pytest_cache", ".ruff_cache", "target", "dist", "build"}


def build_generalization_proof(project: str | Path, *, max_projects: int = 40, max_files_per_project: int = 2500) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    external_projects = _external_projects(root)[:max_projects]
    profiles = [_project_profile(path, max_files=max_files_per_project) for path in external_projects]
    language_counts: dict[str, int] = {}
    for profile in profiles:
        for language, count in profile["languages"].items():
            language_counts[language] = language_counts.get(language, 0) + int(count)
    complex_pr = _read_json(root / "docs" / "retort_complex_pr_replay.json")
    pr_dry_run = _read_json(root / "docs" / "retort_pr_dry_run_report.json")
    ci_projects = [profile for profile in profiles if profile["ci_file_count"] > 0]
    large_projects = [profile for profile in profiles if profile["file_count"] >= 500 or profile["source_file_count"] >= 250]
    checks = [
        {
            "id": "multi_external_project_materialized",
            "passed": len(profiles) >= 3,
            "evidence": f"external_project_count={len(profiles)}",
        },
        {
            "id": "cross_language_materialized",
            "passed": len(language_counts) >= 3,
            "evidence": f"language_count={len(language_counts)}",
        },
        {
            "id": "large_upstream_project_materialized",
            "passed": bool(large_projects),
            "evidence": f"large_project_count={len(large_projects)}",
        },
        {
            "id": "upstream_ci_surface_seen",
            "passed": bool(ci_projects),
            "evidence": f"ci_project_count={len(ci_projects)}",
        },
        {
            "id": "pr_runtime_replay_available",
            "passed": complex_pr.get("status") == "ready" or pr_dry_run.get("status") == "reviewed",
            "evidence": f"complex_pr_status={complex_pr.get('status', '')}; pr_dry_run_status={pr_dry_run.get('status', '')}",
        },
    ]
    return {
        "status": "ready" if all(item["passed"] for item in checks) else "needs_more_generalization",
        "summary": {
            "external_project_count": len(profiles),
            "language_count": len(language_counts),
            "languages": language_counts,
            "ci_project_count": len(ci_projects),
            "large_project_count": len(large_projects),
            "pr_replay_status": complex_pr.get("status") or pr_dry_run.get("status") or "",
        },
        "checks": checks,
        "projects": profiles,
    }


def write_generalization_proof(project: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    result = build_generalization_proof(root)
    target = Path(output).expanduser().resolve() if output else root / "docs" / "retort_generalization_proof.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    result["output"] = str(target)
    return result


def _external_projects(root: Path) -> list[Path]:
    cache = root / ".retort" / "cache" / "github"
    if not cache.is_dir():
        return []
    projects: list[Path] = []
    for owner in sorted(cache.iterdir()):
        if not owner.is_dir():
            continue
        for repo in sorted(owner.iterdir()):
            if repo.is_dir():
                projects.append(repo)
    return projects


def _project_profile(path: Path, *, max_files: int) -> dict[str, Any]:
    languages: dict[str, int] = {}
    file_count = 0
    source_count = 0
    ci_count = 0
    truncated = False
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        if set(file_path.relative_to(path).parts) & SKIP_PARTS:
            continue
        file_count += 1
        if file_count > max_files:
            truncated = True
            break
        suffix = file_path.suffix.lower()
        language = LANGUAGE_SUFFIXES.get(suffix)
        if language:
            languages[language] = languages.get(language, 0) + 1
            source_count += 1
        rel = file_path.relative_to(path).as_posix().lower()
        if rel.startswith(".github/workflows/") or rel in {"jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"}:
            ci_count += 1
    return {
        "name": "/".join(path.parts[-2:]),
        "path": str(path),
        "file_count": file_count,
        "source_file_count": source_count,
        "languages": languages,
        "ci_file_count": ci_count,
        "truncated": truncated,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
