from __future__ import annotations

from modstore_server.domain.wallet.types import WalletBalance


class InMemoryWalletRepository:
    def __init__(self, balances: dict[int, int] | None = None) -> None:
        self._b = dict(balances or {})

    def balance(self, user_id: int) -> WalletBalance:
        return WalletBalance(user_id=user_id, amount_cents=int(self._b.get(user_id, 0)))


__all__ = ["InMemoryWalletRepository"]
