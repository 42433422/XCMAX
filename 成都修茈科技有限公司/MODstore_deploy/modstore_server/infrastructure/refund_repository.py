from __future__ import annotations

from modstore_server.domain.refund.types import RefundRequestRef, RefundStatus


class InMemoryRefundRepository:
    def __init__(self, rows: dict[int, RefundRequestRef] | None = None) -> None:
        self._rows = dict(rows or {})

    def get(self, refund_id: int) -> RefundRequestRef | None:
        return self._rows.get(refund_id)


__all__ = ["InMemoryRefundRepository"]
