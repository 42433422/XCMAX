from __future__ import annotations

from pathlib import Path
from typing import Any

from retort_engine.project_assessment import AssessmentDependencies, assess_project, project_files


def test_project_assessment_collects_structured_evidence_without_local_scores(tmp_path: Path) -> None:
    frontend = tmp_path / "retort_engine" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text(
        """
        <canvas id="blackholeCanvas" data-visual="blackhole-accretion-field"></canvas>
        <div id="deepProgress"></div><div id="progressFill"></div><div id="progressSteps"></div>
        <div id="eventList"></div><div id="sessionState"></div><div id="proofPanel"></div>
        <script src="/app.js"></script>
        """,
        encoding="utf-8",
    )
    (frontend / "app.js").write_text(
        """
        const ctx = canvas.getContext("2d");
        function drawAbsorptionScene() {}
        function drawAbsorptionPlanet() {}
        function renderDevourSession() {}
        function beginAbsorption() {}
        function draw() { requestAnimationFrame(draw); }
        """,
        encoding="utf-8",
    )
    (tmp_path / "retort_engine" / "service.py").write_text("class RetortService: pass\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_demo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def proof(_: Path) -> dict[str, Any]:
        return {"verified": True, "missing": (), "flags": {}, "evidence": []}

    assessment = assess_project(
        str(tmp_path),
        dependencies=AssessmentDependencies(
            read_text=lambda path: path.read_text(encoding="utf-8", errors="ignore"),
            run_command=lambda _cmd, _cwd: True,
            python_command=lambda: "python",
            tracking_state=lambda _root: "tracked_clean",
            closed_loop_proof=proof,
            capability_absorption_audit=lambda _root: {"risk_level": "low", "blockers": []},
            public_absorption_state=lambda _root: {"active": False, "status": "empty"},
        ),
    )

    assert assessment.scores == ()
    assert "test_functions=1" in assessment.evidence
    assert "closed_loop_verified=True" in assessment.evidence
    assert assessment.metadata["features"]["blackhole_ui"] is True
    assert assessment.metadata["score_authority"] == "paibi_llm_prompt_only"


def test_project_files_skips_runtime_directories(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    runtime = tmp_path / ".retort"
    runtime.mkdir()
    (runtime / "state.json").write_text("{}", encoding="utf-8")

    files = project_files(tmp_path, {".retort"})

    assert [path.name for path in files] == ["keep.py"]
