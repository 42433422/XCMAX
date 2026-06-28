from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from retort_engine.core import RetortSelfEvolutionRunner, RetortService, _attach_llm_scoring, _blocking_git_status, _extract_json_from_stdout, _llm_absorption_evidence, _maybe_request_llm_review, absorb, assess_project, record_closed_loop_proof
from retort_engine.core import _is_generated_absorption_file, _is_exempt_git_status_path
from retort_engine.paibi_llm import PaibiLLMClient, build_retort_paibi_prompt, fetch_paibi_parallel_review_status, request_paibi_llm_review, request_paibi_parallel_review
from retort_engine.real_absorption import apply_real_absorption
from retort_engine.ui_server import RetortUIServer
from retort_engine.ui_features import blackhole_ui_detected, blackhole_ui_structure


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

    result = RetortSelfEvolutionRunner().run(str(project))
    assert result["status"] == "blocked"
    assert result["stop_reason"] == "llm_deep_review_required"
    assert result["round_policy"] == "single_paibi_llm_deep_review"
    assert result["final_assessment"]["scores"] == []
    assert result["final_assessment"]["metadata"]["score_authority"] == "paibi_llm_prompt_only"


def test_blackhole_ui_assets_exist() -> None:
    root = RetortUIServer().static_root
    structure = blackhole_ui_structure(root.parents[1])
    assert "blackhole" in (root / "app.js").read_text(encoding="utf-8").lower()
    assert "ownProjectFolder" in (root / "index.html").read_text(encoding="utf-8")
    assert "externalProjectFolder" in (root / "index.html").read_text(encoding="utf-8")
    assert 'id="useLlm" type="checkbox" checked disabled' in (root / "index.html").read_text(encoding="utf-8")
    assert "wait_llm_sec" in (root / "app.js").read_text(encoding="utf-8")
    assert "require_deep_review" in (root / "app.js").read_text(encoding="utf-8")
    assert "beginProgress" in (root / "app.js").read_text(encoding="utf-8")
    assert "deepProgress" in (root / "index.html").read_text(encoding="utf-8")
    assert "progressFill" in (root / "index.html").read_text(encoding="utf-8")
    index_text = (root / "index.html").read_text(encoding="utf-8")
    app_text = (root / "app.js").read_text(encoding="utf-8")
    style_text = (root / "styles.css").read_text(encoding="utf-8")
    assert 'class="rail flow-panel"' in index_text
    assert 'data-step="01"' in index_text
    assert 'data-step="09"' in index_text
    assert "flow-step::before" in style_text
    assert "flow-step::after" in style_text
    assert "llmReviewBtn" not in index_text
    assert "llmParallelBtn" not in index_text
    assert "llmStatusBtn" not in index_text
    assert "function llmReview" not in app_text
    assert "function llmParallelReview" not in app_text
    assert "function llmStatus" not in app_text
    assert "function syncLlmStatus" in app_text
    assert "排比 LLM 自动同步" in app_text
    assert "use_llm: true" in app_text
    assert "require_deep_review: true" in app_text
    assert blackhole_ui_detected(root.parents[1]) is True
    assert structure["missing_ids"] == []
    assert structure["missing_functions"] == []


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


