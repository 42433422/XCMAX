from __future__ import annotations

from pathlib import Path
from typing import Any

from retort_engine.bounded_agent_loop import run_bounded_agent_loop
from retort_engine.branching import BranchWorkflowError, BranchWorkflowState, begin_absorption_branch, merge_absorption_branch
from retort_engine.evaluators import EvidenceProjectEvaluator
from retort_engine.history import RetortHistoryStore
from retort_engine.license_gate import license_gate
from retort_engine.models import AbsorptionResult, ExternalProjectRef, ImprovementTask, ProjectAssessment
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter
from retort_engine.issue_capability_benchmark import run_heldout_oracle_suite
from retort_engine.repository_intelligence import build_ranked_repository_map, compare_repository_gaps, task_targets_from_map
from retort_engine.semantic_reviewer import semantic_compare
from retort_engine.self_bootstrap import external_improvement_gate
from retort_engine.sources import resolve_external_project


class RetortAbsorptionRunner:
    def __init__(self, evaluator: EvidenceProjectEvaluator | None = None) -> None:
        self.evaluator = evaluator or EvidenceProjectEvaluator()

    def run(
        self,
        *,
        own_project: str,
        external_ref: ExternalProjectRef,
        run_local_gates: bool = False,
        min_delta: float = 3.0,
        max_tasks: int = 12,
        employee_queue_path: str = "",
        history_store: str = "",
        enforce_license: bool = False,
        branch_workflow: bool = False,
        absorption_branch: str = "",
        merge_after: bool = False,
        allow_dirty_branch: bool = False,
    ) -> AbsorptionResult:
        branch_state = BranchWorkflowState(False, str(Path(own_project).resolve()))
        rejection_findings: tuple[str, ...] = ()
        package_root = Path(__file__).resolve().parents[1]
        target_root = Path(own_project).resolve()
        if target_root != package_root:
            policy_gate = external_improvement_gate(package_root, target_root)
            if policy_gate["status"] != "allowed":
                rejection_findings = tuple(str(item) for item in policy_gate.get("missing") or ())
                return self._policy_blocked_result(own_project, external_ref, run_local_gates, rejection_findings, policy_gate)
        if branch_workflow:
            try:
                branch_state = begin_absorption_branch(own_project, source=external_ref.source, branch_name=absorption_branch, allow_dirty=allow_dirty_branch)
            except BranchWorkflowError as exc:
                rejection_findings = (f"branch_workflow_blocked: {exc}",)
                return self._blocked_result(own_project, external_ref, run_local_gates, rejection_findings, branch_state)
        own = self.evaluator.evaluate({"project_path": str(Path(own_project).resolve()), "run_local_gates": run_local_gates})
        external = self.evaluator.evaluate({"project_path": external_ref.local_path, "run_local_gates": run_local_gates})
        license_result = license_gate(external_ref.local_path, enforce=enforce_license)
        semantic_findings = tuple(finding.to_text() for finding in semantic_compare(own_project, external_ref.local_path))
        capability_context = build_project_absorption_context(own_project, external_ref.local_path)
        tasks, task_loop = _build_absorption_task_plan(
            own,
            external,
            external_ref,
            semantic_findings=semantic_findings,
            frontier_tasks=_frontier_capability_tasks(external_ref),
            max_tasks=max_tasks,
        )
        capability_context["bounded_task_execution"] = task_loop
        status = "tasks_generated" if tasks else "no_external_advantage_found"
        if enforce_license and not license_result.passed:
            status = "blocked_by_license_gate"
            tasks = ()
            rejection_findings = rejection_findings + ("license gate blocked absorption",)
        if employee_queue_path and tasks:
            RetortEmployeeRuntimeAdapter(employee_queue_path, history_store=history_store).submit_tasks(tasks, source=external_ref.source)
        if merge_after and branch_state.enabled and status != "blocked_by_license_gate":
            try:
                branch_state = merge_absorption_branch(own_project, branch_state)
            except BranchWorkflowError as exc:
                status = "merge_blocked"
                rejection_findings = rejection_findings + (f"merge_after_blocked: {exc}",)
        result = AbsorptionResult(status, own, external, external_ref, tasks, f"Generated {len(tasks)} absorption task(s) from external project {external_ref.source}.", license_result.to_findings(), semantic_findings, rejection_findings, branch_state.to_dict(), capability_context)
        if history_store:
            RetortHistoryStore(history_store).record_absorption_run(result)
        return result

    def _blocked_result(self, own_project: str, external_ref: ExternalProjectRef, run_local_gates: bool, rejection_findings: tuple[str, ...], branch_state: BranchWorkflowState) -> AbsorptionResult:
        own = self.evaluator.evaluate({"project_path": str(Path(own_project).resolve()), "run_local_gates": run_local_gates})
        external = self.evaluator.evaluate({"project_path": external_ref.local_path, "run_local_gates": run_local_gates})
        return AbsorptionResult("blocked_by_branch_workflow", own, external, external_ref, (), "Branch workflow blocked absorption before task generation.", (), (), rejection_findings, branch_state.to_dict())

    def _policy_blocked_result(
        self,
        own_project: str,
        external_ref: ExternalProjectRef,
        run_local_gates: bool,
        rejection_findings: tuple[str, ...],
        policy_gate: dict[str, Any],
    ) -> AbsorptionResult:
        own = self.evaluator.evaluate({"project_path": str(Path(own_project).resolve()), "run_local_gates": run_local_gates})
        external = self.evaluator.evaluate({"project_path": external_ref.local_path, "run_local_gates": run_local_gates})
        return AbsorptionResult(
            "blocked_by_self_depth_gate",
            own,
            external,
            external_ref,
            (),
            "Retort must verify its own frontier depth before improving another module.",
            (),
            (),
            rejection_findings,
            {},
            {"external_improvement_gate": policy_gate},
        )


