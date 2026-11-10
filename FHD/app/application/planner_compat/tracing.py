"""Per-turn trace ownership and legacy run completion."""

from __future__ import annotations

from dataclasses import dataclass

from .protocols import ChatTrace, ChatTurn, Context, Payload


@dataclass
class TurnTrace:
    turn: ChatTurn
    context: Context
    ports: ChatTrace

    def attach(self, payload: Payload, *, mainline: bool = False) -> Payload:
        return self.ports.attach(
            payload,
            self.turn.body,
            message=self.turn.message,
            runtime_context=self.context,
            channel=self.turn.channel + ("_mainline" if mainline else ""),
        )
