from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


DEFAULT_SUFFIXES = (".py",)
SKIP_DIRS = {".git", ".hg", ".mypy_cache", ".pytest_cache", ".retort", "__pycache__", "node_modules", "dist", "build"}
SIGNAL_FOCUS_TERMS = {
    "review_pipeline": ("review", "pipeline", "comment", "localization", "reflection"),
    "file_grouping": ("group", "context", "related", "changed", "files"),
    "diff_hunk_review": ("diff", "hunk", "patch", "line", "comment"),
    "benchmarking": ("benchmark", "eval", "precision", "oracle", "regression"),
    "benchmark_eval": ("benchmark", "eval", "precision", "oracle", "regression"),
    "workflow_ci": ("gate", "pytest", "workflow", "merge", "proof"),
    "safety_policy": ("license", "policy", "permission", "rollback", "secret"),
    "codebase_graph": ("codebase", "graph", "dependency", "import", "call", "hotspot", "architecture"),
}


def build_codebase_graph(project: str | Path, *, include_tests: bool = False, max_files: int = 400) -> dict[str, Any]:
    """Build a deterministic source graph for architecture and absorption targeting."""
    root = Path(project).resolve()
    files = _source_files(root, include_tests=include_tests, max_files=max_files)
    module_index = _module_index(root, files)
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
    edges = _dedupe_edges([*edges, *_local_dependency_edges(module_index, edges)])
    dependency_cycles = _dependency_cycles(edges)
    hotspots = _hotspots(nodes, edges)
    summary = {
        "file_count": len(files),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "import_edge_count": sum(1 for edge in edges if edge["kind"] == "imports"),
        "local_dependency_edge_count": sum(1 for edge in edges if edge["kind"] == "depends_on"),
        "dependency_cycle_count": len(dependency_cycles),
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
        "dependency_cycles": dependency_cycles,
        "evidence": {
            "style": "deterministic_codebase_graph",
            "source": "codegraph_absorption",
            "parse_errors": parse_errors,
        },
    }


def build_absorption_focus_map(
    own_project: str | Path,
    external_project: str | Path,
    *,
    tasks: list[dict[str, Any]] | None = None,
    signals: list[str] | None = None,
    max_files: int = 400,
) -> dict[str, Any]:
    """Use code graphs to decide where deep absorption should spend attention."""
    own_root = Path(own_project).resolve()
    external_root = Path(external_project).resolve()
    own_graph = build_codebase_graph(own_root, include_tests=True, max_files=max_files)
    external_graph = build_codebase_graph(external_root, include_tests=True, max_files=max_files)
    terms = _focus_terms(tasks or [], signals or [])
    own_focus = _rank_focus_files(own_root, own_graph, terms)
    external_focus = _rank_focus_files(external_root, external_graph, terms)
    own_hotspots = _hotspot_rows(own_graph)
    external_hotspots = _hotspot_rows(external_graph)
    return {
        "status": "ready" if own_graph["status"] != "empty" and external_graph["status"] != "empty" else "empty",
        "focus_terms": terms,
        "own_summary": own_graph["summary"],
        "external_summary": external_graph["summary"],
        "own_focus_files": [row["path"] for row in own_focus],
        "external_focus_files": [row["path"] for row in external_focus],
        "own_focus": own_focus,
        "external_focus": external_focus,
        "own_hotspots": own_hotspots,
        "external_hotspots": external_hotspots,
        "evidence": {
            "style": "deterministic_pre_absorption_code_graph",
            "own_project": str(own_root),
            "external_project": str(external_root),
            "max_files": max_files,
        },
    }