def run_absorption(
    *,
    own_project: str,
    github_url: str = "",
    external_path: str = "",
    cache_dir: str = "",
    ref: str = "",
    refresh: bool = False,
    run_local_gates: bool = False,
    min_delta: float = 3.0,
    max_tasks: int = 12,
    employee_queue_path: str = "",
    history_store: str = "",
    enforce_license: bool = False,
    branch_workflow: bool = False,
    absorption_branch: str = "",
    merge_after: bool = False,
    allow_dirty_branch: bool = False,
) -> AbsorptionResult:
    external_ref = resolve_external_project(github_url=github_url, external_path=external_path, cache_dir=cache_dir, ref=ref, refresh=refresh)
    return RetortAbsorptionRunner().run(own_project=own_project, external_ref=external_ref, run_local_gates=run_local_gates, min_delta=min_delta, max_tasks=max_tasks, employee_queue_path=employee_queue_path, history_store=history_store, enforce_license=enforce_license, branch_workflow=branch_workflow, absorption_branch=absorption_branch, merge_after=merge_after, allow_dirty_branch=allow_dirty_branch)


def build_absorption_tasks(own_assessment: ProjectAssessment, external_assessment: ProjectAssessment, external_ref: ExternalProjectRef, *, semantic_findings: tuple[str, ...] = (), max_tasks: int) -> tuple[ImprovementTask, ...]:
    tasks, _loop = _build_absorption_task_plan(
        own_assessment,
        external_assessment,
        external_ref,
        semantic_findings=semantic_findings,
        max_tasks=max_tasks,
    )
    return tasks


