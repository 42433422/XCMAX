from __future__ import annotations

from pathlib import Path

from retort_engine.codebase_graph import build_absorption_focus_map, build_codebase_graph, code_graph_absorption_proof


def test_codebase_graph_tracks_imports_definitions_and_calls(tmp_path: Path) -> None:
    project = tmp_path
    package = project / "retort_engine"
    package.mkdir()
    (package / "worker.py").write_text(
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "",
                "def helper():",
                "    return Path.cwd()",
                "",
                "def run():",
                "    helper()",
                "    json.dumps({'ok': True})",
            ]
        ),
        encoding="utf-8",
    )

    graph = build_codebase_graph(project)

    assert graph["status"] == "ready"
    assert graph["summary"]["file_count"] == 1
    assert graph["summary"]["define_edge_count"] == 2
    assert graph["summary"]["import_edge_count"] == 2
    assert any(edge == {"from": "retort_engine/worker.py:run", "to": "retort_engine/worker.py:helper", "kind": "calls"} for edge in graph["edges"])
    assert any(edge == {"from": "retort_engine/worker.py:run", "to": "json.dumps", "kind": "calls"} for edge in graph["edges"])
    assert "retort_engine/worker.py:run" in {item["id"] for item in graph["hotspots"]}


def test_codebase_graph_excludes_tests_until_requested(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")

    default_graph = build_codebase_graph(tmp_path)
    test_graph = build_codebase_graph(tmp_path, include_tests=True)

    assert default_graph["summary"]["file_count"] == 1
    assert test_graph["summary"]["file_count"] == 2
    assert "tests/test_app.py" not in {node["id"] for node in default_graph["nodes"]}
    assert "tests/test_app.py" in {node["id"] for node in test_graph["nodes"]}


def test_codebase_graph_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("from b import b\n\ndef a():\n    return b()\n", encoding="utf-8")

    first = build_codebase_graph(tmp_path)
    second = build_codebase_graph(tmp_path)

    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]
    assert first["hotspots"] == second["hotspots"]


def test_codebase_graph_reports_parse_errors_without_crashing(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def nope(:\n", encoding="utf-8")

    graph = build_codebase_graph(tmp_path)

    assert graph["status"] == "partial"
    assert graph["summary"]["parse_error_count"] == 1
    assert graph["evidence"]["parse_errors"][0]["path"] == "broken.py"


def test_absorption_focus_map_ranks_matching_graph_files(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    (own / "retort_engine").mkdir(parents=True)
    (external / "src").mkdir(parents=True)
    (own / "retort_engine" / "codebase_graph.py").write_text(
        "def build_codebase_graph():\n    return 'dependency graph import call hotspot architecture'\n",
        encoding="utf-8",
    )
    (own / "retort_engine" / "other.py").write_text("def other():\n    return 1\n", encoding="utf-8")
    (external / "src" / "graph.py").write_text(
        "def extract():\n    return 'codebase graph dependency graph call graph imports hotspot'\n",
        encoding="utf-8",
    )

    focus = build_absorption_focus_map(
        own,
        external,
        tasks=[{"task_id": "retort-depth-codebase-graph", "title": "Deepen codebase graph"}],
        signals=["codebase_graph"],
    )

    assert focus["status"] == "ready"
    assert "graph" in focus["focus_terms"]
    assert focus["own_focus_files"][0] == "retort_engine/codebase_graph.py"
    assert focus["external_focus_files"][0] == "src/graph.py"


def test_code_graph_absorption_proof_requires_focus_or_hotspot_hit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "retort_engine").mkdir(parents=True)
    graph_file = project / "retort_engine" / "codebase_graph.py"
    graph_file.write_text(
        "def target():\n    return 1\n\ndef caller():\n    return target()\n",
        encoding="utf-8",
    )

    proof = code_graph_absorption_proof(
        project,
        [str(graph_file)],
        {"own_focus_files": ["retort_engine/codebase_graph.py"]},
    )
    missed = code_graph_absorption_proof(project, [str(project / "tests" / "test_codebase_graph.py")], {"own_focus_files": ["retort_engine/codebase_graph.py"]})

    assert proof["passed"] is True
    assert proof["changed_focus_files"] == ["retort_engine/codebase_graph.py"]
    assert missed["passed"] is False
