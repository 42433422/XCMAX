"""Prepare context for the single model-selected reply or business plan."""

from __future__ import annotations

from typing import Any, Protocol


class ImportAdmissionCallbacks(Protocol):
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
        # One dispatcher owns resume, task switching and model admission for
        # both controls and free text; internal continuation markers stay there.
        return self.callbacks._dispatch_model_selection(
            user_id,
            message,
            source,
            planning_context,
            text,
        )
