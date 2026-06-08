from __future__ import annotations

from typing import Protocol

from modstore_server.domain.wallet.types import WalletBalance


class WalletRepository(Protocol):
    def balance(self, user_id: int) -> WalletBalance: ...


__all__ = ["WalletRepository"]
