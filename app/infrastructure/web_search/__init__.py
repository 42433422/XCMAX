"""Pluggable web search for kitten analyzer and similar features."""

from app.infrastructure.web_search.service import kitten_web_search, WebSearchHit

__all__ = ["kitten_web_search", "WebSearchHit"]
