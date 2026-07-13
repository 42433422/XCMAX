"""Small, linear-time HTML-to-text helpers for untrusted chat content."""

from __future__ import annotations

from html.parser import HTMLParser


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")


def html_to_plain_text(value: object, *, max_chars: int = 100_000) -> str:
    """Return visible text without applying a backtracking regex to input HTML."""

    parser = _PlainTextParser()
    parser.feed(str(value or "")[:max_chars])
    parser.close()
    return "".join(parser.parts)


__all__ = ["html_to_plain_text"]
