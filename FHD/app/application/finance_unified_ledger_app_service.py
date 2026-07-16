"""Application facade for self-hosted unified finance ledger."""

from __future__ import annotations

from typing import Any


def list_ledger(
    *,
    market_user_id: int | None = None,
    track: str | None = None,
    limit: int = 200,
) -> list[Any]:
    from app.services.finance_unified_archive import list_ledger as impl

    return impl(market_user_id=market_user_id, track=track, limit=limit)


def summarize_ledger(*, market_user_id: int | None = None) -> dict[str, Any]:
    from app.services.finance_unified_archive import summarize_ledger as impl

    return impl(market_user_id=market_user_id)


def rebuild_ledger_archive(*, market_user_id: int | None = None) -> dict[str, Any]:
    from app.services.finance_unified_archive import rebuild_ledger_archive as impl

    return impl(market_user_id=market_user_id)


__all__ = ["list_ledger", "rebuild_ledger_archive", "summarize_ledger"]
