"""HTML-to-text conversion with parser-enforced script/style suppression."""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _PlainTextParser(HTMLParser):
    """Collect visible text without regex-based HTML filtering."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._suppressed_tags: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"}:
            self._suppressed_tags.append(normalized)

    def handle_startendtag(self, tag: str, attrs) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self._suppressed_tags and normalized == self._suppressed_tags[-1]:
            self._suppressed_tags.pop()

    def handle_data(self, data: str) -> None:
        if not self._suppressed_tags:
            self._chunks.append(data)

    def result(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def html_to_plain_text(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value or "")
    parser.close()
    return parser.result()


__all__ = ["html_to_plain_text"]
