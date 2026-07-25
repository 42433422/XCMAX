from pathlib import Path

from retort_engine.real_absorption import apply_real_absorption
from retort_engine.workspace_hygiene import (
    clean_workspace,
    close_run_workspace,
    workspace_residue_report,
)


def test_clean_workspace_removes_ephemeral_residue_keeps_durable_state(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / ".retort"
    (runtime / "cache" / "github" / "o" / "r").mkdir(parents=True)
    (runtime / "cache" / "github" / "o" / "r" / "README.md").write_text(
        "x", encoding="utf-8"
    )
    (runtime / "trajectories").mkdir()
    (runtime / "trajectories" / "t.json").write_text("{}", encoding="utf-8")
    (runtime / "employee_results").mkdir()
    (runtime / "employee_results" / "r.json").write_text("{}", encoding="utf-8")
    (runtime / "absorption_state.json").write_text(
        '{"active": false}', encoding="utf-8"
    )
    (runtime / "employee_queue.jsonl").write_text("{}\n", encoding="utf-8")

    cleaned = clean_workspace(tmp_path)
    assert cleaned["summary"]["clean"] is True
    assert (runtime / "absorption_state.json").is_file()
    assert not (runtime / "cache").exists()
    assert not (runtime / "trajectories").exists()
    assert not (runtime / "employee_results").exists()
    assert not (runtime / "employee_queue.jsonl").exists()


def test_apply_real_absorption_closes_workspace_by_default(tmp_path: Path) -> None:
    import sys

    project = tmp_path / "own"
    external = tmp_path / "external"
    (project / "retort_engine").mkdir(parents=True)
    (project / "retort_engine" / "__init__.py").write_text("", encoding="utf-8")
    external.mkdir()
    (external / "README.md").write_text(
        "review pipeline changed files benchmark\n", encoding="utf-8"
    )

    result = apply_real_absorption(
        {
            "own_project": str(project),
            "external_path": str(external),
            "source": "hygiene-source",
            "tasks": [
                {
                    "task_id": "t1",
                    "title": "Absorb",
                    "dimension": "comparative_analysis_depth",
                    "priority": "P1",
                }
            ],
            "python": sys.executable,
        }
    )

    assert result["workspace_closure"]["summary"]["closed"] is True
    residue = workspace_residue_report(project)
    assert residue["clean"] is True
    assert not (project / ".retort" / "cache").exists()
    assert not (project / ".retort" / "employee_results").exists()
    assert not (project / ".retort" / "real_absorption_runs").exists()


def test_close_run_workspace_reports_closed_status(tmp_path: Path) -> None:
    (tmp_path / ".retort" / "trajectories").mkdir(parents=True)
    (tmp_path / ".retort" / "trajectories" / "x.json").write_text(
        "{}", encoding="utf-8"
    )
    closure = close_run_workspace(tmp_path, run_id="r1")
    assert closure["status"] == "closed"
    assert closure["summary"]["closed"] is True
