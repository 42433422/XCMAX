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
    edges: dict[str, set[str]] = {path.relative_to(root).as_posix(): set() for path in files}
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
            node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
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
            break
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
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(root).parts)
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


def _page_rank(edges: dict[str, set[str]], *, damping: float = 0.85, rounds: int = 30) -> dict[str, float]:
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
            link_rank = sum(ranks[parent] / len(edges[parent]) for parent in incoming.get(node, set()))
            next_ranks[node] = (1.0 - damping) / len(nodes) + damping * (dangling + link_rank)
        ranks = next_ranks
    return ranks