def test_branch_absorption_ignores_dirty_files_outside_selected_project(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    own = repo / "packages" / "retort"
    external = tmp_path / "external"
    own.mkdir(parents=True)
    external.mkdir()
    (own / "README.md").write_text("# Retort\n", encoding="utf-8")
    (external / "README.md").write_text("code review benchmark plugin\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add retort")
    (repo / "unrelated.txt").write_text("dirty\n", encoding="utf-8")

    result = absorb({"own_project": str(own), "external_path": str(external), "branch_workflow": True, "absorption_branch": "retort/absorb-subproject", "execute_absorption": False})

    assert result["branch_workflow"]["created"] is True
    assert git(repo, "branch", "--show-current") == "retort/absorb-subproject"


def test_assessment_cannot_exceed_90_without_closed_loop_proof(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# project\n", encoding="utf-8")

    assessment = assess_project(str(project))
    assert assessment.scores == ()
    assert assessment.metadata["score_authority"] == "paibi_llm_prompt_only"
    assert assessment.metadata["local_scores_removed"] is True


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
    run_dir = project / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "a-source.json").write_text(json.dumps({"source": "https://github.com/example/first"}), encoding="utf-8")
    (run_dir / "aa-source.json").write_text(json.dumps({"source": "https://github.com/example/second"}), encoding="utf-8")
    for index, source in enumerate(("https://github.com/a/one", "https://github.com/b/two", "https://github.com/c/three"), start=1):
        (run_dir / f"behavior-run-{index}.json").write_text(
            json.dumps(
                {
                    "source": source,
                    "changed_files": [str(project / "engine.py"), str(tests / "test_engine.py")],
                }
            ),
            encoding="utf-8",
        )
    result_dir = project / ".retort" / "employee_results"
    result_dir.mkdir(parents=True)
    (result_dir / "behavior-run.json").write_text(
        json.dumps({"execution_mode": "employee_runtime", "results": [{"task_id": "retort-absorb-depth", "status": "applied"}]}),
        encoding="utf-8",
    )
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

    result = RetortSelfEvolutionRunner().run(str(project), run_local_gates=True)
    assert result["status"] == "blocked"
    assert result["stop_reason"] == "llm_deep_review_required"
    assert result["final_assessment"]["scores"] == []


def test_absorption_collects_evidence_then_requires_llm_reassessment(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    own.mkdir()
    external.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    (external / "README.md").write_text(
        "code review pipeline with changed files, benchmark precision, plugin cli, localization, reflection\n",
        encoding="utf-8",
    )

    result = absorb({"own_project": str(own), "external_path": str(external)})

    session = result["devour_session"]
    assert session["stage_order"] == ["pre_dual_review", "overlap_comparison", "absorption_execution", "improvement_proof", "final_self_review"]
    assert [panel["role"] for panel in session["pre_dual_review"]["panels"]] == ["own_before", "external"]
    assert session["pre_dual_review"]["context_policy"] == "isolated_before_absorption"
    assert session["overlap_comparison"]["status"] == "depth_overlap_found"
    assert "comparative_analysis_depth" in session["overlap_comparison"]["overlap_dimensions"]
    assert session["improvement_proof"]["changed_file_count"] >= 1
    assert session["final_self_review"]["record_policy"] == "只有排比 LLM 返回结构化分数时，最终评分才保留。"
    assert result["absorption_state"]["active"] is True
    assert result["absorption_state"]["status"] in {"pending_llm_reassessment", "execution_applied_awaiting_merge"}
    assert result["external_assessment"]["project"] == str(external.resolve())
    assert result["external_assessment"]["scores"] == []
    assert result["absorption_visual"]["external"]["file_count"] == 1
    assert result["absorption_visual"]["external"]["score"] is None
    assert result["own_assessment"]["scores"] == []

    evolved = RetortSelfEvolutionRunner().run(str(own))

    assert evolved["status"] == "blocked"
    assert evolved["stop_reason"] == "llm_deep_review_required"
    assert evolved["final_assessment"]["scores"] == []
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["active"] is True
    assert evolved["final_assessment"]["metadata"]["absorption_state"]["status"] in {"pending_llm_reassessment", "execution_applied_awaiting_merge"}


def test_absorption_executes_cli_and_writes_project_code(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    own.mkdir()
    external.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")
    (external / "README.md").write_text("code review pipeline changed files benchmark plugin cli\n", encoding="utf-8")
    queue_path = own / ".retort" / "employee_queue.jsonl"
    history_path = own / ".retort" / "retort_history.sqlite"

    result = absorb({"own_project": str(own), "external_path": str(external), "employee_queue": str(queue_path), "history_store": str(history_path), "execution_timeout_sec": 30})

    execution = result["execution"]
    assert result["status"] == "absorption_execution_applied"
    assert execution["status"] == "applied"
    assert execution["gates_passed"] is True
    assert str(own / "retort_absorbed_patterns.py") in execution["changed_files"]
    assert str(own / "docs" / "retort_absorption_log.md") in execution["changed_files"]
    assert str(own / "docs" / "retort_external_review_report.json") in execution["changed_files"]
    assert execution["review_report_path"] == str(own / "docs" / "retort_external_review_report.json")
    assert Path(execution["employee_results_path"]).is_file()
    report = json.loads(Path(execution["review_report_path"]).read_text(encoding="utf-8"))
    assert report["absorbed_signals"]
    assert report["semantic_review"]["external"]["source_files"] >= 1
    assert report["review_pipeline"]["pipeline_stages"]
    assert report["review_pipeline"]["benchmark"]["minimum_expected_behavior_tests"] >= 3
    assert report["license_review"]["status"] in {"passed", "blocked"}
    assert execution["feedback_audit"]["closed"] is True
    assert execution["feedback_audit"]["result_tasks_have_queue_records"] is True
    proof = result["absorption_state"]["closed_loop_proof"]["flags"]
    assert proof["branch_diff_verified"] is True
    assert proof["employee_execution_verified"] is True
    assert proof["post_absorption_tests_passed"] is True
    assert proof["merge_verified"] is False


def test_assessment_ignores_retort_runtime_dirty_state(tmp_path: Path) -> None:
    own = tmp_path / "own"
    init_repo(own)
    runtime = own / ".retort" / "absorption_state.json"
    runtime.parent.mkdir()
    runtime.write_text("{}", encoding="utf-8")

    assessment = assess_project(str(own))

    assert assessment.metadata["git_tracking_state"] == "tracked_clean"


def test_capability_audit_does_not_count_registry_snapshot_as_core_behavior(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    changed_files = [
        project / "retort_engine" / "absorbed_capabilities.py",
        project / "tests" / "test_absorbed_capabilities.py",
        project / "docs" / "retort_absorption_log.md",
        project / "docs" / "retort_external_review_report.json",
    ]
    for path in changed_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# generated\n", encoding="utf-8")
    run_dir = project / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"source": "https://github.com/example/reviewer", "changed_files": [str(path) for path in changed_files]}, ensure_ascii=False), encoding="utf-8")

    audit = assess_project(str(project)).metadata["capability_absorption_audit"]

    assert audit["generated_only"] is True
    assert audit["local_score_removed"] is True
    assert "score" not in audit
    assert "overall_cap" not in audit
    assert "employee_execution_cap" not in audit
    assert audit["status"] == "audit_only_no_local_score"
    assert audit["risk_level"] == "high"
    assert "latest_absorption_report_or_registry_only" in audit["blockers"]
    assert audit["reason"] == "latest_absorption_changed_only_reports_logs_or_capability_registry"
    assert audit["behavior_source_files"] == []
    assert audit["behavior_test_files"] == []
    assert "retort_engine/absorbed_capabilities.py" in audit["generated_evidence_files"]
    assert "tests/test_absorbed_capabilities.py" in audit["generated_evidence_files"]


def test_llm_absorption_evidence_uses_risk_audit_not_local_score(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    run_dir = project / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"source": "https://github.com/example/reviewer", "changed_files": [str(project / "retort_absorbed_patterns.py")]}, ensure_ascii=False),
        encoding="utf-8",
    )

    evidence = _llm_absorption_evidence(project)

    assert not any(item.startswith("capability_absorption_score=") for item in evidence)
    assert not any(item.startswith("capability_absorption_cap=") for item in evidence)
    assert "capability_absorption_local_score_removed=True" in evidence
    assert any(item.startswith("capability_absorption_risk_level=") for item in evidence)
    assert any(item.startswith("capability_absorption_blockers=") for item in evidence)
    assert any(item.startswith("latest_code_graph_proof=") for item in evidence)


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


