from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RefundStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class RefundRequestRef:
    refund_id: int
    status: RefundStatus
