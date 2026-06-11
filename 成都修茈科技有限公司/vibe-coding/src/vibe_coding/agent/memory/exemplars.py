"""Exemplar store: validated ProjectPatch records for few-shot retrieval.

P2 enhancements:

- **Outcome tracking** — every entry records ``outcome`` (``success`` or
  ``failure``) so the LLM prompt can show "good examples to follow" *and*
  "bad attempts to avoid". Failures carry the ``error`` and ``tools_failed``
  fields verbatim from the heal loop.
- **Timestamps** — ``created_at`` and ``last_used_at`` (Unix epoch seconds)
  drive recency-aware pruning. ``last_used_at`` is bumped every time a
  retriever returns the exemplar in its top-K.
- **Tags + metadata** — free-form fields the caller can use for downstream
  filtering (``"refactor"`` / ``"performance"`` / ``"i18n"`` …).
- **Pruning** — :meth:`ExemplarStore.prune` keeps memory bounded with a
  least-recently-used + oldest-first eviction; the standard
  :class:`ProjectMemory` calls it automatically on :meth:`record_success`
  and :meth:`record_failure` once the store exceeds its budget.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal
from uuid import uuid4

Outcome = Literal["success", "failure"]


@dataclass
class Exemplar:
    """A single recorded patch outcome."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    brief: str = ""
    patch_id: str = ""
    summary: str = ""
    diff_text: str = ""
    tools_passed: list[str] = field(default_factory=list)
    tools_failed: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    outcome: Outcome = "success"
    error: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "brief": self.brief,
            "patch_id": self.patch_id,
            "summary": self.summary,
            "diff_text": self.diff_text,
            "tools_passed": list(self.tools_passed),
            "tools_failed": list(self.tools_failed),
            "languages": list(self.languages),
            "outcome": self.outcome,
            "error": self.error,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": float(self.created_at),
            "last_used_at": float(self.last_used_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Exemplar":
        outcome = str(raw.get("outcome") or "success")
        if outcome not in ("success", "failure"):
            outcome = "success"
        return cls(
            id=str(raw.get("id") or uuid4().hex[:12]),
            brief=str(raw.get("brief") or ""),
            patch_id=str(raw.get("patch_id") or ""),
            summary=str(raw.get("summary") or ""),
            diff_text=str(raw.get("diff_text") or ""),
            tools_passed=[str(x) for x in raw.get("tools_passed") or []],
            tools_failed=[str(x) for x in raw.get("tools_failed") or []],
            languages=[str(x) for x in raw.get("languages") or []],
            outcome=outcome,  # type: ignore[arg-type]
            error=str(raw.get("error") or ""),
            tags=[str(x) for x in raw.get("tags") or []],
            metadata=dict(raw.get("metadata") or {}),
            created_at=float(raw.get("created_at") or time.time()),
            last_used_at=float(raw.get("last_used_at") or 0.0),
        )

    def search_text(self) -> str:
        """Flat text for tokenisation / BM25 scoring.

        Includes summary, brief, the first ~500 chars of the diff and any
        tags so retrieval can find by topic without dragging the whole
        diff body into the BM25 index.
        """
        tag_text = " ".join(self.tags)
        return f"{self.brief} {self.summary} {tag_text} {self.diff_text[:500]}"

    def touch(self) -> None:
        """Update ``last_used_at`` to mark the exemplar as recently retrieved."""
        self.last_used_at = time.time()


class ExemplarStore:
    """In-memory log of recorded exemplars; flushed to disk via :class:`ProjectMemory`."""

    def __init__(self, exemplars: list[Exemplar] | None = None) -> None:
        self._data: list[Exemplar] = list(exemplars or [])

    def add(self, exemplar: Exemplar) -> None:
        self._data.append(exemplar)

    def all(self) -> list[Exemplar]:
        return list(self._data)

    def successes(self) -> list[Exemplar]:
        return [e for e in self._data if e.outcome == "success"]

    def failures(self) -> list[Exemplar]:
        return [e for e in self._data if e.outcome == "failure"]

    def filter_by_tag(self, tag: str) -> list[Exemplar]:
        return [e for e in self._data if tag in e.tags]

    def __len__(self) -> int:
        return len(self._data)

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._data]

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> "ExemplarStore":
        return cls([Exemplar.from_dict(d) for d in data if isinstance(d, dict)])

    def prune(
        self,
        max_items: int,
        *,
        strategy: Literal["lru", "oldest", "failures_first"] = "lru",
    ) -> int:
        """Cap the store at ``max_items``; return the number removed.

        ``lru`` (default) — drop the entries with the oldest
        ``last_used_at`` (falling back to ``created_at`` for never-touched
        entries). Most recently retrieved exemplars survive.

        ``oldest`` — drop the entries with the oldest ``created_at`` first
        regardless of usage. Useful for time-bounded windows.

        ``failures_first`` — drop ``outcome="failure"`` entries first
        (least-recently-used within), then successes (least-recently-used).
        Use when failure exemplars are "training noise" you want pruned
        more aggressively than successful patterns.
        """
        if max_items <= 0:
            removed = len(self._data)
            self._data = []
            return removed
        if len(self._data) <= max_items:
            return 0
        if strategy == "oldest":
            self._data.sort(key=lambda e: e.created_at)
        elif strategy == "failures_first":
            self._data.sort(
                key=lambda e: (
                    0 if e.outcome == "failure" else 1,
                    max(e.last_used_at, e.created_at),
                )
            )
        else:  # lru
            self._data.sort(key=lambda e: max(e.last_used_at, e.created_at))
        excess = len(self._data) - max_items
        dropped, kept = self._data[:excess], self._data[excess:]
        self._data = kept
        return len(dropped)

    def replace(self, items: Iterable[Exemplar]) -> None:
        """Replace the in-memory list — used for advanced pruning workflows."""
        self._data = list(items)


__all__ = ["Exemplar", "ExemplarStore", "Outcome"]
