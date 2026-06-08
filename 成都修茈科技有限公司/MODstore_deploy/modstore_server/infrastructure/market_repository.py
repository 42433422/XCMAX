"""Market listing adapter (占位，可接 ``market_shared``)."""

from __future__ import annotations

from modstore_server.domain.market.types import MarketListing, MarketSearchQuery


class InMemoryMarketBrowseRepository:
    def search(self, query: MarketSearchQuery) -> list[MarketListing]:
        return [MarketListing(item_id="demo", title=query.q or "demo")]


__all__ = ["InMemoryMarketBrowseRepository"]
