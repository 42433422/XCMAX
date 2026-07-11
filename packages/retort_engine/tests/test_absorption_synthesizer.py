from pathlib import Path

from retort_engine.absorption_synthesizer import synthesize_behavior_absorption


def test_synthesize_behavior_absorption_writes_behavior_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    external = tmp_path / "external"
    (project / "retort_engine").mkdir(parents=True)
    (project / "tests").mkdir(parents=True)
    (external / "pkg").mkdir(parents=True)
    (project / "retort_engine" / "core.py").write_text("def absorb():\n    return 1\n", encoding="utf-8")
    (external / "pkg" / "agent.py").write_text("def agent_loop():\n    return 1\n", encoding="utf-8")
    result = synthesize_behavior_absorption(
        project,
        source="https://github.com/example/frontier",
        external_path=external,
        tasks=[{"dimension": "bounded_execution", "task_id": "t1"}],
        run_id="synth-1",
    )
    assert result["status"] == "synthesized"
    assert (project / "retort_engine" / "absorbed_behavior_bridge.py").is_file()
    assert (project / "tests" / "test_absorbed_behavior_bridge.py").is_file()
    assert "retort_engine/absorbed_behavior_bridge.py" in result["behavior_source_files"]
