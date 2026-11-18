"""Dataset synonym groups used for query expansion at retrieval time."""

from __future__ import annotations

from typing import Any

MAX_SYNONYM_GROUPS = 200
MAX_SYNONYM_TERM_CHARS = 32
MAX_SYNONYM_EXPANSIONS = 10


def normalize_synonyms(raw: Any) -> dict[str, list[str]]:
    """Validate and bound a ``{term: [expansion, ...]}`` mapping.

    Terms are the words users type; expansions are the words the corpus uses.
    Blank values and duplicates are dropped instead of raising so an editor can
    save incrementally, but the shape must stay a mapping of short strings.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("synonyms must be a mapping of term -> expansions")
    cleaned: dict[str, list[str]] = {}
    for term, values in raw.items():
        key = str(term or "").strip()
        if not key:
            continue
        if len(key) > MAX_SYNONYM_TERM_CHARS:
            raise ValueError(f"synonym term too long: {key[:16]}…")
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"synonym expansions for {key} must be a list")
        expansions: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and len(text) <= MAX_SYNONYM_TERM_CHARS and text not in expansions:
                expansions.append(text)
            if len(expansions) >= MAX_SYNONYM_EXPANSIONS:
                break
        if expansions:
            cleaned[key] = expansions
        if len(cleaned) >= MAX_SYNONYM_GROUPS:
            break
    return cleaned


def expand_query(query: str, synonyms: Any) -> str:
    """Append corpus-side synonyms for terms the query already mentions."""
    groups = synonyms if isinstance(synonyms, dict) else {}
    if not query or not groups:
        return query
    appended: list[str] = []
    for term, expansions in groups.items():
        key = str(term or "")
        if not key or key not in query or not isinstance(expansions, (list, tuple)):
            continue
        for value in expansions:
            text = str(value or "").strip()
            if text and text not in query and text not in appended:
                appended.append(text)
    return f"{query} {' '.join(appended)}" if appended else query
