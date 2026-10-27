"""Explicit ports for one maintenance runtime, bound at construction time.

The production composition uses the configured process store and services. A
runtime can instead own another store/executor without mutating a facade or
rebinding dependencies used by an already-running transaction.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

from modstore_server import (
    self_maintenance_para_merge_remediation,
    self_maintenance_retort_remediation,
)

from . import (
    decision,
    dispatch,
    knowledge_gate,
    outcomes,
    prompts,
    schedule,
    store,
    workspace,
)

Record = Dict[str, Any]
RecordOperation = Callable[..., Record]
StepResult = tuple[Record, bool, str, Record, str, int, int]


@dataclass(frozen=True)
class RuntimeState:
    """Lease, durable state, and the terminal memory projection share one owner."""

    lease: Callable[[], AbstractContextManager[bool]]
    ensure_baseline: Callable[[], Record]
    load_memory: Callable[[], Record]
    write_memory: Callable[[Record], None]
    memory_path: Callable[[], Path]
    append: Callable[[Record], None]
    record_outcome: Callable[[Record, Record], Any]

    @classmethod
    def configured(cls) -> RuntimeState:
        return cls(
            lease=store._exclusive_loop_lease,
            ensure_baseline=store.ensure_clean_baseline,
            load_memory=store._load_loop_memory,
            write_memory=store._write_loop_memory,
            memory_path=store.loop_memory_path,
            append=store._append_ledger,
            record_outcome=outcomes._update_loop_memory,
        )


@dataclass(frozen=True)
class RuntimeRecovery:
    """Recover prior work before selecting the next executable candidate."""

    stale_runs: RecordOperation
    requested_merges: Callable[[Record], Record]
    retort_scope: Callable[[Record], Record]
    absorbed_merges: RecordOperation

    @classmethod
    def configured(cls) -> RuntimeRecovery:
        return cls(
            stale_runs=schedule.reconcile_stale_self_maintenance_runs,
            requested_merges=outcomes._reconcile_requested_merge_feedback,
            retort_scope=self_maintenance_retort_remediation.reconcile_retort_scope_remediations,
            absorbed_merges=(
                self_maintenance_para_merge_remediation.reconcile_absorbed_para_merge_remediations
            ),
        )


@dataclass(frozen=True)
class RuntimePolicy:
    """Scheduling admission and final authorization remain independent of execution."""

    admit: RecordOperation
    actor_user_id: Callable[[], int]
    decide: RecordOperation

    @classmethod
    def configured(cls) -> RuntimePolicy:
        return cls(
            admit=schedule.should_run_self_maintenance_loop,
            actor_user_id=schedule._self_maintenance_actor_user_id,
            decide=decision._decide_post_loop_policy,
        )


@dataclass(frozen=True)
class RuntimeExecution:
    """Employee dispatch and pre-review checks; no scheduling or lease authority."""

    run_step: Callable[..., StepResult]
    retort_before_review: RecordOperation
    validate_branch_delivery: RecordOperation
    validate_knowledge: RecordOperation
    reject_knowledge: RecordOperation

    @classmethod
    def configured(cls) -> RuntimeExecution:
        return cls(
            run_step=dispatch._run_step_with_inner_retries,
            retort_before_review=knowledge_gate._evaluate_retort_clarification_before_review,
            validate_branch_delivery=workspace._validate_remediation_branch_delivery,
            validate_knowledge=knowledge_gate._early_kb_validation_for_branch,
            reject_knowledge=knowledge_gate._reject_and_retry_kb_schema_failure,
        )


@dataclass(frozen=True)
class RuntimePrompts:
    """Task rendering can use the same knowledge/baseline source as its runtime."""

    code: Callable[..., str]
    review: Callable[..., str]
    qa: Callable[..., str]

    @classmethod
    def configured(cls) -> RuntimePrompts:
        return cls(
            code=prompts._code_task_text,
            review=prompts._review_task_text,
            qa=prompts._qa_task_text,
        )
