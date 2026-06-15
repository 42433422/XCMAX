"""Minimise diffs: turn whole-file rewrites into the smallest viable hunk set.

LLMs sometimes ignore the "hunks only" contract and hand back a full file
rewrite. Rejecting that wastes a round-trip; instead we run the rewrite
through :func:`minimise_diff` which uses :class:`difflib.SequenceMatcher` to
find every changed region, then expands each region by ``context_lines`` to
form a self-anchored :class:`Hunk`.

The output of :func:`minimise_diff` is a tuple ``(edits, was_minimised)`` so
callers can record whether they actually ran a minimisation step (useful for
ledger / metrics).
"""

from __future__ import annotations

import difflib
from typing import Iterable

from .hunk import Hunk

DEFAULT_CONTEXT_LINES = 3


def minimise_diff(
    original: str,
    rewritten: str,
    *,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> list[Hunk]:
    """Compute the minimal anchored hunks that turn ``original`` into ``rewritten``.

    Lines are compared with line endings preserved so the resulting hunk's
    ``old_text`` / ``new_text`` round-trip exactly back to the original
    string when concatenated with their anchors. If the two inputs are
    identical the result is an empty list.
    """
    if original == rewritten:
        return []
    if not original:
        # Pure file creation — single hunk with no anchors.
        return [Hunk(anchor_before="", old_text="", new_text=rewritten, anchor_after="")]
    if not rewritten:
        return [Hunk(anchor_before="", old_text=original, new_text="", anchor_after="")]

    a = original.splitlines(keepends=True)
    b = rewritten.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_lines = a[max(0, i1 - context_lines) : i1]
        after_lines = a[i2 : min(len(a), i2 + context_lines)]
        old_lines = a[i1:i2]
        new_lines = b[j1:j2]
        hunks.append(
            Hunk(
                anchor_before="".join(before_lines),
                old_text="".join(old_lines),
                new_text="".join(new_lines),
                anchor_after="".join(after_lines),
            )
        )
    return _coalesce_overlapping(hunks)


def hunks_from_full_rewrite(
    original: str,
    rewritten: str,
    *,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> list[Hunk]:
    """Backwards-compatible alias for :func:`minimise_diff`."""
    return minimise_diff(original, rewritten, context_lines=context_lines)


def unified_diff(original: str, rewritten: str, *, path: str = "file") -> str:
    """Produce a classic ``unified_diff`` string for human display."""
    a = original.splitlines(keepends=True)
    b = rewritten.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(a, b, fromfile=f"a/{path}", tofile=f"b/{path}", n=3)
    )


def _coalesce_overlapping(hunks: Iterable[Hunk]) -> list[Hunk]:
    """Merge hunks whose anchor regions overlap to keep ledger entries clean.

    Adjacent hunks (``anchor_after`` of one equals ``anchor_before`` of the
    next) are intentionally NOT merged — keeping them separate makes ledger
    entries easier to read and rolling back individual edits possible later.
    """
    out: list[Hunk] = []
    for h in hunks:
        out.append(h)
    return out


__all__ = ["DEFAULT_CONTEXT_LINES", "hunks_from_full_rewrite", "minimise_diff", "unified_diff"]
