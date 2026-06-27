from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SemanticFinding:
    kind: str
    detail: str

    def to_text(self) -> str:
        return f"{self.kind}: {self.detail}"


def semantic_compare(own_project: str | Path, external_project: str | Path) -> tuple[SemanticFinding, ...]:
    own = _profile_python_project(Path(own_project))
    external = _profile_python_project(Path(external_project))
    findings: list[SemanticFinding] = []
    for key, label in (("classes", "domain modeling depth"), ("functions", "functional decomposition"), ("cli_entries", "operator command surface"), ("api_routes", "service API surface"), ("async_functions", "async workflow depth")):
        gap = external[key] - own[key]
        if gap > 0:
            findings.append(SemanticFinding(label, f"external has +{gap} {key.replace('_', ' ')}"))
    return tuple(findings)


def _profile_python_project(root: Path) -> dict[str, int]:
    profile = {"classes": 0, "functions": 0, "cli_entries": 0, "api_routes": 0, "async_functions": 0}
    for path in root.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "build", "dist"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                profile["classes"] += 1
            elif isinstance(node, ast.AsyncFunctionDef):
                profile["functions"] += 1
                profile["async_functions"] += 1
            elif isinstance(node, ast.FunctionDef):
                profile["functions"] += 1
        profile["cli_entries"] += text.count("add_parser(") + text.count("[project.scripts]")
        profile["api_routes"] += text.count("@app.") + text.count("APIRouter") + text.count("FastAPI(")
    return profile