def test_extract_json_from_stdout_prefers_last_complete_candidate() -> None:
    incomplete = {"status": "applied", "changed_files": ["a.py"]}
    complete_one = {
        "status": "applied",
        "project": "one",
        "summary": "first",
        "changed_files": ["a.py"],
        "gates": [{"ok": True}],
        "gates_passed": True,
        "review_report_path": "one.json",
        "employee_results_path": "one-result.json",
    }
    complete_two = {**complete_one, "project": "two", "summary": "last"}

    parsed = _extract_json_from_stdout(f"debug {json.dumps(incomplete)}\n{json.dumps(complete_one)}\nnoise\n{json.dumps(complete_two)}")

    assert parsed["project"] == "two"
    assert parsed["summary"] == "last"


def test_extract_json_from_stdout_rejects_incomplete_candidates() -> None:
    parsed = _extract_json_from_stdout('{"status":"applied","changed_files":[]}')

    assert parsed == {}


def test_llm_disabled_semantics_are_consistent(tmp_path: Path) -> None:
    project = tmp_path / "own"
    project.mkdir()
    assessment = {"metadata": {}}

    review = _maybe_request_llm_review({}, project, "assess", "", "", [], [])
    attached = _attach_llm_scoring({}, assessment, project, "assess", "", "", [])

    assert review["status"] == "disabled"
    assert review["dispatch"]["status"] == "disabled"
    assert review["score_source"] == "paibi_llm_disabled"
    assert attached["llm_review"]["status"] == "disabled"
    assert attached["metadata"]["score_source"] == "paibi_llm_disabled"

    with pytest.raises(RuntimeError, match="PaiBi LLM scoring is required"):
        _attach_llm_scoring({"require_deep_review": True}, {"metadata": {}}, project, "assess", "", "", [])


