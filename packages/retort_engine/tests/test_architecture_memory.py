from __future__ import annotations

import json
from pathlib import Path

from retort_engine.architecture_memory import build_architecture_record, deep_architecture_tasks, update_architecture_memory


def test_architecture_memory_accumulates_sources_and_repeated_components(tmp_path: Path) -> None:
    path = tmp_path / "retort_architecture_memory.json"
    first = build_architecture_record(
        run_id="run-aider",
        source="https://github.com/aider-ai/aider",
        external_path=tmp_path / "aider",
        profile={
            "file_count": 100,
            "git_revision": "abc",
            "signals": ["review_pipeline", "file_grouping", "benchmarking"],
            "signal_evidence": {"review_pipeline": ["README.md"], "file_grouping": ["aider/repomap.py"], "benchmarking": ["benchmark.py"]},
        },
        review_report={"review_pipeline": {"depth_absorption_workflow": {"focused_components": [{"component": "review_pipeline", "source_files": ["README.md"]}]}}},
        tasks=[{"dimension": "comparative_analysis_depth"}],
        changed_files=["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
        gates=[{"ok": True}],
    )
    second = build_architecture_record(
        run_id="run-openhands",
        source="https://github.com/OpenHands/software-agent-sdk",
        external_path=tmp_path / "sdk",
        profile={
            "file_count": 80,
            "git_revision": "def",
            "signals": ["review_pipeline", "benchmarking", "multi_provider"],
            "signal_evidence": {"review_pipeline": ["README.md"], "benchmarking": ["eval.py"], "multi_provider": ["provider.py"]},
        },
        review_report={"review_pipeline": {"depth_absorption_workflow": {"focused_components": [{"component": "review_pipeline", "source_files": ["README.md"]}]}}},
        tasks=[{"dimension": "architecture_depth"}],
        changed_files=["retort_engine/architecture_memory.py", "tests/test_architecture_memory.py"],
        gates=[{"ok": True}],
    )

    memory = update_architecture_memory(path, first)
    memory = update_architecture_memory(path, second)

    assert path.is_file()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["summary"]["source_count"] == 2
    assert persisted["summary"]["repeated_component_count"] >= 1
    assert persisted["component_index"]["review_pipeline"]["source_count"] == 2
    assert deep_architecture_tasks(memory)


def test_architecture_memory_marks_three_source_components_ready(tmp_path: Path) -> None:
    path = tmp_path / "retort_architecture_memory.json"
    for index, source in enumerate(["https://github.com/aider-ai/aider", "https://github.com/SWE-agent/mini-swe-agent", "https://github.com/OpenHands/software-agent-sdk"]):
        record = build_architecture_record(
            run_id=f"run-{index}",
            source=source,
            external_path=tmp_path / str(index),
            profile={"file_count": 20, "signals": ["review_pipeline"], "signal_evidence": {"review_pipeline": ["README.md"]}},
            review_report={"review_pipeline": {"depth_absorption_workflow": {"focused_components": [{"component": "review_pipeline", "source_files": ["README.md"]}]}}},
            tasks=[{"dimension": "architecture_depth"}],
            changed_files=["retort_engine/review_context_bias.py", "tests/test_review_context_bias.py"],
            gates=[{"ok": True}],
        )
        memory = update_architecture_memory(path, record)

    assert memory["component_index"]["review_pipeline"]["ready_for_deep_refactor"] is True
    assert "review_pipeline" in memory["summary"]["ready_components"]
    assert any(task["priority"] == "P0" for task in memory["deep_architecture_tasks"])
