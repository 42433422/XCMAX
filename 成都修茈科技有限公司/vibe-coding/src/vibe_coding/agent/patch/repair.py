"""Cascading hunk-application strategies for LLM-supplied patches.

The single-skill repair loop (``code_factory._apply_hunks_inline``) and
the multi-file :class:`PatchApplier` both face the same problem: an LLM-
returned hunk is *almost* correct, but anchor whitespace or surrounding
context drifted by one line. Without a fallback the patch is rejected and
the LLM has to spend another round-trip on the same fix.

This module ships a single :func:`apply_hunks_to_source` entry point that
tries the strategies below, in order, until one succeeds:

1. **strict** — ``anchor_before + old_text + anchor_after`` matches verbatim.
2. **anchors_only** — ``anchor_before + anchor_after`` (zero-width old_text)
   for pure insertions.
3. **fuzzy_anchors** — ``anchor_before`` and ``anchor_after`` both appear
   within ``fuzzy_lines`` lines of each other and ``old_text`` lives between
   them. Lines outside the anchors can drift freely.
4. **unique_old_text** — ``old_text`` itself appears exactly once anywhere
   in the file. Anchors are advisory.
5. **stripped_old_text** — ``old_text`` matches modulo leading-whitespace
   differences (LLMs love to indent two spaces instead of four).
6. **anchor_only_insertion** — pure insertion (no ``old_text``) anchored
   on ``anchor_after`` only.

Returns a :class:`HunkApplyOutcome` with the new source plus the strategy
used per hunk so callers can record it (telemetry, telemetry, telemetry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .hunk import Hunk

DEFAULT_FUZZY_LINES = 10


@dataclass(slots=True)
class HunkApplyError(ValueError):
    """Raised when no strategy could locate a hunk."""

    hunk_index: int = -1
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.args:
            self.args = (f"hunk[{self.hunk_index}]: {self.reason}",)


@dataclass(slots=True)
class HunkApplyResult:
    """Per-hunk outcome."""

    index: int
    strategy: str
    success: bool
    reason: str = ""


@dataclass(slots=True)
class HunkApplyOutcome:
    """Aggregated result of applying a list of hunks to a source string."""

    source: str
    results: list[HunkApplyResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return bool(self.results) and all(r.success for r in self.results)

    @property
    def strategies_used(self) -> list[str]:
        return [r.strategy for r in self.results if r.success]


def apply_hunks_to_source(
    source: str,
    hunks: Iterable[Hunk | dict],
    *,
    fuzzy_lines: int = DEFAULT_FUZZY_LINES,
    raise_on_failure: bool = True,
) -> HunkApplyOutcome:
    """Try to apply every hunk to ``source`` using the cascade above.

    ``raise_on_failure=True`` (default) raises :class:`HunkApplyError` on the
    first hunk that no strategy can place. Set to ``False`` to record the
    failure in :attr:`HunkApplyResult.success` and continue with the rest —
    useful for "best-effort" callers that prefer partial application.
    """
    text = source
    results: list[HunkApplyResult] = []
    for idx, raw in enumerate(hunks):
        hunk = _coerce_hunk(raw)
        new_text, strategy, error = _apply_one(text, hunk, fuzzy_lines=fuzzy_lines)
        if strategy:
            text = new_text
            results.append(HunkApplyResult(index=idx, strategy=strategy, success=True))
            continue
        results.append(
            HunkApplyResult(index=idx, strategy="", success=False, reason=error or "no strategy matched")
        )
        if raise_on_failure:
            raise HunkApplyError(hunk_index=idx, reason=error or "no strategy matched")
    return HunkApplyOutcome(source=text, results=results)


# ---------------------------------------------------------------------- helpers


def _coerce_hunk(raw: Hunk | dict) -> Hunk:
    if isinstance(raw, Hunk):
        return raw
    if isinstance(raw, dict):
        return Hunk.from_dict(raw)
    raise HunkApplyError(hunk_index=-1, reason=f"unsupported hunk type {type(raw).__name__}")


def _apply_one(
    text: str,
    hunk: Hunk,
    *,
    fuzzy_lines: int,
) -> tuple[str, str, str]:
    """Try every strategy; return ``(new_text, strategy, error)``.

    On failure ``strategy`` is the empty string and ``error`` carries a short
    diagnostic.
    """
    # Strategy 1: strict
    if hunk.anchor_before or hunk.old_text or hunk.anchor_after:
        candidate = hunk.anchor_before + hunk.old_text + hunk.anchor_after
        replacement = hunk.anchor_before + hunk.new_text + hunk.anchor_after
        if candidate and candidate in text:
            return text.replace(candidate, replacement, 1), "strict", ""

    # Strategy 2: anchors_only — pure insertion at anchor boundary
    if not hunk.old_text and hunk.anchor_before and hunk.anchor_after:
        joint = hunk.anchor_before + hunk.anchor_after
        if joint in text:
            replacement = hunk.anchor_before + hunk.new_text + hunk.anchor_after
            return text.replace(joint, replacement, 1), "anchors_only", ""

    # Strategy 3: fuzzy anchors — anchors within ``fuzzy_lines`` window
    if hunk.old_text:
        new_text, ok = _fuzzy_anchor_replace(text, hunk, fuzzy_lines=fuzzy_lines)
        if ok:
            return new_text, "fuzzy_anchors", ""

    # Strategy 4: unique old_text replacement
    if hunk.old_text and text.count(hunk.old_text) == 1:
        return text.replace(hunk.old_text, hunk.new_text, 1), "unique_old_text", ""

    # Strategy 5: stripped old_text (ignore leading-whitespace differences)
    if hunk.old_text:
        new_text, ok = _stripped_old_text_replace(text, hunk)
        if ok:
            return new_text, "stripped_old_text", ""

    # Strategy 6: anchor_after-only insertion
    if not hunk.old_text and hunk.new_text:
        if hunk.anchor_after and hunk.anchor_after in text:
            pos = text.find(hunk.anchor_after)
            return text[:pos] + hunk.new_text + text[pos:], "anchor_after_insertion", ""
        if not hunk.anchor_after and not hunk.anchor_before:
            return text + hunk.new_text, "append", ""

    return "", "", "anchors and old_text could not be located"


def _fuzzy_anchor_replace(
    text: str,
    hunk: Hunk,
    *,
    fuzzy_lines: int,
) -> tuple[str, bool]:
    """Locate ``old_text`` whose neighbouring anchors appear within ``fuzzy_lines``.

    The LLM may have copied the ``anchor_before`` / ``anchor_after`` from a
    slightly different version of the file, so they sit a few lines off but
    still uniquely identify the change. We accept any occurrence of
    ``old_text`` whose surrounding lines contain the anchor blocks within
    the fuzzy window.
    """
    if not hunk.old_text:
        return "", False
    pos = -1
    while True:
        pos = text.find(hunk.old_text, pos + 1)
        if pos < 0:
            return "", False
        prefix = text[:pos]
        suffix = text[pos + len(hunk.old_text) :]
        if hunk.anchor_before:
            tail_lines = prefix.splitlines()[-(fuzzy_lines + 5) :]
            tail = "\n".join(tail_lines)
            anchor_b = hunk.anchor_before.rstrip("\n")
            if anchor_b.strip() and anchor_b not in tail:
                continue
        if hunk.anchor_after:
            head_lines = suffix.splitlines()[: fuzzy_lines + 5]
            head = "\n".join(head_lines)
            anchor_a = hunk.anchor_after.rstrip("\n")
            if anchor_a.strip() and anchor_a not in head:
                continue
        return prefix + hunk.new_text + suffix, True


def _stripped_old_text_replace(text: str, hunk: Hunk) -> tuple[str, bool]:
    """Match ``old_text`` ignoring per-line leading-whitespace differences.

    We do this line-by-line: walk every starting line in ``text`` whose
    first old-line stripped matches the first old-line of the hunk, and
    check the rest follow with the same stripped equivalence. On match we
    replace using the *file's* indentation prefix so the inserted code stays
    aligned with the surrounding block.
    """
    old_lines = hunk.old_text.splitlines(keepends=True)
    new_lines = hunk.new_text.splitlines(keepends=True)
    if not old_lines:
        return "", False
    text_lines = text.splitlines(keepends=True)
    needle_first_stripped = old_lines[0].lstrip()
    needle_count = len(old_lines)
    matches: list[int] = []
    for i in range(len(text_lines) - needle_count + 1):
        candidate = text_lines[i]
        if candidate.lstrip() != needle_first_stripped:
            continue
        if all(
            text_lines[i + j].lstrip() == old_lines[j].lstrip()
            for j in range(needle_count)
        ):
            matches.append(i)
    if len(matches) != 1:
        return "", False
    start = matches[0]
    # Detect the file's indent by comparing first matched line's leading
    # whitespace to the hunk's leading whitespace.
    file_indent = text_lines[start][: len(text_lines[start]) - len(text_lines[start].lstrip())]
    hunk_indent = old_lines[0][: len(old_lines[0]) - len(old_lines[0].lstrip())]
    if hunk_indent and file_indent.startswith(hunk_indent) and file_indent != hunk_indent:
        extra = file_indent[len(hunk_indent) :]
        new_lines = [extra + line if line.strip() else line for line in new_lines]
    elif not hunk_indent and file_indent:
        new_lines = [file_indent + line if line.strip() else line for line in new_lines]
    rebuilt = (
        "".join(text_lines[:start])
        + "".join(new_lines)
        + "".join(text_lines[start + needle_count :])
    )
    return rebuilt, True


__all__ = [
    "HunkApplyError",
    "HunkApplyOutcome",
    "HunkApplyResult",
    "apply_hunks_to_source",
]
