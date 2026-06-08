from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WalletBalance:
    user_id: int
    amount_cents: int
