from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from typing import Any

from retort_engine.codebase_graph import build_codebase_graph


PACK_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
}
SKIP_DIRS = {
    ".git",
    ".retort",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
}
DEFAULT_FOCUS_TERMS = ("retort", "absorb", "review", "benchmark", "codebase", "graph", "security", "context")
GENERATED_CONTEXT_PREFIXES = ("docs/retort_",)


def build_context_pack(
    project: str | Path,
    *,
    focus_terms: Sequence[str] | None = None,
    max_files: int = 24,
    max_chars: int = 24000,
) -> dict[str, Any]:
    """Build a bounded, ranked repository context pack for deep review."""
    root = Path(project).expanduser().resolve()
    terms = _normalize_terms(focus_terms or DEFAULT_FOCUS_TERMS)
    graph = build_codebase_graph(root, include_tests=True, max_files=500)
    graph_degree = {str(item.get("path") or ""): int(item.get("degree") or 0) for item in graph.get("hotspots") or [] if isinstance(item, dict)}
    candidates = [_score_file(root, path, terms, graph_degree) for path in _pack_files(root)]
    ranked = [item for item in candidates if item["score"] > 0]
    if not ranked:
        ranked = sorted(candidates, key=lambda item: (item["path"]))[:max_files]
    ranked = sorted(ranked, key=lambda item: (-int(item["score"]), item["path"]))
    files: list[dict[str, Any]] = []
    used_chars = 0
    per_file_budget = max(1, max_chars // max(1, max_files))
    for item in ranked:
        if len(files) >= max_files or used_chars >= max_chars:
            break
        budget = max(0, min(int(item["char_count"]), per_file_budget, max_chars - used_chars))
        if budget <= 0:
            break
        excerpt = _read_excerpt(root / item["path"], budget)
        used_chars += len(excerpt)
        files.append({**item, "excerpt": excerpt})
    status = "ready" if files else "empty"
    return {
        "status": status,
        "project": str(root),
        "summary": {
            "selected_file_count": len(files),
            "candidate_file_count": len(candidates),
            "used_chars": used_chars,
            "max_chars": max_chars,
            "max_files": max_files,
            "focus_term_count": len(terms),
            "graph_status": graph.get("status"),
        },
        "focus_terms": terms,
        "files": files,
        "evidence": {
            "style": "deterministic_context_packaging",
            "ranking": "term_hits_plus_code_graph_hotspot_degree",
            "source": "repomix_absorbed_context_packaging",
        },
    }


def _pack_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in PACK_SUFFIXES:
            continue
        parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel.startswith(prefix) for prefix in GENERATED_CONTEXT_PREFIXES):
            continue
        files.append(path)
    return files


def _score_file(root: Path, path: Path, terms: list[str], graph_degree: dict[str, int]) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    lowered = text.lower()
    term_hits = sum(lowered.count(term) for term in terms)
    degree = graph_degree.get(rel, 0)
    size_penalty = 5 if len(text) > 50000 else 0
    score = term_hits * 10 + degree * 3 - size_penalty
    return {
        "path": rel,
        "score": max(0, score),
        "term_hits": term_hits,
        "graph_degree": degree,
        "char_count": len(text),
        "reason": _reason(term_hits, degree),
    }


def _reason(term_hits: int, graph_degree: int) -> str:
    if term_hits and graph_degree:
        return "focus_terms_and_graph_hotspot"
    if graph_degree:
        return "code_graph_hotspot"
    if term_hits:
        return "focus_term_match"
    return "fallback_candidate"


def _read_excerpt(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return text[:max_chars]


def _normalize_terms(terms: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for term in terms:
        value = str(term).lower().strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized
