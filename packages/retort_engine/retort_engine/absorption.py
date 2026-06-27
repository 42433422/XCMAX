from __future__ import annotations

from pathlib import Path

from retort_engine.branching import BranchWorkflowError, BranchWorkflowState, begin_absorption_branch, merge_absorption_branch
from retort_engine.evaluators import EvidenceProjectEvaluator
from retort_engine.history import RetortHistoryStore
from retort_engine.license_gate import license_gate
from retort_engine.models import AbsorptionResult, ExternalProjectRef, ImprovementTask, ProjectAssessment
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter
from retort_engine.semantic_reviewer import semantic_compare
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
        tasks = build_absorption_tasks(own, external, external_ref, semantic_findings=semantic_findings, max_tasks=max_tasks)
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
        result = AbsorptionResult(status, own, external, external_ref, tasks, f"Generated {len(tasks)} absorption task(s) from external project {external_ref.source}.", license_result.to_findings(), semantic_findings, rejection_findings, branch_state.to_dict())
        if history_store:
            RetortHistoryStore(history_store).record_absorption_run(result)
        return result

    def _blocked_result(self, own_project: str, external_ref: ExternalProjectRef, run_local_gates: bool, rejection_findings: tuple[str, ...], branch_state: BranchWorkflowState) -> AbsorptionResult:
        own = self.evaluator.evaluate({"project_path": str(Path(own_project).resolve()), "run_local_gates": run_local_gates})
        external = self.evaluator.evaluate({"project_path": external_ref.local_path, "run_local_gates": run_local_gates})
        return AbsorptionResult("blocked_by_branch_workflow", own, external, external_ref, (), "Branch workflow blocked absorption before task generation.", (), (), rejection_findings, branch_state.to_dict())


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
    tasks: list[ImprovementTask] = []
    for strength in external_assessment.strengths:
        if strength not in own_assessment.strengths:
            tasks.append(_task_from_strength(external_ref, strength, len(tasks) + 1))
            if len(tasks) >= max_tasks:
                return tuple(tasks)
    for finding in semantic_findings:
        tasks.append(_task_from_semantic_finding(external_ref, finding, len(tasks) + 1))
        if len(tasks) >= max_tasks:
            return tuple(tasks)
    return tuple(tasks)


def _task_from_strength(external_ref: ExternalProjectRef, strength: str, index: int) -> ImprovementTask:
    return ImprovementTask(f"retort-absorb-strength-{index:02d}", f"Review external strength: {strength[:80]}", "external_strength", f"External project exposes a strength not detected in own project: {strength}.", f"Inspect {external_ref.local_path}, decide whether this strength should be adopted, and create an implementation task if relevant.", "Decision is recorded with evidence; adopted items have a verification command.", "fhd-core-maintainer", "P2")


def _task_from_semantic_finding(external_ref: ExternalProjectRef, finding: str, index: int) -> ImprovementTask:
    return ImprovementTask(f"retort-absorb-semantic-{index:02d}", f"Adapt semantic pattern: {finding[:70]}", "comparative_analysis_depth", f"Semantic reviewer found an external project advantage: {finding}.", f"Inspect {external_ref.local_path}, identify the design pattern, and adapt it with project-local implementation.", "A follow-up Retort comparison shows this semantic gap is closed or justified.", "fhd-core-maintainer", "P1")


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-") or "score"
