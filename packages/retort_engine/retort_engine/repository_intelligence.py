from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


SKIP_DIRS = {".git", ".retort", ".venv", "__pycache__", "node_modules", "dist", "build"}


def build_ranked_repository_map(
    project: str | Path,
    *,
    focus_terms: Sequence[str] = (),
    max_files: int = 24,
    max_chars: int = 24_000,
) -> dict[str, Any]:
    """Build a bounded repository map ranked by dependency PageRank and task focus.

    This is Retort's project-understanding primitive.  It adapts Aider's useful
    idea (rank symbols/files by their position in the repository graph) without
    importing Aider or requiring tree-sitter at runtime.
    """
    root = Path(project).expanduser().resolve()
    files = _python_files(root)
    module_index = _module_index(root, files)
    edges: dict[str, set[str]] = {
        path.relative_to(root).as_posix(): set() for path in files
    }
    symbols: dict[str, list[str]] = {}
    parse_errors: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError):
            parse_errors.append(rel)
            continue
        symbols[rel] = sorted(
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for imported in _imports(tree):
            target = _resolve_module(imported, module_index)
            if target and target != rel:
                edges[rel].add(target)

    ranks = _page_rank(edges)
    terms = [str(term).lower().strip() for term in focus_terms if str(term).strip()]
    rows: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        lowered = text.lower()
        focus_hits = sum(lowered.count(term) for term in terms)
        dependency_rank = ranks.get(rel, 0.0)
        score = dependency_rank * 1000.0 + min(focus_hits, 100) * 5.0
        rows.append(
            {
                "path": rel,
                "score": round(score, 6),
                "page_rank": round(dependency_rank, 8),
                "focus_hits": focus_hits,
                "symbols": symbols.get(rel, [])[:40],
                "outgoing_dependencies": sorted(edges.get(rel, set())),
                "char_count": len(text),
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), str(row["path"])))
    selected: list[dict[str, Any]] = []
    used_chars = 0
    per_file_budget = max(1, max_chars // max(1, max_files))
    for row in rows:
        if len(selected) >= max_files or used_chars >= max_chars:
            break
        budget = min(int(row["char_count"]), per_file_budget, max_chars - used_chars)
        if budget <= 0:
            selected.append({**row, "included_chars": 0})
            continue
        selected.append({**row, "included_chars": budget})
        used_chars += budget
    return {
        "status": "ready" if selected else "empty",
        "project": str(root),
        "summary": {
            "candidate_file_count": len(files),
            "selected_file_count": len(selected),
            "dependency_edge_count": sum(len(items) for items in edges.values()),
            "parse_error_count": len(parse_errors),
            "used_chars": used_chars,
            "max_chars": max_chars,
        },
        "focus_terms": terms,
        "files": selected,
        "evidence": {
            "algorithm": "personalized_file_pagerank_plus_focus_hits",
            "absorbed_from": "https://github.com/Aider-AI/aider/blob/main/aider/repomap.py",
            "parse_errors": parse_errors,
        },
    }


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if path.is_file()
        and not any(part in SKIP_DIRS for part in path.relative_to(root).parts)
    ]