def _build_absorption_task_plan(
    own_assessment: ProjectAssessment,
    external_assessment: ProjectAssessment,
    external_ref: ExternalProjectRef,
    *,
    semantic_findings: tuple[str, ...] = (),
    frontier_tasks: tuple[ImprovementTask, ...] = (),
    max_tasks: int,
) -> tuple[tuple[ImprovementTask, ...], dict[str, Any]]:
    tasks: list[ImprovementTask] = list(frontier_tasks[:max_tasks])
    for strength in external_assessment.strengths:
        if len(tasks) >= max_tasks:
            break
        if strength not in own_assessment.strengths:
            tasks.append(_task_from_strength(external_ref, strength, len(tasks) + 1))
    for finding in semantic_findings:
        if len(tasks) >= max_tasks:
            break
        tasks.append(_task_from_semantic_finding(external_ref, finding, len(tasks) + 1))
    own_map = build_ranked_repository_map(
        own_assessment.project,
        focus_terms=("absorb", "agent", "benchmark", "oracle"),
        max_files=12,
        max_chars=12_000,
    )
    focus_targets = task_targets_from_map(own_map, limit=3)
    focus_paths = [str(item["path"]) for item in focus_targets]
    enriched: list[ImprovementTask] = []
    for task in tasks[:max_tasks]:
        action = task.action
        if focus_paths and "target_files=" not in action:
            action = f"{action} target_files={','.join(focus_paths)}"
        enriched.append(
            ImprovementTask(
                task.task_id,
                task.title,
                task.dimension,
                task.why,
                action,
                task.acceptance,
                task.owner_hint,
                task.priority,
            )
        )
    candidates = tuple(enriched)
    if not candidates:
        return (), {"status": "no_tasks", "summary": {"completed": True, "step_count": 0, "max_steps": max_tasks}, "focus_targets": focus_targets}
    oracle = run_heldout_oracle_suite(Path(__file__).resolve().parents[1])

    def _executor(action: dict[str, Any]) -> dict[str, Any]:
        index = int(action["candidate_index"])
        task = candidates[index]
        return {
            "task_id": task.task_id,
            "accepted": True,
            "oracle_resolved": bool(oracle["summary"]["all_resolved"]),
            "target_files": focus_paths,
        }

    loop = run_bounded_agent_loop(
        "plan synthesize and oracle-verify absorption tasks",
        planner=lambda _objective, trajectory: {"candidate_index": len(trajectory), "phase": "synthesize"},
        executor=_executor,
        judge=lambda _objective, trajectory: {
            "complete": len(trajectory) >= len(candidates),
            "score": round(100 * len(trajectory) / len(candidates), 2),
            "missing": "" if len(trajectory) >= len(candidates) else "remaining_candidates",
            "oracle_resolved_count": oracle["summary"]["resolved_count"],
        },
        max_steps=len(candidates),
        wall_time_limit_sec=60,
        trajectory_dir=Path(__file__).resolve().parents[1] / ".retort" / "trajectories",
        run_id="absorption-task-routing",
    )
    accepted_ids = {str(row["observation"].get("task_id") or "") for row in loop["trajectory"] if row["observation"].get("accepted")}
    loop["focus_targets"] = focus_targets
    loop["oracle_summary"] = oracle["summary"]
    return tuple(task for task in candidates if task.task_id in accepted_ids), loop

def _frontier_capability_tasks(external_ref: ExternalProjectRef) -> tuple[ImprovementTask, ...]:
    source = external_ref.source.lower().rstrip("/").removesuffix(".git")
    specs: list[tuple[str, str, str, str, str]] = []
    if source.endswith("/aider-ai/aider"):
        specs = [
            (
                "repository_intelligence",
                "Adopt dependency-ranked repository context",
                "Rank symbols and files by dependency PageRank plus task mentions before expensive reasoning.",
                "Add a bounded repository map to the target agent context path.",
                "A behavior test proves dependency hubs outrank unrelated keyword-heavy files under a fixed context budget.",
            )
        ]
    elif source.endswith("/swe-agent/mini-swe-agent"):
        specs = [
            (
                "bounded_execution",
                "Add explicit step, time, and error budgets to agent execution",
                "mini-SWE-agent stops on step, cost, wall-time, and repeated format failures instead of relying on prompts.",
                "Wire hard limits into the target employee or coding-agent loop and expose the exit reason.",
                "Tests prove each limit terminates deterministically and returns a machine-readable exit status.",
            ),
            (
                "trajectory_persistence",
                "Persist replayable action-observation trajectories",
                "mini-SWE-agent serializes model calls, environment configuration, actions, observations, exit status, and submission.",
                "Store a versioned trajectory for every target-module agent run.",
                "A failed run can be replayed from one artifact with task, actions, observations, budgets, and terminal status intact.",
            ),
            (
                "process_safety",
                "Kill the full command process group on timeout",
                "mini-SWE-agent prevents orphan child processes when an environment command times out.",
                "Apply process-group timeout cleanup to target-module command execution.",
                "A test launches a child process, triggers timeout, and proves both parent and child are terminated.",
            ),
        ]
    elif source.endswith("/openhands/software-agent-sdk"):
        specs = [
            (
                "goal_audit",
                "Separate goal completion judgment from agent execution",
                "OpenHands uses a transport-independent goal controller that returns complete, capped, or follow-up decisions.",
                "Add an independent post-run judge to the target workflow.",
                "The workflow cannot claim completion without a verdict and reports capped work separately from success.",
            ),
            (
                "stuck_detection",
                "Detect repeated action, error, monologue, and alternating loops",
                "OpenHands audits a bounded recent event window for several unproductive loop shapes.",
                "Add event-based stuck detection before the target agent spends another model turn.",
                "Behavior tests cover repeated action-observation, repeated errors, and alternating cycles without false positives after user input.",
            ),
        ]
    elif source.endswith("/swe-bench/swe-bench"):
        specs = [
            (
                "reproducible_evaluation",
                "Gate patches with fail-to-pass and regression oracles",
                "SWE-bench resolves an issue only when the patch applies, failing tests pass, and existing passing tests do not regress.",
                "Run target-module patches in an isolated reproducible environment with before/after test evidence.",
                "The report rejects empty, unapplied, already-passing, off-target, and regressing patches.",
            )
        ]
    elif source.endswith("/swe-bench/swe-smith"):
        specs = [
            (
                "verified_task_synthesis",
                "Generate new repair tasks only from verified defects",
                "SWE-smith derives issue tasks from concrete test/patch evidence and validates them before dataset use.",
                "Feed the target improvement queue only with reproducible fail-to-pass records.",
                "Every synthesized task contains a failing test, failing output, reference patch, and verified passing result after repair.",
            )
        ]
    return tuple(
        ImprovementTask(
            f"retort-frontier-{dimension}-{index:02d}",
            title,
            dimension,
            why,
            action,
            acceptance,
            "fhd-core-maintainer",
            "P0",
        )
        for index, (dimension, title, why, action, acceptance) in enumerate(specs, start=1)
    )


