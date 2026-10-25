"""Authenticated context preparation and ordered planner preconditions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from .protocols import ChatTurn, Context, Payload, ReadAuthorization, ReplyFormatter


@dataclass(frozen=True)
class AdmissionResult:
    payload: Payload | None = None
    context_update: Context | None = None


@dataclass(frozen=True)
class ChatAdmission:
    merge_paths: Callable[[Context | None, str], tuple[Context, list[str]]]
    authenticate: Callable[[Request, Context | None], Context]
    with_tier: Callable[[Context | None, str], Context]
    authorize_read: ReadAuthorization
    requires_read: Callable[[str], bool]
    interrupt: Callable[[str], str | None]
    after_interrupt: Callable[[Context | None], Context]
    vector_guard: Callable[[str, Context], str | None]
    reply: ReplyFormatter

    def context(self, request: Request, context: Context | None, message: str) -> Context:
        merged, _ = self.merge_paths(context, message)
        return self.authenticate(request, merged)

    def check(self, request: Request, turn: ChatTurn) -> AdmissionResult:
        allowed, required = self.authorize_read(
            request, message=turn.message, provided_token=turn.body.db_read_token
        )
        if not allowed and required:
            return AdmissionResult(
                {
                    "success": True,
                    "requires_token": True,
                    "token_name": required.get("token_name"),
                    "token_description": required.get("token_description"),
                    "message": required.get("message"),
                    "response": required.get("message"),
                    "data": {
                        "requires_token": True,
                        "token_name": required.get("token_name"),
                        "token_description": required.get("token_description"),
                    },
                }
            )
        if allowed and self.requires_read(turn.message):
            turn.context["chat_db_read_authorized"] = True
        interrupt_reply = self.interrupt(turn.message)
        if interrupt_reply is not None:
            cleared = self.after_interrupt(turn.context)
            return AdmissionResult(
                self.reply(
                    interrupt_reply,
                    runtime_context_update=cleared,
                    kitten_attachments=turn.kitten_extra,
                ),
                context_update=cleared,
            )
        error = self.vector_guard(turn.message, turn.context)
        if error:
            return AdmissionResult(self.reply(error, kitten_attachments=turn.kitten_extra))
        return AdmissionResult()
