"""Per-turn trace ownership and legacy run completion."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import ChatTrace, ChatTurn, Context, Payload


@dataclass
class TurnTrace:
    turn: ChatTurn
    context: Context
    ports: ChatTrace
    run_id: str | None = None

    def attach(self, payload: Payload, *, mainline: bool = False) -> Payload:
        return self.ports.attach(
            payload,
            self.turn.body,
            message=self.turn.message,
            runtime_context=self.context,
            channel=self.turn.channel + ("_mainline" if mainline else ""),
        )

    def start(self, logger: Logger) -> None:
        try:
            run = self.ports.start(
                message=self.turn.message,
                runtime_context=self.context,
                user_id=self.turn.body.user_id,
                source=self.turn.body.source,
                channel=self.turn.channel,
            )
            self.run_id = run.run_id
            self.context["run_id"] = self.run_id
            self.context["agent_run_id"] = self.run_id
        except RECOVERABLE_ERRORS:
            logger.debug("legacy planner AgentRun pre-create skipped", exc_info=True)

    def finish(self, payload: Payload) -> Payload:
        if self.run_id is None:
            return self.attach(payload)
        return self.ports.finalize(
            self.run_id,
            payload,
            message=self.turn.message,
            runtime_context=self.context,
            user_id=self.turn.body.user_id,
            source=self.turn.body.source,
            channel=self.turn.channel,
        )
