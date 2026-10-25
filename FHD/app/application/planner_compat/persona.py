"""Host session identity, industry selection and stream persona enrichment."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from logging import Logger
from typing import Any, Protocol

from fastapi import Request

from app.fastapi_routes.xcagi_compat_chat_models import XcagiCompatChatBody
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import Context

BINARY_CONTEXT_KEYS = frozenset(
    {
        "base64",
        "data_url",
        "dataurl",
        "file_bytes",
        "image_base64",
        "image_data",
        "pdf_base64",
        "raw_bytes",
    }
)


class ConversationState(Protocol):
    @property
    def conversation_history(self) -> list[dict[str, Any]]: ...


class PersonaService(Protocol):
    async def build_prompt_from_message(
        self,
        *,
        user_id: str,
        message: str,
        history: list[dict[str, Any]],
        industry: str,
        context_prompt: str,
    ) -> tuple[str, Any]: ...


class ConversationService(Protocol):
    @property
    def contexts(self) -> Mapping[str, ConversationState]: ...

    @property
    def persona_service(self) -> PersonaService | None: ...


def request_session_candidates(
    request: Request, compatibility_session: Callable[[Request], str | None], logger: Logger
) -> list[str]:
    """Prefer explicit host sessions over a compatibility market bearer."""
    candidates: list[str] = []

    def append(raw: Any) -> None:
        value = raw.strip() if isinstance(raw, str) else ""
        if value and value not in candidates:
            candidates.append(value)

    headers = getattr(request, "headers", {}) or {}
    cookies = getattr(request, "cookies", {}) or {}
    try:
        append(headers.get("X-Session-ID"))
    except (AttributeError, TypeError):
        pass
    cookie_name = (os.environ.get("SESSION_COOKIE_NAME") or "session_id").strip()
    try:
        append(cookies.get(cookie_name))
    except (AttributeError, TypeError):
        pass
    try:
        append(compatibility_session(request))
    except RECOVERABLE_ERRORS:
        logger.debug("planner session candidate extraction failed", exc_info=True)
    return candidates


@dataclass(frozen=True)
class IndustryResolver:
    sessions: Callable[[Request], list[str]]
    account_meta: Callable[[str], Context]
    workspace_prefs: Callable[[str], Context]
    user_industry: Callable[[Any], str | None]
    logger: Logger

    def resolve(self, request: Request) -> str:
        state_raw = getattr(getattr(request, "state", None), "industry_id", "")
        state_industry = state_raw.strip() if isinstance(state_raw, str) else ""
        if state_industry == "管理端":
            return "管理端"
        try:
            meta: Context = {}
            for session in self.sessions(request):
                candidate = self.account_meta(session) or {}
                if candidate:
                    meta = candidate
                    break
            if meta.get("account_kind") == "admin":
                return "管理端"
            if state_industry and state_industry != "通用":
                return state_industry
            tenant = meta.get("tenant_id")
            user = meta.get("local_user_id")
            owner = ""
            if tenant is not None and str(tenant).strip().isdigit():
                owner = f"tenant:{int(tenant)}"
            elif user is not None and str(user).strip().isdigit():
                owner = f"session:{int(user)}"
            if owner:
                selected = str(
                    self.workspace_prefs(owner).get("selected_industry_id") or ""
                ).strip()
                if selected:
                    return selected
            if user:
                industry = self.user_industry(user)
                if industry is not None:
                    return industry
        except RECOVERABLE_ERRORS:
            self.logger.debug("derive_industry_from_session failed", exc_info=True)
        return state_industry or "通用"


def summarize_context_for_log(
    value: Any, *, key: str = "", depth: int = 0, binary_keys: frozenset[str] = BINARY_CONTEXT_KEYS
) -> Any:
    if depth >= 5:
        return "<nested-context>"
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, str):
        normalized_key = key.lower().replace("-", "_")
        if value.startswith("data:"):
            header, separator, payload = value.partition(",")
            return f"<{header[:96]} payload_chars={len(payload) if separator else 0}>"
        if normalized_key in binary_keys:
            return f"<redacted-binary chars={len(value)}>"
        return f"{value[:160]}… <text_chars={len(value)}>" if len(value) > 320 else value
    if isinstance(value, dict):
        items = list(value.items())
        summary = {
            str(k): summarize_context_for_log(
                v, key=str(k), depth=depth + 1, binary_keys=binary_keys
            )
            for k, v in items[:32]
        }
        if len(items) > 32:
            summary["<omitted_keys>"] = len(items) - 32
        return summary
    if isinstance(value, (list, tuple)):
        entries = [
            summarize_context_for_log(item, key=key, depth=depth + 1, binary_keys=binary_keys)
            for item in value[:12]
        ]
        if len(value) > 12:
            entries.append(f"<omitted_items={len(value) - 12}>")
        return entries
    return (
        value
        if isinstance(value, (int, float, bool)) or value is None
        else f"<{type(value).__name__}>"
    )


def recent_history(service: ConversationService, user_id: str) -> list[dict[str, Any]]:
    try:
        contexts = getattr(service, "contexts", None)
        context = contexts.get(user_id) if contexts else None
        history = getattr(context, "conversation_history", None) if context else None
        return list(history) if history else []
    except RECOVERABLE_ERRORS:
        return []


def resolve_chat_user_id(request: Request, body: XcagiCompatChatBody) -> str:
    if body.user_id:
        return str(body.user_id)
    try:
        header = request.headers.get("X-User-Id") or request.headers.get("X-User-ID")
        if header and str(header).strip():
            return str(header).strip()
    except RECOVERABLE_ERRORS:
        pass
    return "1"


@dataclass(frozen=True)
class PersonaEnricher:
    conversation: Callable[[], ConversationService]
    user_id: Callable[[Request, XcagiCompatChatBody], str]
    industry: Callable[[Request], str]
    history: Callable[[ConversationService, str], list[dict[str, Any]]]
    summarize: Callable[[Any], Any]
    logger: Logger

    async def enrich(self, request: Request, body: XcagiCompatChatBody) -> None:
        if body.system_prompt or not body.message:
            return
        try:
            service = self.conversation()
            persona = getattr(service, "persona_service", None)
            self.logger.info(
                "persona_inject check: has_persona=%s msg=%s",
                persona is not None,
                body.message[:50],
            )
            if persona is None:
                return
            user_id = self.user_id(request, body)
            context = body.context or {}
            industry = context.get("industry") if isinstance(context, dict) else None
            industry = industry or self.industry(request)
            history = self.history(service, user_id)
            self.logger.info(
                "persona_inject ctx=%s industry=%s history_len=%d",
                self.summarize(context),
                industry,
                len(history),
            )
            prompt, _ = await persona.build_prompt_from_message(
                user_id=user_id,
                message=body.message,
                history=history,
                industry=industry,
                context_prompt="",
            )
            body.system_prompt = prompt
            self.logger.info("persona_inject OK: prompt_len=%d", len(prompt))
        except RECOVERABLE_ERRORS as exc:
            self.logger.warning("persona_inject FAIL: %s", exc, exc_info=True)
