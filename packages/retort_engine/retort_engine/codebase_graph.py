from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


DEFAULT_SUFFIXES = (".py",)
SKIP_DIRS = {".git", ".hg", ".mypy_cache", ".pytest_cache", ".retort", "__pycache__", "node_modules", "dist", "build"}


def build_codebase_graph(project: str | Path, *, include_tests: bool = False, max_files: int = 400) -> dict[str, Any]:
    """Build a deterministic source graph for architecture and absorption targeting."""
    root = Path(project).resolve()
    files = _source_files(root, include_tests=include_tests, max_files=max_files)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        nodes.append({"id": rel, "kind": "file", "path": rel, "name": path.stem, "line": 1})
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append({"path": rel, "error": type(exc).__name__})
            continue
        file_symbols = _symbols_for_file(rel, tree)
        nodes.extend(file_symbols["nodes"])
        edges.extend(file_symbols["edges"])
    hotspots = _hotspots(nodes, edges)
    summary = {
        "file_count": len(files),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "import_edge_count": sum(1 for edge in edges if edge["kind"] == "imports"),
        "define_edge_count": sum(1 for edge in edges if edge["kind"] == "defines"),
        "call_edge_count": sum(1 for edge in edges if edge["kind"] == "calls"),
        "hotspot_count": len(hotspots),
        "parse_error_count": len(parse_errors),
        "include_tests": include_tests,
    }
    return {
        "status": "ready" if files and not parse_errors else ("partial" if files else "empty"),
        "project": str(root),
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
        "hotspots": hotspots,
        "evidence": {
            "style": "deterministic_codebase_graph",
            "source": "codegraph_absorption",
            "parse_errors": parse_errors,
        },
    }


def _source_files(root: Path, *, include_tests: bool, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file() or path.suffix not in DEFAULT_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not include_tests and _is_test_path(rel_parts, path.name):
            continue
        files.append(path)
    return files


def _symbols_for_file(rel: str, tree: ast.AST) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    local_symbols: dict[str, str] = {}
    imports: dict[str, str] = {}
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol_id = f"{rel}:{child.name}"
            kind = "class" if isinstance(child, ast.ClassDef) else "function"
            local_symbols[child.name] = symbol_id
            nodes.append({"id": symbol_id, "kind": kind, "path": rel, "name": child.name, "line": int(child.lineno)})
            edges.append({"from": rel, "to": symbol_id, "kind": "defines"})
        elif isinstance(child, ast.Import):
            for alias in child.names:
                imported = alias.name
                local = alias.asname or imported.split(".")[0]
                imports[local] = imported
                edges.append({"from": rel, "to": imported, "kind": "imports"})
        elif isinstance(child, ast.ImportFrom):
            module = "." * int(child.level or 0) + str(child.module or "")
            for alias in child.names:
                imported = f"{module}.{alias.name}".strip(".")
                imports[alias.asname or alias.name] = imported
                edges.append({"from": rel, "to": imported, "kind": "imports"})
    for owner in [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        owner_id = local_symbols.get(owner.name)
        if not owner_id:
            continue
        for call in [node for node in ast.walk(owner) if isinstance(node, ast.Call)]:
            target = _call_target(call.func)
            if not target:
                continue
            if target in local_symbols:
                edges.append({"from": owner_id, "to": local_symbols[target], "kind": "calls"})
            elif target.split(".", 1)[0] in imports:
                imported = imports[target.split(".", 1)[0]]
                suffix = target.split(".", 1)[1:] or [""]
                call_target = ".".join([imported, *[item for item in suffix if item]]).strip(".")
                edges.append({"from": owner_id, "to": call_target, "kind": "calls"})
    return {"nodes": nodes, "edges": _dedupe_edges(edges)}


def _hotspots(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    node_kinds = {str(node["id"]): str(node.get("kind") or "") for node in nodes}
    scores: dict[str, dict[str, int]] = {node_id: {"incoming": 0, "outgoing": 0} for node_id in node_kinds}
    for edge in edges:
        source = str(edge["from"])
        target = str(edge["to"])
        if source in scores:
            scores[source]["outgoing"] += 1
        if target in scores:
            scores[target]["incoming"] += 1
    rows = []
    for node_id, counts in scores.items():
        degree = counts["incoming"] + counts["outgoing"]
        if degree:
            rows.append({"id": node_id, "kind": node_kinds.get(node_id, ""), "incoming": counts["incoming"], "outgoing": counts["outgoing"], "degree": degree})
    kind_priority = {"function": 0, "class": 1, "file": 2}
    return sorted(rows, key=lambda row: (-row["degree"], -row["incoming"], kind_priority.get(str(row["kind"]), 9), row["id"]))[:limit]


def _call_target(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = _call_target(func.value)
        return f"{base}.{func.attr}" if base else func.attr
    return ""


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        key = (str(edge["from"]), str(edge["to"]), str(edge["kind"]))
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return sorted(result, key=lambda edge: (str(edge["kind"]), str(edge["from"]), str(edge["to"])))


def _is_test_path(parts: tuple[str, ...], name: str) -> bool:
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")
