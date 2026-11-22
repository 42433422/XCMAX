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
        """统一 Agent Runtime 接缝：run 终态记忆回写（best-effort，开关控制）。"""
        try:
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                remember_run_outcome,
            )

            if not agent_runtime_hooks_enabled():
                return
            ctx = dict(run.metadata.get("runtime_context") or {})
            summary = self.run_outcome_summary(run)
            remembered = remember_run_outcome(
                user_id=run.user_id,
                task=run.message,
                summary=summary,
                success=str(run.status) == "completed",
                session_id=str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                metadata={"run_id": run.run_id, "intent": run.intent, "status": str(run.status)},
            )
            run.add_event(
                "runtime.memory_writeback",
                "run 终态记忆回写完成" if remembered else "run 终态记忆回写跳过",
                {"remembered": bool(remembered), "status": str(run.status)},
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