def test_blocking_git_status_exempts_generated_absorption_outputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    own = repo / "packages" / "retort_engine"
    generated = [
        own / "retort_engine" / "absorbed_capabilities.py",
        own / "tests" / "test_absorbed_capabilities.py",
        own / "docs" / "retort_external_review_report.json",
        own / "docs" / "retort_stage_report.json",
    ]
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# generated\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add generated files")
    for path in generated:
        path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    (own / "docs" / "retort_new_gate.json").write_text("{}", encoding="utf-8")
    (own / ".retort" / "absorption_state.json").parent.mkdir(parents=True, exist_ok=True)
    (own / ".retort" / "absorption_state.json").write_text("{}", encoding="utf-8")

    assert _blocking_git_status(repo, own) == ""


def test_generated_absorption_path_detects_docs_retort_json() -> None:
    assert _is_generated_absorption_file("docs/retort_stage_report.json") is True
    assert _is_generated_absorption_file("docs/retort_replay_snapshot.json") is True
    assert _is_generated_absorption_file("docs/other.json") is False
    assert _is_exempt_git_status_path("docs/retort_stage_report.json", (".retort/",)) is True


def test_blocking_git_status_still_flags_real_code_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    own = repo / "packages" / "retort_engine"
    own.mkdir(parents=True)
    real_file = own / "real_behavior.py"
    real_file.write_text("print('dirty')\n", encoding="utf-8")
    assert "packages/retort_engine/" in _blocking_git_status(repo, own)


