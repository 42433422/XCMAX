"""Bounded, read-only graph recall over the existing MemoryV2 authority.

A path is evidence of connected recorded assertions, not an inferred fact or
proof of entity identity. Names never bridge different owners/scopes. Only
typed, non-generic entities bridge records; literal attributes are terminals.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from app.application.user_memory.policy import is_recallable_memory

_MAX_VISITS = 160
_NAMED_TYPES = frozenset({"person", "organization", "project", "product", "place"})
_GENERIC = frozenset({"user", "self", "用户", "本人", "公司", "客户", "项目"})
RecordKey = tuple[str, str]
EntityKey = tuple[str, str, str]


def record_key(row: dict[str, Any]) -> RecordKey:
    return str(row.get("scope") or ""), str(row.get("memory_id") or "")


def _entities(row: dict[str, Any]) -> set[EntityKey]:
    value = row.get("value")
    if not isinstance(value, dict):
        return set()
    entities = value.get("entities")
    if not isinstance(entities, list):
        return set()
    scope = record_key(row)[0]
    result: set[EntityKey] = set()
    if not scope:
        return result
    for entity in entities[:6]:
        if not isinstance(entity, dict) or entity.get("role") not in {"subject", "object"}:
            continue
        kind = str(entity.get("type") or "")
        name = str(entity.get("name") or "").strip().casefold()
        if kind in _NAMED_TYPES and 2 <= len(name) <= 160 and name not in _GENERIC:
            result.add((scope, kind, name))
    return result


def _mentions(query: str, name: str) -> bool:
    if re.fullmatch(r"[a-z0-9 _.-]+", name):
        return re.search(r"(?<![a-z0-9_])" + re.escape(name) + r"(?![a-z0-9_])", query) is not None
    return name in query


def relation_paths(
    query: str, rows: list[dict[str, Any]], *, max_hops: int
) -> tuple[dict[RecordKey, list[dict[str, Any]]], bool]:
    """Return shortest evidence paths and whether the traversal exhausted its budget."""
    if max_hops <= 0:
        return {}, False
    depth_limit = min(3, max_hops)
    by_key = {
        record_key(row): row
        for row in rows
        if is_recallable_memory(row) and all(record_key(row))
    }
    links: dict[EntityKey, list[RecordKey]] = defaultdict(list)
    entities_by_record: dict[RecordKey, set[EntityKey]] = {}
    for key, row in sorted(by_key.items()):
        entities = _entities(row)
        entities_by_record[key] = entities
        for entity in sorted(entities):
            links[entity].append(key)
    normalized_query = query.casefold()
    queue: deque[tuple[EntityKey, list[dict[str, Any]]]] = deque(
        (entity, []) for entity in sorted(links) if _mentions(normalized_query, entity[2])
    )
    visited_entities: set[EntityKey] = set()
    paths: dict[RecordKey, list[dict[str, Any]]] = {}
    visits = 0
    while queue:
        entity, prefix = queue.popleft()
        if entity in visited_entities or len(prefix) >= depth_limit:
            continue
        visited_entities.add(entity)
        for key in links[entity]:
            if key in paths:
                continue
            if visits >= _MAX_VISITS:
                return paths, True
            visits += 1
            row = by_key[key]
            path = [
                *prefix,
                {
                    "memory_id": key[1],
                    "scope": key[0],
                    "revision": row.get("revision"),
                    "via_entity": entity[2],
                    "entity_type": entity[1],
                    "statement": row.get("statement"),
                },
            ]
            paths[key] = path
            if len(path) < depth_limit:
                for neighbor in sorted(entities_by_record[key]):
                    if neighbor not in visited_entities:
                        queue.append((neighbor, path))
    return paths, False


def parse_as_of(value: str) -> datetime:
    """Reject naive or invalid timestamps instead of guessing a timezone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("as_of requires an explicit UTC offset")
    return parsed.astimezone(UTC)


def _revision_time(record: dict[str, Any]) -> datetime | None:
    value = record.get("recorded_at_utc")
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_as_of(value)
    except ValueError:
        return None


def snapshot_at(
    record: dict[str, Any], as_of: datetime
) -> tuple[dict[str, Any] | None, bool]:
    """Read an earlier recorded revision, not historical real-world validity.

    Revoked/rejected current records never reappear through time travel.
    Old records with ambiguous wall-clock timestamps are reported unavailable.
    The returned bool marks unavailable/invalid revision-time evidence.
    """
    if not is_recallable_memory(record):
        return None, False
    current = record
    history = record.get("history") or []
    if not isinstance(history, list):
        return None, True
    ends_at: datetime | None = None
    for index in range(len(history), -1, -1):
        starts_at = _revision_time(current)
        if starts_at is None or (ends_at is not None and starts_at > ends_at):
            return None, True
        if as_of >= starts_at:
            if not is_recallable_memory(current):
                return None, False
            return {
                **{key: value for key, value in current.items() if key != "history"},
                "scope": record.get("scope"),
                "recorded_from": starts_at.isoformat(),
                "recorded_until": ends_at.isoformat() if ends_at else None,
            }, False
        if index == 0:
            return None, False
        event = history[index - 1]
        previous = event.get("previous") if isinstance(event, dict) else None
        if not isinstance(previous, dict) or previous.get("memory_id") != record.get("memory_id"):
            return None, True
        if (
            not isinstance(current.get("revision"), int)
            or not isinstance(previous.get("revision"), int)
            or previous["revision"] + 1 != current["revision"]
        ):
            return None, True
        ends_at = starts_at
        current = previous
    return None, True
