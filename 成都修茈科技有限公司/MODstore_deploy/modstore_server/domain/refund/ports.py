from __future__ import annotations

from typing import Protocol

from modstore_server.domain.refund.types import RefundRequestRef


class RefundRepository(Protocol):
    def get(self, refund_id: int) -> RefundRequestRef | None: ...


__all__ = ["RefundRepository"]
