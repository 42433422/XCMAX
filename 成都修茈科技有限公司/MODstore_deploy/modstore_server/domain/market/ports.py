from __future__ import annotations

from typing import Protocol

from modstore_server.domain.market.types import MarketListing, MarketSearchQuery


class MarketBrowseRepository(Protocol):
    def search(self, query: MarketSearchQuery) -> list[MarketListing]: ...


__all__ = ["MarketBrowseRepository"]
