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


def test_self_evolution_stays_blocked_without_closed_loop_proof() -> None:
    result = RetortSelfEvolutionRunner(max_rounds=3).run("packages/retort_engine")
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


def test_assessment_cannot_exceed_90_without_closed_loop_proof() -> None:
    assessment = assess_project("packages/retort_engine")
    scores = assessment.score_map()
    assert not assessment.all_scores_over(90)
    assert scores["calibrated_overall"] <= 82


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
    assert after_scores["calibrated_overall"] < before_scores["calibrated_overall"]
    assert after_scores["calibrated_overall"] <= 90

    evolved = RetortSelfEvolutionRunner(max_rounds=3).run(str(own))
    final_scores = {score["dimension"]: score["value"] for score in evolved["final_assessment"]["scores"]}

    assert evolved["status"] == "blocked"
    assert final_scores["calibrated_overall"] <= 82
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["active"] is True
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["status"] == "awaiting_execution_evidence"


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
    assert result["subtasks"][0]["status"] == "completed"
