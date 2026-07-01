from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def code_graph_proof_path(root: Path, run_id: str) -> Path:
    return root / "docs" / f"retort_code_graph_proof_{run_id}.json"


def has_graph_parseable_code(root: Path, path: Path) -> bool:
    rel = _project_relative(root, path)
    if rel.startswith(".retort/"):
        return False
    if path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return False
    text = _read(path)
    return bool(text.strip())


def build_code_graph_proof(root: Path, run_id: str, source: str, external_path: Path, changed_files: list[Path]) -> dict[str, Any]:
    node_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    for source_path in changed_files:
        if not source_path.is_file():
            continue
        node_path = _project_relative(root, source_path)
        if node_path not in node_map:
            node_map[node_path] = {"path": node_path, "language": _file_language(source_path), "line_count": _line_count(source_path), "imports": []}
            seen_nodes.add(node_path)
        source_node = node_map[node_path]
        for edge in _extract_import_edges(root, source_path):
            edge_key = (node_path, edge["target"], edge["edge_type"])
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edge_record = {
                "source": node_path,
                "target": edge["target"],
                "edge_type": edge["edge_type"],
                "raw": edge["raw"],
                "target_is_local": edge["target_is_local"],
                "target_kind": edge["target_kind"],
            }
            edges.append(edge_record)
            if edge["target_is_local"]:
                target_path = edge["target"]
                if target_path not in seen_nodes:
                    target_file = (root / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path)
                    node_map[target_path] = {
                        "path": target_path,
                        "language": _file_language(target_file),
                        "line_count": _line_count(target_file) if target_file.is_file() else 0,
                        "imports": [],
                    }
                    seen_nodes.add(target_path)
            if edge["raw"] not in source_node["imports"]:
                source_node["imports"].append(edge["raw"])
                if len(source_node["imports"]) > 20:
                    source_node["imports"] = source_node["imports"][:20]
    nodes = sorted(node_map.values(), key=lambda item: item["path"])
    return {
        "run_id": run_id,
        "source": source,
        "external_path": str(external_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nodes": nodes,
        "edges": edges,
        "changed_files": [_project_relative(root, item) for item in changed_files],
        "language_distribution": _build_graph_language_distribution(changed_files),
        "changed_file_count": len(changed_files),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _build_graph_language_distribution(changed_files: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in changed_files:
        if not path.is_file():
            continue
        language = _file_language(path)
        counts[language] = counts.get(language, 0) + 1
    return counts


def _file_language(path: Path) -> str:
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
    }
    return mapping.get(path.suffix.lower(), "text")


def _extract_import_edges(root: Path, path: Path) -> list[dict[str, Any]]:
    text = _read(path)
    if not text:
        return []
    if path.suffix.lower() == ".py":
        return _extract_python_import_edges(root, path, text)
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        return _extract_node_import_edges(root, path, text)
    return []


def _extract_python_import_edges(root: Path, source_path: Path, text: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                edges.extend(_normalize_python_import(root, source_path, item.name, item.asname, 0, raw=f"import {item.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module is None and node.level <= 0:
                continue
            module_name = node.module or ""
            if node.level == 0:
                edges.extend(_normalize_python_import(root, source_path, module_name, None, node.level, raw=f"from {module_name or '*'} import ..."))
            else:
                for alias in node.names:
                    alias_name = alias.name
                    if node.module:
                        target_name = f"{node.module}.{alias_name}" if alias_name != "*" else node.module
                    else:
                        target_name = alias_name
                    edges.extend(_normalize_python_import(root, source_path, target_name, alias.asname, node.level, raw=f"from {('.' * node.level)}{node.module or ''} import {alias_name}"))
    return edges


def _extract_node_import_edges(root: Path, source_path: Path, text: str) -> list[dict[str, Any]]:
    patterns = [
        re.compile(r"""(?mx)^\s*import\s+(?:[^'";]*?from\s+)?['\"](?P<spec>[^'"]+)['\"]"""),
        re.compile(r"""\brequire\s*\(\s*['"](?P<spec>[^'"]+)['"]\s*\)"""),
        re.compile(r"""(?mx)^\s*import\s*\(\s*['"](?P<spec>[^'"]+)['"]\s*\)"""),
    ]
    edges: list[dict[str, Any]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            spec = str(match.group("spec") or "")
            edges.extend(_normalize_node_import(root, source_path, spec, raw=match.group(0)))
    return edges


def _normalize_python_import(root: Path, source_file: Path, module_name: str, alias: str | None, level: int, raw: str) -> list[dict[str, Any]]:
    if not module_name and not alias:
        return []
    target = _resolve_python_import_target(root, source_file, module_name, level)
    if target:
        return [{"target": target, "target_kind": "local_python", "target_is_local": True, "edge_type": "import", "raw": raw}]
    cleaned = module_name or ""
    if alias:
        cleaned = f"{cleaned} as {alias}" if alias else cleaned
    return [{"target": cleaned, "target_kind": "external_or_unresolved", "target_is_local": False, "edge_type": "import", "raw": raw}]


def _normalize_node_import(root: Path, source_file: Path, spec: str, raw: str) -> list[dict[str, Any]]:
    spec = spec.strip()
    if not spec or spec in {"react", "react-dom"}:
        return []
    target = _resolve_node_import_target(root, source_file, spec)
    if target:
        return [{"target": target, "target_kind": "local_node", "target_is_local": True, "edge_type": "import", "raw": raw}]
    return [{"target": spec, "target_kind": "external_or_unresolved", "target_is_local": False, "edge_type": "import", "raw": raw}]


def _resolve_python_import_target(root: Path, source_file: Path, module_name: str, level: int) -> str:
    module_name = module_name.strip()
    if not module_name and level <= 0:
        return ""
    candidate_parts = [part for part in module_name.split(".") if part]
    if not candidate_parts and level > 0:
        candidate = source_file.parent
    elif level > 0:
        base_dir = source_file.parent
        for _ in range(level):
            parent = base_dir.parent
            if parent == base_dir:
                return ""
            base_dir = parent
        candidate = base_dir.joinpath(*candidate_parts) if candidate_parts else base_dir
    else:
        candidate = root.joinpath(*candidate_parts)
    return _pick_python_module_path(root, candidate) or ""


def _resolve_node_import_target(root: Path, source_file: Path, spec: str) -> str:
    if not spec:
        return ""
    if spec.startswith("."):
        candidate = (source_file.parent / spec).expanduser()
        resolved = _pick_node_module_path(root, candidate)
        if resolved:
            return resolved
    return ""


def _pick_python_module_path(root: Path, candidate: Path) -> str:
    if candidate.exists() and candidate.is_file():
        try:
            return _project_relative(root, candidate)
        except OSError:
            return ""
    if candidate.with_suffix(".py").is_file():
        return _project_relative(root, candidate.with_suffix(".py"))
    if candidate.is_dir():
        init_file = candidate / "__init__.py"
        if init_file.is_file():
            return _project_relative(root, init_file)
    direct = candidate.with_suffix("")
    for path in (direct.with_suffix(ext) for ext in (".py",)):
        if path.is_file():
            return _project_relative(root, path)
    return ""


def _pick_node_module_path(root: Path, candidate: Path) -> str:
    if candidate.is_file():
        return _project_relative(root, candidate)
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        direct = candidate.with_suffix(ext)
        if direct.is_file():
            return _project_relative(root, direct)
        index_file = candidate / f"index{ext}"
        if index_file.is_file():
            return _project_relative(root, index_file)
    return ""


def _project_relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except (OSError, ValueError):
        return str(path)


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