def _module_index(root: Path, files: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        module = ".".join(parts)
        result[module] = rel
        result.setdefault(parts[-1], rel)
    return result


def _imports(tree: ast.AST) -> list[str]:
    rows: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.append(node.module)
    return rows


def _resolve_module(imported: str, index: dict[str, str]) -> str:
    normalized = imported.strip(".")
    parts = normalized.split(".")
    for size in range(len(parts), 0, -1):
        candidate = ".".join(parts[:size])
        if candidate in index:
            return index[candidate]
    return ""


def compare_repository_gaps(
    own_project: str | Path,
    external_project: str | Path,
    *,
    focus_terms: Sequence[str] = (
        "absorb",
        "agent",
        "benchmark",
        "evaluation",
        "repository",
        "task",
    ),
    max_files: int = 16,
) -> dict[str, Any]:
    """Compare own vs external repository maps and emit symbol/file gaps for absorption."""
    own_map = build_ranked_repository_map(
        own_project, focus_terms=focus_terms, max_files=max_files, max_chars=16_000
    )
    external_map = build_ranked_repository_map(
        external_project, focus_terms=focus_terms, max_files=max_files, max_chars=16_000
    )
    own_symbols = {
        symbol
        for row in own_map.get("files") or []
        for symbol in row.get("symbols") or []
    }
    gaps: list[dict[str, Any]] = []
    for row in external_map.get("files") or []:
        missing_symbols = [
            symbol for symbol in row.get("symbols") or [] if symbol not in own_symbols
        ]
        if not missing_symbols and row["path"] in {
            item["path"] for item in own_map.get("files") or []
        }:
            continue
        gaps.append(
            {
                "external_path": row["path"],
                "page_rank": row["page_rank"],
                "focus_hits": row["focus_hits"],
                "missing_symbols": missing_symbols[:20],
                "suggested_own_targets": _suggested_own_targets_for_gap(
                    own_map,
                    external_path=str(row["path"]),
                    missing_symbols=missing_symbols,
                    limit=3,
                ),
            }
        )
    gaps.sort(
        key=lambda item: (
            -float(item["page_rank"]),
            -int(item["focus_hits"]),
            str(item["external_path"]),
        )
    )
    return {
        "status": "ready"
        if own_map["status"] == "ready" and external_map["status"] == "ready"
        else "partial",
        "summary": {
            "gap_count": len(gaps),
            "own_selected_file_count": own_map["summary"]["selected_file_count"],
            "external_selected_file_count": external_map["summary"][
                "selected_file_count"
            ],
            "decision_source": "repository_graph_gap",
            "marker_scan_is_auxiliary": True,
        },
        "gaps": gaps,
        "own_top_targets": task_targets_from_map(own_map, limit=5),
        "own_map_summary": own_map["summary"],
        "external_map_summary": external_map["summary"],
    }


def tasks_from_repository_gaps(
    gap: dict[str, Any],
    own_map: dict[str, Any] | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Convert repository graph gaps into absorption tasks with target_files."""
    tasks: list[dict[str, Any]] = []
    fallback_targets = task_targets_from_map(own_map or {}, limit=3) if own_map else []
    for index, row in enumerate((gap.get("gaps") or [])[: max(0, limit)], start=1):
        if not isinstance(row, dict):
            continue
        missing = [str(item) for item in row.get("missing_symbols") or []][:12]
        targets = [
            item
            for item in row.get("suggested_own_targets") or []
            if isinstance(item, dict)
        ]
        if not targets:
            targets = fallback_targets
        paths = [str(item.get("path") or "") for item in targets if item.get("path")]
        external_path = str(row.get("external_path") or "")
        tasks.append(
            {
                "task_id": f"retort-gap-{index:02d}",
                "title": f"Close repository gap from {external_path or 'external module'}",
                "dimension": "diff_hunk_review"
                if missing
                else "comparative_analysis_depth",
                "why": (
                    f"External exposes symbols missing locally: {', '.join(missing[:5])}."
                    if missing
                    else f"External file {external_path} is a graph-ranked absorption candidate."
                ),
                "action": f"Implement missing behavior toward target_files={','.join(paths)}",
                "acceptance": (
                    f"Own map covers symbols {', '.join(missing[:3])} or records a justified deferral."
                    if missing
                    else f"Gap for {external_path} is closed or deferred with evidence."
                ),
                "owner_hint": "fhd-core-maintainer",
                "priority": "P0" if missing else "P1",
                "target_files": paths,
                "missing_symbols": missing,
                "external_path": external_path,
                "source": "repository_graph_gap",
            }
        )
    return tasks


def task_targets_from_map(
    repo_map: dict[str, Any], *, limit: int = 5
) -> list[dict[str, Any]]:
    """Turn a ranked repository map into absorption task target_files/symbols."""
    targets: list[dict[str, Any]] = []
    for row in (repo_map.get("files") or [])[: max(0, limit)]:
        targets.append(
            {
                "path": row["path"],
                "symbols": list(row.get("symbols") or [])[:12],
                "score": row.get("score"),
                "page_rank": row.get("page_rank"),
                "focus_hits": row.get("focus_hits"),
            }
        )
    return targets


def _suggested_own_targets_for_gap(
    own_map: dict[str, Any],
    *,
    external_path: str,
    missing_symbols: list[str],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Pick own targets per gap row (basename/rank), not a repeated whole-map default."""
    external_name = Path(external_path).name
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in own_map.get("files") or []:
        if not isinstance(row, dict):
            continue
        score = (
            float(row.get("page_rank") or 0.0) * 1000.0
            + float(row.get("focus_hits") or 0) * 5.0
        )
        if Path(str(row.get("path") or "")).name == external_name:
            score += 500.0
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("path") or "")))
    targets: list[dict[str, Any]] = []
    for score, row in scored[: max(0, limit)]:
        targets.append(
            {
                "path": row["path"],
                "symbols": list(row.get("symbols") or [])[:12],
                "score": round(score, 6),
                "page_rank": row.get("page_rank"),
                "focus_hits": row.get("focus_hits"),
                "matched_for_external": external_path,
                "missing_symbols": list(missing_symbols)[:8],
            }
        )
    return targets


def _page_rank(
    edges: dict[str, set[str]], *, damping: float = 0.85, rounds: int = 30
) -> dict[str, float]:
    nodes = sorted(edges)
    if not nodes:
        return {}
    incoming: dict[str, set[str]] = defaultdict(set)
    for source, targets in edges.items():
        for target in targets:
            if target in edges:
                incoming[target].add(source)
    ranks = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(rounds):
        dangling = sum(ranks[node] for node in nodes if not edges[node]) / len(nodes)
        next_ranks: dict[str, float] = {}
        for node in nodes:
            link_rank = sum(
                ranks[parent] / len(edges[parent])
                for parent in incoming.get(node, set())
            )
            next_ranks[node] = (1.0 - damping) / len(nodes) + damping * (
                dangling + link_rank
            )
        ranks = next_ranks
    return ranks
