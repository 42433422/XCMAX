"""Persist formal task outcomes on the existing run ledger."""

from __future__ import annotations

import logging

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RunKnowledge:
    def __init__(self, repository: AgentRunRepository) -> None:
        self.repository = repository

    def remember_run_outcome_for(self, run: AgentRun) -> None:
        """Write accepted results back through the existing memory namespace."""
        try:
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash
            from app.application.agent_orchestrator.result_verification import (
                summarize_verification,
            )
            from app.application.agent_orchestrator.task_context import task_context_of
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                remember_run_outcome,
            )
            from app.domain.task_lifecycle.results import execution_result_error

            if not agent_runtime_hooks_enabled():
                return
            report = summarize_verification(run)
            completed = run.status == "completed"
            reason = (
                "execution_not_terminal"
                if run.status not in {"completed", "failed", "cancelled", "rejected"}
                else "result_not_verified"
                if completed
                and (report.get("accepted") is not True or execution_result_error(run.final_output))
                else ""
            )
            if reason:
                run.add_event(
                    "runtime.memory_writeback",
                    "结果未完成或未通过核验，未写入成功记忆",
                    {"remembered": False, "status": str(run.status), "reason": reason},
                )
                return
            committed = self.repository.get(run.run_id)
            if (
                committed is None
                or committed.status != run.status
                or canonical_hash(committed.final_output) != canonical_hash(run.final_output)
                or (
                    completed
                    and canonical_hash(summarize_verification(committed)) != canonical_hash(report)
                )
            ):
                run.add_event(
                    "runtime.memory_writeback",
                    "终态回执尚未持久化，未写入结果记忆",
                    {
                        "remembered": False,
                        "status": str(run.status),
                        "reason": "terminal_receipt_not_committed",
                    },
                )
                return
            ctx = dict(run.metadata.get("runtime_context") or {})
            task = task_context_of(run)
            summary = (
                self.run_outcome_summary(run) if completed else str(run.error or run.status)[:600]
            )
            evidence = canonical_hash(
                [
                    {
                        key: row.get(key)
                        for key in (
                            "call_id",
                            "status",
                            "contract_sha256",
                            "output_sha256",
                            "evidence_sha256",
                        )
                    }
                    for row in report["steps"]
                ]
            )
            feedback_id = canonical_hash([run.run_id, run.status, summary, evidence])
            previous = run.metadata.get("memory_feedback") or {}
            if previous.get("feedback_id") == feedback_id and previous.get("remembered") is True:
                return
            metadata = {
                "run_id": run.run_id,
                "task_id": str(task["task_id"]),
                "root_run_id": str(task["root_run_id"]),
                "turn_id": str(task.get("turn_id") or ctx.get("turn_id") or ""),
                "tenant_id": str(ctx.get("tenant_id") or ""),
                "intent": run.intent,
                "status": str(run.status),
                "verification_status": report["status"],
                "evidence_sha256": evidence,
                "feedback_id": feedback_id,
            }
            remembered = remember_run_outcome(
                user_id=run.user_id,
                task=run.message,
                summary=summary,
                success=completed,
                session_id=str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                metadata=metadata,
            )
            run.metadata["memory_feedback"] = {**metadata, "remembered": bool(remembered)}
            run.add_event(
                "runtime.memory_writeback",
                "run 终态记忆回写完成" if remembered else "run 终态记忆回写跳过",
                {**metadata, "remembered": bool(remembered)},
            )
        except RECOVERABLE_ERRORS:
            logger.debug("memory writeback hook skipped", exc_info=True)

    @staticmethod
    def run_outcome_summary(run: AgentRun) -> str:
        """终态摘要：优先取工具输出的可读字段，退化为错误/状态描述。"""
        outputs = (
            run.final_output.get("node_outputs") if isinstance(run.final_output, dict) else None
        )
        if isinstance(outputs, dict):
            for value in outputs.values():
                if isinstance(value, dict):
                    for key in ("summary", "message", "output", "result", "preview"):
                        text = str(value.get(key) or "").strip()
                        if text:
                            return text[:600]
                elif isinstance(value, str) and value.strip():
                    return value.strip()[:600]
        return str(run.error or run.status or "")[:600]
