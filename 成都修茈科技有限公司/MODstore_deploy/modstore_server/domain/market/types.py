from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSearchQuery:
    q: str = ""
    limit: int = 20


@dataclass(frozen=True)
class MarketListing:
    item_id: str
    title: str