def test_record_closed_loop_proof_rejects_unvalidated_manual_flags(tmp_path: Path) -> None:
    own = tmp_path / "own"
    own.mkdir()
    (own / "README.md").write_text("# Own\n", encoding="utf-8")

    result = record_closed_loop_proof(
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

    assert result["status"] == "awaiting_execution_evidence"
    assert result["closed_loop_proof"]["verified"] is False
    assert "post_absorption_tests_passed" in result["closed_loop_proof"]["missing"]
    assert "merge_verified" in result["closed_loop_proof"]["missing"]
    assert any("merge_cross_check=False" in item for item in result["closed_loop_proof"]["evidence"])
    assert any("pytest_gate_cross_check=False" in item for item in result["closed_loop_proof"]["evidence"])


def test_record_closed_loop_proof_cross_validates_merge_and_pytest_gate(tmp_path: Path) -> None:
    own = tmp_path / "own"
    init_repo(own)
    tests = own / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    run_dir = own / ".retort" / "real_absorption_runs"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"gates": [{"ok": True, "command": [sys.executable, "-m", "pytest", "tests", "-q"]}]}),
        encoding="utf-8",
    )
    git(own, "checkout", "-b", "retort/absorb-proof")
    (own / "absorbed.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(own, "add", ".")
    git(own, "commit", "-m", "absorb")
    git(own, "checkout", "main")
    git(own, "merge", "--no-ff", "retort/absorb-proof", "-m", "Merge retort proof")
    merge_commit = git(own, "rev-parse", "--short", "HEAD")

    full = record_closed_loop_proof(
        str(own),
        {
            "branch_diff_verified": True,
            "employee_execution_verified": True,
            "post_absorption_tests_passed": True,
            "merge_verified": True,
            "merge_commit": merge_commit,
            "external_advantage_reassessed": True,
            "evidence": ["unit proof"],
        },
    )

    assert full["status"] == "closed_loop_verified"
    assert full["closed_loop_proof"]["verified"] is True
    assert any("merge_cross_check=True" in item for item in full["closed_loop_proof"]["evidence"])
    assert any("pytest_gate_cross_check=True" in item for item in full["closed_loop_proof"]["evidence"])


def test_paibi_llm_review_writes_outbox_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RETORT_PAIBI_API_URL", "disabled")
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    result = request_paibi_llm_review(project=str(project), mode="assess", scores=[{"dimension": "calibrated_overall", "value": 82}], tasks=[])

    assert result["provider"] == "paibi"
    assert result["dispatch"]["status"] == "queued_outbox"
    assert (project / ".retort" / "paibi_llm_outbox.jsonl").is_file()


def test_paibi_llm_review_can_skip_dispatch_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RETORT_PAIBI_API_URL", "disabled")
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    result = request_paibi_llm_review(project=str(project), mode="assess", scores=[{"dimension": "calibrated_overall", "value": 82}], tasks=[], record=False)

    assert result["dispatch"]["status"] == "queued_outbox"
    assert not (project / ".retort" / "llm_reviews.jsonl").exists()


def test_paibi_prompt_keeps_closed_loop_score_cap(tmp_path: Path) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    prompt = build_retort_paibi_prompt(project=project, mode="manual", scores=[], tasks=[])

    assert "排比 Para/Codex" in prompt
    assert "不得超过 82" in prompt
    assert "严格 JSON" in prompt
    assert "证据闭环" in prompt
    assert "能力吸收" in prompt
    assert "本地不提供任何分数" in prompt
    assert "不得把本地能力吸收审计当作参考分" in prompt
    assert "capability_absorption_score" in prompt
    assert "吸收 diff 只改报告/日志/absorbed_patterns 时" in prompt
    assert '"scores"' in prompt


def test_paibi_prompt_strips_legacy_local_capability_scores(tmp_path: Path) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    prompt = build_retort_paibi_prompt(
        project=project,
        mode="manual",
        scores=[],
        tasks=[],
        metadata={"capability_absorption_audit": {"score": 94.0, "overall_cap": 96.0, "employee_execution_cap": 97.0, "risk_level": "high"}},
    )

    assert '"score": 94.0' not in prompt
    assert "overall_cap" not in prompt
    assert "employee_execution_cap" not in prompt
    assert '"local_score_removed": true' in prompt


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


def test_real_absorption_writes_behavior_module_tests_and_runtime_mode(tmp_path: Path) -> None:
    project = tmp_path / "own"
    external = tmp_path / "external"
    (project / "retort_engine").mkdir(parents=True)
    (project / "retort_engine" / "__init__.py").write_text("", encoding="utf-8")
    (external / "internal").mkdir(parents=True)
    (external / "internal" / "review.ts").write_text("review pipeline changed files diff hunk patch set benchmark provider plugin", encoding="utf-8")
    queue = project / ".retort" / "employee_queue.jsonl"
    history = project / ".retort" / "retort_history.sqlite"

    result = apply_real_absorption(
        {
            "own_project": str(project),
            "external_path": str(external),
            "source": "unit-source",
            "tasks": [{"task_id": "retort-absorb-review", "title": "Review pipeline", "dimension": "comparative_analysis_depth", "priority": "P1"}],
            "employee_queue": str(queue),
            "history_store": str(history),
            "python": sys.executable,
        }
    )

    assert result["status"] == "applied"
    assert result["gates_passed"] is True
    assert str(project / "retort_engine" / "absorbed_capabilities.py") in result["changed_files"]
    assert str(project / "tests" / "test_absorbed_capabilities.py") in result["changed_files"]
    assert str(project / "retort_engine" / "review_context_bias.py") in result["changed_files"]
    assert str(project / "tests" / "test_review_context_bias.py") in result["changed_files"]
    assert Path(result["review_context_bias_path"]).is_file()
    assert Path(result["review_context_bias_test_path"]).is_file()
    assert Path(result["code_graph_proof_path"]).is_file()
    proof = json.loads(Path(result["code_graph_proof_path"]).read_text(encoding="utf-8"))
    assert proof["node_count"] >= 1
    assert proof["edge_count"] >= 1
    assert result["code_graph_node_count"] == proof["node_count"]
    assert result["code_graph_edge_count"] == proof["edge_count"]
    employee_result = json.loads(Path(result["employee_results_path"]).read_text(encoding="utf-8"))
    assert employee_result["execution_mode"] == "employee_runtime_worker"
    assert employee_result["runtime_evidence"]["independent_process"] is True
    worker_review = employee_result["runtime_evidence"]["worker_review"]
    assert worker_review["status"] == "reviewed"
    assert worker_review["file_count"] >= 1
    assert Path(worker_review["artifact"]).is_file()


def test_paibi_parallel_review_dispatches_independent_subtasks(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_request(self: PaibiLLMClient, method: str, path: str, *, token: str = "", json_body: dict[str, object] | None = None) -> dict[str, object]:
        if path == "/api/health":
            return {"success": True}
        if path == "/api/auth/guest":
            return {"token": "token-1"}
        if path == "/api/devices":
            return {
                "devices": [
                    {"id": "primary", "name": "Primary", "status": "online", "devTool": "codex", "isPrimary": True, "tools": [{"toolName": "codex", "status": "idle"}]},
                    {"id": "worker-a", "name": "Worker A", "status": "online", "devTool": "cursor", "tools": [{"toolName": "cursor", "status": "idle"}]},
                    {"id": "worker-b", "name": "Worker B", "status": "online", "devTool": "trae", "tools": [{"toolName": "trae", "status": "idle"}]},
                ]
            }
        if path.startswith("/api/devices/"):
            raise AssertionError("parallel review should not force devices to codex")
        if path == "/api/tasks":
            assert json_body is not None
            calls.append(json_body)
            task_id = str(json_body.get("task_id") or "task-1")
            return {"task": {"id": task_id, "status": "running"}, "subtask": {"id": f"sub-{len(calls)}"}}
        raise AssertionError(path)

    monkeypatch.setattr(PaibiLLMClient, "_request", fake_request)

    result = request_paibi_parallel_review(project=str(project), max_parallel=3)

    assert result["status"] == "accepted"
    assert result["dispatch"]["task_id"] == "task-1"
    assert len(calls) == 3
    assert calls[0]["device_id"] == "worker-a"
    assert calls[1]["device_id"] == "worker-b"
    assert calls[2]["device_id"] == "worker-a"
    assert calls[0]["tool_name"] == "cursor"
    assert calls[1]["tool_name"] == "trae"
    assert calls[2]["tool_name"] == "cursor"
    assert "task_id" not in calls[0]
    assert calls[1]["task_id"] == "task-1"
    assert "depends_on" not in calls[0]
    assert "depends_on" not in calls[1]


def test_paibi_parallel_review_uses_same_device_multi_tool_slots(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fake_request(self: PaibiLLMClient, method: str, path: str, *, token: str = "", json_body: dict[str, object] | None = None) -> dict[str, object]:
        if path == "/api/health":
            return {"success": True}
        if path == "/api/auth/guest":
            return {"token": "token-1"}
        if path == "/api/devices":
            return {
                "devices": [
                    {
                        "id": "worker-a",
                        "name": "Worker A",
                        "status": "online",
                        "devTool": "cursor",
                        "tools": [
                            {"toolName": "cursor", "status": "idle"},
                            {"toolName": "trae", "status": "idle"},
                            {"toolName": "claude_code", "status": "idle"},
                            {"toolName": "codex", "status": "not_installed"},
                        ],
                    }
                ]
            }
        if path == "/api/tasks":
            assert json_body is not None
            calls.append(json_body)
            task_id = str(json_body.get("task_id") or "task-1")
            return {"task": {"id": task_id, "status": "running"}, "subtask": {"id": f"sub-{len(calls)}"}}
        raise AssertionError(path)

    monkeypatch.setattr(PaibiLLMClient, "_request", fake_request)

    result = request_paibi_parallel_review(project=str(project), max_parallel=3)

    assert result["status"] == "accepted"
    assert result["dispatch"]["device_count"] == 1
    assert result["dispatch"]["parallelism"] == 3
    assert result["dispatch"]["degraded_reason"] == ""
    assert [call["tool_name"] for call in calls] == ["cursor", "trae", "claude_code"]
    assert len({call["device_id"] for call in calls}) == 1


def test_paibi_parallel_status_reports_unblock_tasks(monkeypatch) -> None:
    def fake_fetch_task(self: PaibiLLMClient, task_id: str) -> dict[str, object]:
        return {
            "task": {
                "id": task_id,
                "status": "running",
                "subTasks": [
                    {"id": "sub-ok", "title": "ok", "status": "completed", "progress": 100, "logs": [{"content": '{"panel_id":"ok","score_suggestion":82}'}]},
                    {"id": "sub-pending", "title": "pending", "status": "pending", "progress": 0, "depends_on": [], "logs": [{"content": "子任务未派发：设备 dev 当前不可用（离线或执行器忙）"}]},
                    {"id": "sub-bad", "title": "blocked", "status": "failed", "blocked": True, "last_error": "工作设备 Worker 缺少自动改码执行器：Codex CLI", "logs": []},
                ],
            }
        }

    monkeypatch.setattr(PaibiLLMClient, "fetch_task", fake_fetch_task)

    result = fetch_paibi_parallel_review_status("task-1")

    assert result["parallel"] is True
    assert result["parallel_summary"]["has_blockers"] is True
    kinds = {item["kind"] for item in result["blockers"]}
    assert "executor_missing" in kinds
    assert "worker_capacity_limit" in kinds
    assert {item["owner_hint"] for item in result["unblock_tasks"]} == {"runtime"}


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

    result = RetortService().assess({"project": str(project), "use_llm": True, "wait_llm_sec": 1, "require_deep_review": True})

    scores = {item["dimension"]: item["value"] for item in result["scores"]}
    records = (project / ".retort" / "llm_reviews.jsonl").read_text(encoding="utf-8")
    assert result["metadata"]["score_source"] == "paibi_llm"
    assert result["metadata"]["score_authority"] == "paibi_llm_prompt_only"
    assert '"record_type": "deep_score"' in records
    assert scores["calibrated_overall"] == 79
    assert scores["employee_execution_integration"] == 70


def test_service_assess_rejects_local_score_when_deep_review_required(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "own"
    project.mkdir()
    (project / "README.md").write_text("# Own\n", encoding="utf-8")

    def fake_request(**kwargs) -> dict[str, object]:
        return {"provider": "paibi", "enabled": True, "status": "accepted", "dispatch": {"task_id": "task-pending"}}

    def fake_wait(task_id: str, *, timeout_sec: float, interval_sec: float = 5.0) -> dict[str, object]:
        return {"provider": "paibi", "task_id": task_id, "status": "running"}

    monkeypatch.setattr("retort_engine.core.request_paibi_llm_review", fake_request)
    monkeypatch.setattr("retort_engine.core.wait_for_paibi_llm_review", fake_wait)

    with pytest.raises(RuntimeError, match="deep review did not complete"):
        RetortService().assess({"project": str(project), "use_llm": True, "wait_llm_sec": 1, "require_deep_review": True})