def code_graph_absorption_proof(project: str | Path, changed_files: list[str], pre_absorption_focus: dict[str, Any] | None = None, *, max_files: int = 400) -> dict[str, Any]:
    """Prove whether an absorption changed code graph hotspots or preselected focus files."""
    root = Path(project).resolve()
    graph = build_codebase_graph(root, include_tests=True, max_files=max_files)
    changed = _relative_changed_files(root, changed_files)
    hotspot_files = {row["path"] for row in _hotspot_rows(graph, limit=24)}
    focus_files = {str(item) for item in (pre_absorption_focus or {}).get("own_focus_files") or []}
    behavior_changed = [path for path in changed if _is_behavior_change(path)]
    changed_hotspots = sorted(path for path in behavior_changed if path in hotspot_files)
    changed_focus_files = sorted(path for path in behavior_changed if path in focus_files)
    dependency_impact = _dependency_impact(graph, behavior_changed)
    proof_ready = bool(behavior_changed and (changed_hotspots or changed_focus_files))
    return {
        "passed": proof_ready,
        "status": "proved" if proof_ready else "not_proved",
        "changed_behavior_files": behavior_changed,
        "changed_hotspots": changed_hotspots,
        "changed_focus_files": changed_focus_files,
        "dependency_impact": dependency_impact,
        "hotspot_files": sorted(hotspot_files)[:24],
        "focus_files": sorted(focus_files)[:24],
        "summary": {
            "changed_behavior_file_count": len(behavior_changed),
            "changed_hotspot_count": len(changed_hotspots),
            "changed_focus_file_count": len(changed_focus_files),
            "dependency_impact_file_count": len(dependency_impact["impacted_files"]),
            "dependency_cycle_touch_count": len(dependency_impact["touched_cycles"]),
            "graph_status": graph["status"],
        },
        "evidence": {
            "style": "deterministic_post_absorption_code_graph",
            "project": str(root),
            "max_files": max_files,
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


def _focus_terms(tasks: list[dict[str, Any]], signals: list[str]) -> list[str]:
    terms: list[str] = []
    for signal in signals:
        terms.extend(SIGNAL_FOCUS_TERMS.get(str(signal), (str(signal), str(signal).replace("_", " "))))
    task_text = " ".join(
        " ".join(str(task.get(key) or "") for key in ("task_id", "title", "dimension", "why"))
        for task in tasks
        if isinstance(task, dict)
    ).lower()
    for signal, signal_terms in SIGNAL_FOCUS_TERMS.items():
        if signal in task_text or signal.replace("_", " ") in task_text:
            terms.extend(signal_terms)
    for token in task_text.replace("-", " ").replace("_", " ").split():
        if len(token) >= 5 and token.isascii():
            terms.append(token)
    result: list[str] = []
    for term in terms:
        normalized = str(term).lower().strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:32]


def _rank_focus_files(root: Path, graph: dict[str, Any], terms: list[str], *, limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hotspot_degree = {row["path"]: int(row["degree"]) for row in _hotspot_rows(graph, limit=64)}
    for path in _graph_file_paths(graph):
        full = root / path
        try:
            text = full.read_text(encoding="utf-8").lower()[:40000]
        except (OSError, UnicodeDecodeError):
            text = ""
        term_hits = sum(text.count(term) for term in terms)
        degree = hotspot_degree.get(path, 0)
        score = term_hits * 10 + degree
        if score <= 0:
            continue
        rows.append({"path": path, "score": score, "term_hits": term_hits, "graph_degree": degree})
    if not rows:
        rows = [{"path": row["path"], "score": int(row["degree"]), "term_hits": 0, "graph_degree": int(row["degree"])} for row in _hotspot_rows(graph, limit=limit)]
    return sorted(rows, key=lambda row: (-int(row["score"]), row["path"]))[:limit]


def _hotspot_rows(graph: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in graph.get("hotspots") or []:
        if not isinstance(item, dict):
            continue
        path = _node_path(str(item.get("id") or ""))
        if not path:
            continue
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "path": path,
                "kind": str(item.get("kind") or ""),
                "degree": int(item.get("degree") or 0),
                "incoming": int(item.get("incoming") or 0),
                "outgoing": int(item.get("outgoing") or 0),
            }
        )
    return rows[:limit]


def _graph_file_paths(graph: dict[str, Any]) -> list[str]:
    return [str(node.get("id") or "") for node in graph.get("nodes") or [] if isinstance(node, dict) and node.get("kind") == "file" and node.get("id")]


def _relative_changed_files(root: Path, changed_files: list[str]) -> list[str]:
    rows: list[str] = []
    for item in changed_files:
        text = str(item).replace("\\", "/")
        path = Path(text)
        if path.is_absolute():
            try:
                text = path.resolve().relative_to(root).as_posix()
            except ValueError:
                text = path.name
        rows.append(text)
    return sorted(dict.fromkeys(rows))


def _is_behavior_change(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name
    if "/tests/" in f"/{normalized}" or name.startswith("test_"):
        return False
    return normalized.endswith(DEFAULT_SUFFIXES)


def _node_path(node_id: str) -> str:
    return node_id.split(":", 1)[0]


def _module_index(root: Path, files: list[Path]) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = list(path.relative_to(root).with_suffix("").parts)
        if path.name == "__init__.py":
            parts = parts[:-1]
        if not parts:
            continue
        module = ".".join(parts)
        names = {module, parts[-1]}
        for index in range(1, len(parts)):
            names.add(".".join(parts[index:]))
        for name in names:
            candidates.setdefault(name, []).append(rel)
    return {name: rows[0] for name, rows in candidates.items() if len(set(rows)) == 1}


def _local_dependency_edges(module_index: dict[str, str], edges: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for edge in edges:
        if edge.get("kind") != "imports":
            continue
        source = _node_path(str(edge.get("from") or ""))
        if not source.endswith(DEFAULT_SUFFIXES):
            continue
        target = _resolve_local_module(module_index, str(edge.get("to") or ""))
        if target and target != source:
            rows.append({"from": source, "to": target, "kind": "depends_on"})
    return rows


def _resolve_local_module(module_index: dict[str, str], imported: str) -> str:
    normalized = imported.strip(".")
    if not normalized:
        return ""
    parts = normalized.split(".")
    for size in range(len(parts), 0, -1):
        candidate = ".".join(parts[:size])
        if candidate in module_index:
            return module_index[candidate]
    return ""


def _dependency_cycles(edges: list[dict[str, Any]], *, limit: int = 10) -> list[list[str]]:
    graph: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("kind") != "depends_on":
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if source and target:
            graph.setdefault(source, []).append(target)
    for source, targets in graph.items():
        graph[source] = sorted(set(targets))

    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def visit(start: str, node: str, path: list[str]) -> None:
        if len(cycles) >= limit:
            return
        for target in graph.get(node, []):
            if target == start:
                cycle = _canonical_cycle([*path, start])
                key = tuple(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif target not in path and target >= start:
                visit(start, target, [*path, target])

    for start in sorted(graph):
        visit(start, start, [start])
        if len(cycles) >= limit:
            break
    return sorted(cycles, key=lambda row: (len(row), row))[:limit]


def _canonical_cycle(cycle: list[str]) -> list[str]:
    core = cycle[:-1] if len(cycle) > 1 and cycle[0] == cycle[-1] else cycle
    if not core:
        return []
    rotations = [core[index:] + core[:index] for index in range(len(core))]
    best = min(rotations)
    return [*best, best[0]]


def _dependency_impact(graph: dict[str, Any], changed_files: list[str], *, limit: int = 24) -> dict[str, Any]:
    changed = {path for path in changed_files if path.endswith(DEFAULT_SUFFIXES)}
    dependencies: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("kind") != "depends_on":
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        if not source or not target:
            continue
        dependencies.setdefault(source, set()).add(target)
        dependents.setdefault(target, set()).add(source)
    impacted = set(changed)
    for path in changed:
        impacted.update(dependencies.get(path, set()))
        impacted.update(dependents.get(path, set()))
    touched_cycles = [
        cycle
        for cycle in graph.get("dependency_cycles") or []
        if isinstance(cycle, list) and any(str(item) in changed for item in cycle)
    ]
    return {
        "changed_files": sorted(changed),
        "impacted_files": sorted(impacted)[:limit],
        "direct_dependencies": {path: sorted(dependencies.get(path, set())) for path in sorted(changed)},
        "direct_dependents": {path: sorted(dependents.get(path, set())) for path in sorted(changed)},
        "touched_cycles": touched_cycles[:limit],
    }


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