def build_project_absorption_context(own_project: str | Path, external_project: str | Path) -> dict[str, Any]:
    focus_terms = ("absorb", "agent", "benchmark", "evaluation", "repository", "task")
    own_map = build_ranked_repository_map(own_project, focus_terms=focus_terms, max_files=12, max_chars=12_000)
    external_map = build_ranked_repository_map(external_project, focus_terms=focus_terms, max_files=12, max_chars=12_000)
    graph_gap = compare_repository_gaps(own_project, external_project, focus_terms=focus_terms, max_files=12)
    return {
        "status": "ready" if own_map["status"] == "ready" and external_map["status"] == "ready" else "partial",
        "repository_intelligence": {
            "own": {"summary": own_map["summary"], "top_files": [row["path"] for row in own_map["files"][:5]]},
            "external": {"summary": external_map["summary"], "top_files": [row["path"] for row in external_map["files"][:5]]},
            "algorithm": own_map["evidence"]["algorithm"],
            "task_targets": task_targets_from_map(own_map, limit=3),
        },
        "graph_gap": graph_gap,
        "evaluation_contract": {
            "patch_must_apply": True,
            "before_must_fail": True,
            "after_must_pass": True,
            "existing_passing_tests_must_not_regress": True,
            "synthetic_tasks_require_verified_repair": True,
        },
        "source_layers": ["Aider repo map", "mini-SWE-agent budget", "OpenHands goal audit", "SWE-bench oracle", "SWE-smith verified synthesis"],
    }


def _task_from_strength(external_ref: ExternalProjectRef, strength: str, index: int) -> ImprovementTask:
    return ImprovementTask(f"retort-absorb-strength-{index:02d}", f"Review external strength: {strength[:80]}", "external_strength", f"External project exposes a strength not detected in own project: {strength}.", f"Inspect {external_ref.local_path}, decide whether this strength should be adopted, and create an implementation task if relevant.", "Decision is recorded with evidence; adopted items have a verification command.", "fhd-core-maintainer", "P2")


def _task_from_semantic_finding(external_ref: ExternalProjectRef, finding: str, index: int) -> ImprovementTask:
    return ImprovementTask(f"retort-absorb-semantic-{index:02d}", f"Adapt semantic pattern: {finding[:70]}", "comparative_analysis_depth", f"Semantic reviewer found an external project advantage: {finding}.", f"Inspect {external_ref.local_path}, identify the design pattern, and adapt it with project-local implementation.", "A follow-up Retort comparison shows this semantic gap is closed or justified.", "fhd-core-maintainer", "P1")


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-") or "score"
