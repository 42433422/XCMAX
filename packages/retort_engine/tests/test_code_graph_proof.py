from __future__ import annotations

from pathlib import Path

from retort_engine.code_graph_proof import build_code_graph_proof, code_graph_proof_path, has_graph_parseable_code


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_code_graph_proof_links_local_python_and_node_imports(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write(root / "pkg" / "__init__.py", "")
    _write(root / "pkg" / "helpers.py", "VALUE = 1\n")
    _write(root / "pkg" / "main.py", "import pkg.helpers\nimport json\n")
    _write(root / "web" / "view.ts", "import { draw } from './draw'\n")
    _write(root / "web" / "draw.ts", "export function draw() {}\n")

    proof = build_code_graph_proof(
        root,
        "run-1",
        "https://github.com/example/project",
        root / ".retort" / "cache" / "github" / "example" / "project",
        [root / "pkg" / "main.py", root / "web" / "view.ts"],
    )

    edges = {(edge["source"], edge["target"], edge["target_is_local"]) for edge in proof["edges"]}
    assert ("pkg/main.py", "pkg/helpers.py", True) in edges
    assert ("pkg/main.py", "json", False) in edges
    assert ("web/view.ts", "web/draw.ts", True) in edges
    assert proof["language_distribution"] == {"python": 1, "typescript": 1}
    assert proof["node_count"] >= 4


def test_code_graph_parseable_filter_excludes_retort_cache_and_empty_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write(root / "src" / "main.py", "print('ok')\n")
    _write(root / "src" / "empty.py", "")
    _write(root / ".retort" / "cache" / "tmp.py", "print('skip')\n")

    assert has_graph_parseable_code(root, root / "src" / "main.py") is True
    assert has_graph_parseable_code(root, root / "src" / "empty.py") is False
    assert has_graph_parseable_code(root, root / ".retort" / "cache" / "tmp.py") is False
    assert code_graph_proof_path(root, "abc").name == "retort_code_graph_proof_abc.json"
