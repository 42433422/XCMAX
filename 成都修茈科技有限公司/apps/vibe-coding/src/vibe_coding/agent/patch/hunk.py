"""The :class:`Hunk` data model — a precise, anchored, replace-only edit.

Why anchors instead of line numbers? Line numbers are the easiest contract to
break: any unrelated change earlier in the file silently invalidates the
patch. Anchors (≥3 lines of unchanged context before and after the change)
plus an exact ``old_text`` give us:

- Fuzzy locatability (the applier can scan ±N lines if the anchors moved)
- A lossless inverse (``new_text`` → ``old_text``) for rollback
- A natural "minimum unit of change" so LLMs don't drift into rewriting
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class Hunk:
    """A single replace-only edit anchored on surrounding context.

    Fields:

    - ``anchor_before`` — lines immediately preceding ``old_text`` (≥1 line
      recommended; empty only when editing the very first line of a file).
    - ``anchor_after`` — lines immediately following ``old_text`` (same rule).
    - ``old_text`` — the exact substring being replaced (must already exist
      verbatim in the file).
    - ``new_text`` — the replacement.
    - ``description`` — human-readable purpose; surfaces in patch summaries.

    Anchors and ``old_text`` are stored verbatim including whitespace and line
    endings; the applier handles normalisation.
    """

    anchor_before: str
    old_text: str
    new_text: str
    anchor_after: str
    description: str = ""

    def is_pure_insertion(self) -> bool:
        return not self.old_text and bool(self.new_text)

    def is_pure_deletion(self) -> bool:
        return bool(self.old_text) and not self.new_text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Hunk:
        return cls(
            anchor_before=str(raw.get("anchor_before") or ""),
            old_text=str(raw.get("old_text") or ""),
            new_text=str(raw.get("new_text") or ""),
            anchor_after=str(raw.get("anchor_after") or ""),
            description=str(raw.get("description") or ""),
        )


__all__ = ["Hunk"]
