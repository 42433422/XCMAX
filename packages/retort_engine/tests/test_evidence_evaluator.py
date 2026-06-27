from __future__ import annotations

from pathlib import Path

from retort_engine.evaluators import EvidenceProjectEvaluator


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_focused_tool_package(root: Path) -> None:
    write_file(root / "pyproject.toml", "[project]\nname='demo-tool'\n[project.scripts]\ndemo-tool='demo_tool.cli:main'\n")
    write_file(root / "README.md", "# Demo Tool\n")
    write_file(root / "Makefile", "test:\n\tpython -m pytest tests -q\n")
    write_file(root / ".github" / "workflows" / "test.yml", "name: test\n")
    write_file(root / "docs" / "evolution_protocol.md", "# Protocol\n")
    write_file(root / "demo_tool" / "__init__.py", "")
    write_file(root / "demo_tool" / "models.py", "class Result:\n    def to_dict(self):\n        return {}\n")
    write_file(root / "demo_tool" / "self_evolution.py", "class TaskBacklogImprover: pass\n")
    write_file(root / "demo_tool" / "prompts.py", "PROMPT = 'scores_repeated_without_convergence'\n")
    write_file(root / "demo_tool" / "cli.py", "def main(): return 0\n")
    write_file(root / "demo_tool" / "extra.py", "VALUE = 1\n")
    write_file(root / "tests" / "test_demo.py", "\n".join(f"def test_{i}(): pass" for i in range(7)))


def create_incomplete_package(root: Path) -> None:
    write_file(root / "README.md", "# Incomplete\n")
    write_file(root / "demo_tool" / "__init__.py", "")


def test_focused_tool_package_returns_evidence_without_scores(tmp_path: Path) -> None:
    create_focused_tool_package(tmp_path)
    assessment = EvidenceProjectEvaluator().evaluate({"project_path": str(tmp_path), "context_policy": "provided", "allow_dirty": True, "gate_results": {"lint": True, "test": True}})
    assert assessment.scores == ()
    assert assessment.metadata["score_authority"] == "paibi_llm_prompt_only"
    assert assessment.metadata["signals"]["gate_results"] == {"lint": True, "test": True}


def test_isolated_mode_ignores_supplied_context(tmp_path: Path) -> None:
    create_incomplete_package(tmp_path)
    assessment = EvidenceProjectEvaluator().evaluate({"project_path": str(tmp_path), "gate_results": {"lint": True, "test": True}, "allow_dirty": True, "prompt": "great"})
    assert assessment.scores == ()
    assert assessment.metadata["signals"]["gate_results"] == {}
