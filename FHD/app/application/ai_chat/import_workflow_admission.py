"""Prepare context for the single model-selected reply or business plan."""

from __future__ import annotations

from typing import Any, Protocol

from app.application.ai_chat.workflow_session import CANCEL_WORDS, CONFIRM_WORDS


class ImportAdmissionCallbacks(Protocol):
    def _resume_pending_dynamic_workflow(
        self, user_id: str, message: str, text: str, context: dict[str, Any] | None = None
    ) -> tuple[bool, dict[str, Any] | None]: ...
    def _hydrate_pending_workflow(self, user_id: str, session_id: str) -> bool: ...
    def _sweep_expired_clarifications(self) -> list[str]: ...
    def _dispatch_model_selection(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None: ...


class ImportWorkflowAdmission:
    def __init__(
        self, pending: dict[str, dict[str, Any]], callbacks: ImportAdmissionCallbacks
    ) -> None:
        self.pending = pending
        self.callbacks = callbacks

    def handle(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        file_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = str(message or "").strip()
        if not text:
            return None
        self.callbacks._sweep_expired_clarifications()
        merged_file_context: dict[str, Any] = {}
        for key in ("file_analysis", "file_context"):
            value = context.get(key)
            if isinstance(value, dict):
                merged_file_context.update(value)
        if isinstance(file_context, dict):
            merged_file_context.update(file_context)
        planning_context = dict(context)
        if merged_file_context:
            planning_context["file_context"] = merged_file_context
        control = text.lower().rstrip("。.!！") in CONFIRM_WORDS | CANCEL_WORDS
        session_id = str(context.get("session_id") or context.get("conversation_id") or "")
        if control and (
            user_id in self.pending
            or (session_id and self.callbacks._hydrate_pending_workflow(user_id, session_id))
        ):
            return self.callbacks._resume_pending_dynamic_workflow(user_id, message, text, context)[
                1
            ]
        # Every non-control turn goes to the configured model. It returns either
        # a normal reply node or a complete authorized business plan; no local
        # dialogue/business classifier chooses a separate model path.
        return self.callbacks._dispatch_model_selection(
            user_id,
            message,
            source,
            planning_context,
            text,
        )
