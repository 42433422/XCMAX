"""Tolerant JSON parser for LLM responses.

In production we routinely see LLMs (even ``response_format=json_object``
ones) emit slightly broken payloads:

- Wrapped in ``markdown`` fences (``\u0060\u0060\u0060json … \u0060\u0060\u0060``)
- Prefixed with chatter (``"Sure, here's the JSON: { … }"``)
- Trailing commas (``[1, 2, 3,]`` / ``{"a": 1,}``)
- Inline ``// comments`` or ``/* block comments */``
- ASCII single quotes (``{'a': 'b'}``) — illegal JSON
- Smart quotes copy-pasted from a chat UI (``"a"``)
- Truncated tail (``{"a": 1, "b": 2``)
- BOM / zero-width characters at the start
- Multiple JSON objects in a row (chooses the largest valid one)

Every one of these breaks the strict ``json.loads`` we used to call from
``code_factory`` / ``facade`` / ``workflow_factory`` etc, which in
production translated into a ``VibeCodingError`` and a wasted LLM round-trip.
This module's :func:`safe_parse_json` runs a graduated-tolerance pipeline so
we recover from each of those modes without silently mutating semantics.

If recovery is impossible, :exc:`JSONParseError` is raised with the
original text snippet — callers should treat it as a transient LLM error
and (optionally) retry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Unicode bidi/zero-width chars sometimes leak from chat UIs.
_INVISIBLE_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u200e\u200f\u2028\u2029]")
# Smart double / single quotes → ASCII equivalents.
_SMART_QUOTES = {
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u00ab": '"', "\u00bb": '"',
}
# ``//`` line comments and ``/* … */`` block comments — illegal in JSON
# but extremely common in LLM output.
_LINE_COMMENT_RE = re.compile(r"^\s*//[^\n]*\n", re.MULTILINE)
_INLINE_LINE_COMMENT_RE = re.compile(r"(?<![:\\])//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# ``,]`` / ``,}`` — trailing comma fix.
_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")
# Markdown fence variants.
_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json|javascript|js|python|py)?\s*\n?", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")
# JSON-ish keys without quotes (``{a: 1}``) — last-resort fix.
_BARE_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*):", re.MULTILINE)


class JSONParseError(ValueError):
    """Raised when no recovery strategy can decode the LLM output."""

    def __init__(self, message: str, snippet: str = "") -> None:
        super().__init__(message)
        self.snippet = snippet


@dataclass(slots=True)
class _ParseAttempt:
    """Result of one strategy in the graduated parse pipeline."""

    success: bool
    payload: Any = None
    error: str = ""
    strategy: str = ""


def safe_parse_json(raw: str | bytes) -> Any:
    """Parse ``raw`` into a Python object, applying a tolerance pipeline.

    Returns the parsed object (typically a ``dict``) or raises
    :class:`JSONParseError`. Callers that *require* a dict should check
    :func:`isinstance(out, dict)` afterwards.
    """
    if raw is None:
        raise JSONParseError("LLM returned None")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = str(raw or "").strip()
    if not text:
        raise JSONParseError("LLM returned empty response")

    for attempt in _attempts(text):
        if attempt.success:
            return attempt.payload
    raise JSONParseError(
        f"Could not recover JSON from LLM response after exhausting all strategies",
        snippet=text[:400],
    )


def safe_parse_json_object(raw: str | bytes) -> dict[str, Any]:
    """Same as :func:`safe_parse_json` but enforce ``isinstance(out, dict)``."""
    out = safe_parse_json(raw)
    if not isinstance(out, dict):
        raise JSONParseError(
            f"expected JSON object, got {type(out).__name__}",
            snippet=str(out)[:400],
        )
    return out


def extract_first_object(text: str) -> str | None:
    """Return the substring spanning the largest balanced ``{...}`` in ``text``.

    Useful when the LLM puts a JSON object after a paragraph of chatter — we
    walk every ``{`` candidate and return the one whose matching ``}``
    encloses the most content.
    """
    candidates: list[tuple[int, int]] = []
    for start in (i for i, c in enumerate(text) if c == "{"):
        end = _find_matching_brace(text, start)
        if end > start:
            candidates.append((start, end))
    if not candidates:
        return None
    best = max(candidates, key=lambda se: se[1] - se[0])
    return text[best[0] : best[1] + 1]


# ---------------------------------------------------------------------- internals


def _attempts(text: str):
    """Yield :class:`_ParseAttempt` instances in graduated-tolerance order.

    Strategy ordering rationale:

    1. Cheap text rewrites first (fence / comment / comma cleanup) — any of
       these on its own often fixes the payload without touching semantics.
    2. ``auto_closed_braces`` runs *before* ``extracted_object`` because
       extraction would otherwise return a *smaller* nested object that
       happens to be balanced, hiding the real (truncated) outer object.
    3. ``extracted_object`` last for cases where the LLM precedes the JSON
       with prose. We re-apply the cheap cleaners on the extracted span so
       chatter-with-comments still parses.
    """
    yield _try(text, label="raw")

    cleaned = _normalise(text)
    if cleaned != text:
        yield _try(cleaned, label="normalised")

    stripped = _strip_fence(cleaned)
    if stripped and stripped != cleaned:
        yield _try(stripped, label="fence_stripped")

    base = stripped or cleaned

    no_comments = _strip_comments(base)
    if no_comments and no_comments != base:
        yield _try(no_comments, label="comments_stripped")
        base = no_comments

    no_trailing = _strip_trailing_commas(base)
    if no_trailing and no_trailing != base:
        yield _try(no_trailing, label="no_trailing_commas")
        base = no_trailing

    closed = _try_close_truncation(base)
    if closed:
        yield _try(closed, label="auto_closed_braces")

    closed_strings = _try_close_truncated_string(base)
    if closed_strings:
        yield _try(closed_strings, label="auto_closed_string")

    obj = extract_first_object(base)
    if obj:
        yield _try(obj, label="extracted_object")
        obj_clean = _strip_trailing_commas(_strip_comments(obj))
        if obj_clean != obj:
            yield _try(obj_clean, label="extracted_cleaned")
        obj_closed = _try_close_truncation(obj_clean or obj)
        if obj_closed:
            yield _try(obj_closed, label="extracted_closed")
        obj_string_closed = _try_close_truncated_string(obj_clean or obj)
        if obj_string_closed:
            yield _try(obj_string_closed, label="extracted_string_closed")

    bare_key_fixed = _quote_bare_keys(base)
    if bare_key_fixed != base:
        yield _try(bare_key_fixed, label="bare_keys_quoted")


def _try(text: str, *, label: str) -> _ParseAttempt:
    try:
        return _ParseAttempt(success=True, payload=json.loads(text), strategy=label)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return _ParseAttempt(success=False, error=str(exc), strategy=label)


def _normalise(text: str) -> str:
    text = _INVISIBLE_RE.sub("", text)
    for src, dst in _SMART_QUOTES.items():
        text = text.replace(src, dst)
    return text.strip()


def _strip_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = _FENCE_OPEN_RE.sub("", t, count=1)
    t = _FENCE_CLOSE_RE.sub("", t)
    return t.strip()


def _strip_comments(text: str) -> str:
    """Remove ``//`` and ``/* … */`` comments while preserving string literals.

    The naive approach (regex over the whole text) would corrupt URLs like
    ``"https://x"``. We tokenise into "in-string" vs "out-of-string" runs.
    """
    if "//" not in text and "/*" not in text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in '"\'':
            in_str = True
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                # Skip to newline.
                end = text.find("\n", i + 2)
                if end < 0:
                    return "".join(out)
                i = end
                continue
            if nxt == "*":
                end = text.find("*/", i + 2)
                if end < 0:
                    return "".join(out)
                i = end + 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _quote_bare_keys(text: str) -> str:
    """Quote unquoted object keys (``{a: 1}`` → ``{"a": 1}``).

    This is risky inside string literals, so we only apply it to substrings
    that are NOT inside a quoted span — same string-aware walk as
    :func:`_strip_comments`.
    """
    if not text or "{" not in text:
        return text
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    span_start = 0
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                in_str = False
                spans.append((span_start, i))
            i += 1
            continue
        if c in '"\'':
            in_str = True
            quote = c
            span_start = i
        i += 1
    # Apply the regex only outside string spans.
    last = 0
    for span_start, span_end in spans:
        chunk = text[last:span_start]
        out.append(_BARE_KEY_RE.sub(r'\1"\2"\3:', chunk))
        out.append(text[span_start : span_end + 1])
        last = span_end + 1
    chunk = text[last:]
    out.append(_BARE_KEY_RE.sub(r'\1"\2"\3:', chunk))
    return "".join(out)


def _try_close_truncation(text: str) -> str | None:
    """Append the right number of ``]`` / ``}`` to close a truncated payload.

    Counts unbalanced openers (ignoring quoted spans) and appends matching
    closers in LIFO order. Returns ``None`` if the text already balances or
    appears too broken to repair this way.
    """
    stack: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in '"\'':
            in_str = True
            quote = c
            i += 1
            continue
        if c in "{[":
            stack.append(c)
        elif c in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener, c) not in {("{", "}"), ("[", "]")}:
                return None
        i += 1
    if not stack:
        return None
    closers = "".join("}" if o == "{" else "]" for o in reversed(stack))
    return text + closers


def _try_close_truncated_string(text: str) -> str | None:
    """Close a payload cut off while inside a JSON string, then close braces.

    Token limits often truncate after a key or a string value, e.g.
    ``{"items": [{"id": "abc``.  Appending a quote plus matching ``]``/``}``
    can recover the outer structure so downstream schema normalisation can
    decide whether the partial field is usable.
    """
    stack: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in '"\'':
            in_str = True
            quote = c
            i += 1
            continue
        if c in "{[":
            stack.append(c)
        elif c in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener, c) not in {("{", "}"), ("[", "]")}:
                return None
        i += 1
    if not in_str:
        return None
    closers = "".join("}" if o == "{" else "]" for o in reversed(stack))
    return text + quote + closers


def _find_matching_brace(text: str, start: int) -> int:
    """Return the index of the ``}`` that matches the ``{`` at ``start``.

    Returns ``-1`` if no match is found. Honours string literals so braces
    inside ``"…"`` don't confuse the counter.
    """
    if start < 0 or start >= len(text) or text[start] != "{":
        return -1
    depth = 0
    in_str = False
    quote = ""
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in '"\'':
            in_str = True
            quote = c
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


__all__ = [
    "JSONParseError",
    "extract_first_object",
    "safe_parse_json",
    "safe_parse_json_object",
]
