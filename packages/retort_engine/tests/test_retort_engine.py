from __future__ import annotations

import subprocess
from pathlib import Path

from retort_engine.core import RetortSelfEvolutionRunner, RetortService, absorb, assess_project, record_closed_loop_proof
from retort_engine.paibi_llm import PaibiLLMClient, build_retort_paibi_prompt, request_paibi_llm_review
from retort_engine.ui_server import RetortUIServer


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def init_repo(root: Path) -> None:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "retort@example.test")
    git(root, "config", "user.name", "Retort Test")
    (root / "README.md").write_text("# own\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "init")


def test_self_evolution_stays_blocked_without_closed_loop_proof(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# project\n", encoding="utf-8")

    result = RetortSelfEvolutionRunner(max_rounds=3).run(str(project))
    scores = {s["dimension"]: s["value"] for s in result["final_assessment"]["scores"]}
    assert result["status"] == "blocked"
    assert scores["calibrated_overall"] <= 82
    assert scores["employee_execution_integration"] < 90


def test_blackhole_ui_assets_exist() -> None:
    root = RetortUIServer().static_root
    assert "blackhole" in (root / "app.js").read_text(encoding="utf-8").lower()
    assert "ownProjectFolder" in (root / "index.html").read_text(encoding="utf-8")
    assert "externalProjectFolder" in (root / "index.html").read_text(encoding="utf-8")
    assert "useLlm" in (root / "index.html").read_text(encoding="utf-8")
    assert "llmReviewBtn" in (root / "index.html").read_text(encoding="utf-8")
    assert "llmStatusBtn" in (root / "index.html").read_text(encoding="utf-8")


def test_branch_absorption_blocks_dirty_and_creates_clean_branch(tmp_path: Path) -> None:
    own = tmp_path / "own"
    init_repo(own)
    dirty = own / "dirty.txt"
    dirty.write_text("dirty\n", encoding="utf-8")
    blocked = absorb({"own_project": str(own), "external_path": str(tmp_path), "branch_workflow": True})
    assert blocked["status"] == "blocked_by_branch_workflow"
    dirty.unlink()
    clean = absorb({"own_project": str(own), "external_path": str(tmp_path), "branch_workflow": True, "absorption_branch": "retort/absorb-test"})
    assert clean["branch_workflow"]["created"] is True
    assert git(own, "branch", "--show-current") == "retort/absorb-test"


def test_assessment_cannot_exceed_90_without_closed_loop_proof(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# project\n", encoding="utf-8")

    assessment = assess_project(str(project))
    scores = assessment.score_map()
    assert not assessment.all_scores_over(90)
    assert scores["calibrated_overall"] <= 82


def test_real_executor_features_can_converge_after_closed_loop_proof(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "engine.py").write_text(
        '"""'
        + "\n".join(
            [
                "RetortService RetortUIServer",
                "RetortSelfEvolutionRunner scores_repeated_without_convergence",
                "begin_absorption_branch merge_absorption_branch branch_workflow",
                "employee_queue RetortHistory",
                "github_url external_path ownProjectFolder externalProjectFolder",
                "license incompatible",
                "blackhole accretion canvas",
                "apply_real_absorption apply-absorption execution_requests",
                "_record_execution_proof closed_loop_proof gates_passed",
                "https://github.com/openai/codex",
            ]
        )
        + '"""\n',
        encoding="utf-8",
    )
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_engine.py").write_text("\n".join(f"def test_ok_{index}():\n    assert True\n" for index in range(25)), encoding="utf-8")
    workflow = project / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "retort-engine.yml").write_text("name: retort\n", encoding="utf-8")
    record_closed_loop_proof(
        str(project),
        {
            "branch_diff_verified": True,
            "employee_execution_verified": True,
            "post_absorption_tests_passed": True,
            "merge_verified": True,
            "external_advantage_reassessed": True,
            "evidence": ["unit proof"],
        },
    )

    result = RetortSelfEvolutionRunner(max_rounds=3).run(str(project), run_local_gates=True)
    scores = {s["dimension"]: s["value"] for s in result["final_assessment"]["scores"]}
    assert result["status"] == "converged"
    assert scores["architecture_depth"] > 90
    assert scores["employee_execution_integration"] > 90


def test_absorption_shock_drops_score_then_self_evolution_recovers(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    own.mkdir()
    external.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    (external / "README.md").write_text(
        "code review pipeline with changed files, benchmark precision, plugin cli, localization, reflection\n",
        encoding="utf-8",
    )

    before = assess_project(str(own))
    result = absorb({"own_project": str(own), "external_path": str(external)})
    after_scores = {score["dimension"]: score["value"] for score in result["own_assessment"]["scores"]}
    before_scores = before.score_map()

    assert result["absorption_state"]["active"] is True
    assert result["external_assessment"]["project"] == str(external.resolve())
    assert result["external_assessment"]["scores"]
    assert result["absorption_visual"]["external"]["file_count"] == 1
    assert result["absorption_visual"]["external"]["score"] is not None
    assert result["absorption_visual"]["own"]["pre_score"] == before_scores["calibrated_overall"]
    assert after_scores["calibrated_overall"] < before_scores["calibrated_overall"]
    assert after_scores["calibrated_overall"] <= 90

    evolved = RetortSelfEvolutionRunner(max_rounds=3).run(str(own))
    final_scores = {score["dimension"]: score["value"] for score in evolved["final_assessment"]["scores"]}

    assert evolved["status"] == "blocked"
    assert final_scores["calibrated_overall"] <= 82
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["active"] is True
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["status"] == "awaiting_execution_evidence"


def test_absorption_executes_cli_and_writes_project_code(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    own.mkdir()
    external.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    (external / "README.md").write_text("code review pipeline changed files benchmark plugin cli\n", encoding="utf-8")

    result = absorb({"own_project": str(own), "external_path": str(external), "execution_timeout_sec": 30})

    execution = result["execution"]
    assert result["status"] == "absorption_execution_applied"
    assert execution["status"] == "applied"
    assert execution["gates_passed"] is True
    assert str(own / "retort_absorbed_patterns.py") in execution["changed_files"]
    assert str(own / "docs" / "retort_absorption_log.md") in execution["changed_files"]
    proof = result["absorption_state"]["closed_loop_proof"]["flags"]
    assert proof["branch_diff_verified"] is True
    assert proof["employee_execution_verified"] is True
    assert proof["post_absorption_tests_passed"] is True
    assert proof["merge_verified"] is False


def test_external_assessment_counts_files_inside_retort_cache(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = own / ".retort" / "cache" / "github" / "owner" / "repo"
    own.mkdir()
    external.mkdir(parents=True)
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    (external / "README.md").write_text("# External\ncode review benchmark plugin\n", encoding="utf-8")

    result = absorb({"own_project": str(own), "external_path": str(external)})

    assert result["external_assessment"]["evidence"][0] == "source_files=1"
    assert result["absorption_visual"]["external"]["file_count"] == 1


def test_record_closed_loop_proof_is_required_for_verified_state(tmp_path: Path) -> None:
    own = tmp_path / "own"
    own.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    absorb({"own_project": str(own), "external_path": str(tmp_path)})

    partial = record_closed_loop_proof(str(own), {"branch_diff_verified": True})
    assert partial["status"] == "awaiting_execution_evidence"
    assert partial["closed_loop_proof"]["verified"] is False

    full = record_closed_loop_proof(
        str(own),
        {
            "branch_diff_verified": True,
            "employee_execution_verified": True,
            "post_absorption_tests_passed": True,
            "merge_verified": True,
            "external_advantage_reassessed": True,
            "evidence": ["unit proof"],
        },
    )
    assert full["status"] == "closed_loop_verified"
    assert full["closed_loop_proof"]["verified"] is True


def test_paibi_llm_review_writes_outbox_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RETORT_PAIBI_API_URL", "disabled")
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    result = request_paibi_llm_review(project=str(project), mode="assess", scores=[{"dimension": "calibrated_overall", "value": 82}], tasks=[])

    assert result["provider"] == "paibi"
    assert result["dispatch"]["status"] == "queued_outbox"
    assert (project / ".retort" / "paibi_llm_outbox.jsonl").is_file()


def test_paibi_prompt_keeps_closed_loop_score_cap(tmp_path: Path) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    prompt = build_retort_paibi_prompt(project=project, mode="manual", scores=[], tasks=[])

    assert "排比 Para/Codex" in prompt
    assert "不得超过 82" in prompt
    assert "严格 JSON" in prompt
    assert "规则评分已经转成" in prompt
    assert '"scores"' in prompt


def test_service_llm_review_uses_paibi_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RETORT_PAIBI_API_URL", "disabled")
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    result = RetortService().llm_review({"project": str(project), "mode": "manual"})

    assert result["provider"] == "paibi"
    assert result["dispatch"]["dispatcher"] == "paibi_outbox"


def test_service_llm_review_status_parses_paibi_logs(monkeypatch) -> None:
    def fake_fetch_task(self: PaibiLLMClient, task_id: str) -> dict[str, object]:
        return {
            "task": {
                "id": task_id,
                "status": "completed",
                "subTasks": [
                    {
                        "id": "sub-1",
                        "status": "completed",
                        "progress": 100,
                        "device_name": "codex-device",
                        "branch_name": "devfleet/codex/sub-1",
                        "logs": [{"content": 'prefix {"level":"usable","score_suggestion":81}'}],
                    }
                ],
            }
        }

    monkeypatch.setattr(PaibiLLMClient, "fetch_task", fake_fetch_task)

    result = RetortService().llm_review_status({"task_id": "task-1"})

    assert result["status"] == "completed"
    assert result["json_result"]["score_suggestion"] == 81
    assert result["scores"][0]["dimension"] == "calibrated_overall"
    assert result["subtasks"][0]["status"] == "completed"


def test_service_assess_uses_llm_scores_when_wait_returns_json(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    def fake_request(**kwargs) -> dict[str, object]:
        return {"provider": "paibi", "enabled": True, "status": "accepted", "dispatch": {"task_id": "task-llm"}}

    def fake_wait(task_id: str, *, timeout_sec: float, interval_sec: float = 5.0) -> dict[str, object]:
        return {
            "provider": "paibi",
            "task_id": task_id,
            "status": "completed",
            "json_result": {"level": "usable", "score_suggestion": 79},
            "scores": [
                {"dimension": "calibrated_overall", "value": 79, "reason": "LLM saw missing closed-loop proof.", "evidence": ["no closed-loop proof"]},
                {"dimension": "employee_execution_integration", "value": 70, "reason": "No employee execution proof.", "evidence": []},
            ],
        }

    monkeypatch.setattr("retort_engine.core.request_paibi_llm_review", fake_request)
    monkeypatch.setattr("retort_engine.core.wait_for_paibi_llm_review", fake_wait)

    result = RetortService().assess({"project": str(project), "use_llm": True, "wait_llm_sec": 1})

    scores = {item["dimension"]: item["value"] for item in result["scores"]}
    assert result["metadata"]["score_source"] == "paibi_llm"
    assert result["metadata"]["fallback_rule_scores"]
    assert scores["calibrated_overall"] == 79
    assert scores["employee_execution_integration"] == 70
