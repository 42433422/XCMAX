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


def _entities(row: dict[str, Any]) -> dict[EntityKey, str]:
    value = row.get("value")
    if not isinstance(value, dict):
        return {}
    entities = value.get("entities")
    if not isinstance(entities, list):
        return {}
    scope = record_key(row)[0]
    result: dict[EntityKey, str] = {}
    if not scope:
        return result
    for entity in entities[:6]:
        if not isinstance(entity, dict) or entity.get("role") not in {"subject", "object"}:
            continue
        kind = str(entity.get("type") or "")
        name = str(entity.get("name") or "").strip().casefold()
        if kind in _NAMED_TYPES and 2 <= len(name) <= 160 and name not in _GENERIC:
            identity = entity.get("entity_id")
            key = _entity_identity(identity, name)
            result[(scope, kind, key)] = name
    return result


def _entity_identity(identity: Any, name: str) -> str:
    # Explicit IDs and name-only candidates never collapse into one another.
    if isinstance(identity, str) and 0 < len(identity.strip()) <= 160:
        return "id:" + identity.strip()
    return "name:" + name


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
    entities_by_record: dict[RecordKey, dict[EntityKey, str]] = {}
    aliases: dict[EntityKey, set[str]] = defaultdict(set)
    for key, row in sorted(by_key.items()):
        entities = _entities(row)
        entities_by_record[key] = entities
        for entity in sorted(entities):
            links[entity].append(key)
            aliases[entity].add(entities[entity])
    normalized_query = query.casefold()
    queue: deque[tuple[EntityKey, list[dict[str, Any]]]] = deque(
        (entity, [])
        for entity in sorted(links)
        if any(_mentions(normalized_query, name) for name in aliases[entity])
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
                    "via_entity": entities_by_record[key][entity],
                    "entity_type": entity[1],
                    "identity_basis": (
                        "recorded_id" if entity[2].startswith("id:") else "typed_name_candidate"
                    ),
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
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
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


def validity_bounds(value: Any) -> tuple[datetime | None, datetime | None]:
    """Explicit business-time interval; never infer it from recording time."""
    if not isinstance(value, dict):
        return None, None
    cardinality = value.get("relation_cardinality")
    if cardinality is not None and cardinality not in ("one", "many"):
        raise ValueError("relation_cardinality must be one or many")
    if "relation_validity" not in value:
        return None, None
    interval = value["relation_validity"]
    if not isinstance(interval, dict) or set(interval) - {"effective_from", "effective_until"}:
        raise ValueError("invalid relation_validity")
    start_raw = interval.get("effective_from")
    end_raw = interval.get("effective_until")
    start = parse_as_of(start_raw) if start_raw is not None else None
    end = parse_as_of(end_raw) if end_raw is not None else None
    if start is None and end is None:
        raise ValueError("relation_validity needs an explicit bound")
    if start is not None and end is not None and start >= end:
        raise ValueError("relation validity interval is empty or reversed")
    return start, end


def validate_relation_value(value: Any) -> dict[str, Any] | None:
    try:
        validity_bounds(value)
    except ValueError as exc:
        return {
            "success": False,
            "error_code": "memory_invalid_relation_validity",
            "message": str(exc),
        }
    return None


def _relation_key(row: dict[str, Any]) -> tuple[tuple[str, str, str, str], str] | None:
    value = row.get("value")
    if not isinstance(value, dict):
        return None
    predicate = value.get("predicate")
    object_text = value.get("object")
    entities = value.get("entities")
    if not isinstance(predicate, str) or not isinstance(object_text, str):
        return None
    if not predicate.strip() or not object_text.strip() or not isinstance(entities, list):
        return None
    subject = next(
        (entity for entity in entities[:6] if isinstance(entity, dict)
         and entity.get("role") == "subject"),
        None,
    )
    if subject is None:
        return None
    name = str(subject.get("name") or "").strip().casefold()
    kind = str(subject.get("type") or "")
    if kind not in _NAMED_TYPES or not name or name in _GENERIC:
        return None
    subject_key = _entity_identity(subject.get("entity_id"), name)
    obj = next(
        (entity for entity in entities[:6] if isinstance(entity, dict)
         and entity.get("role") == "object"),
        None,
    )
    object_key = _entity_identity(
        obj.get("entity_id") if obj else None, object_text.strip().casefold()
    )
    scope = record_key(row)[0] or "owner"
    return (scope, kind, subject_key, predicate.strip().casefold()), object_key


def select_effective_records(
    rows: list[dict[str, Any]],
    *,
    at: datetime | None = None,
    require_explicit: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Filter effective records and quarantine explicit single-valued conflicts.

    Callers must provide only one authorized owner's records, or scope-tagged
    records from the same authorized access context. No record is mutated.
    """
    instant = at or datetime.now(UTC)
    eligible: list[dict[str, Any]] = []
    unavailable = 0
    groups: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for row in rows:
        if not is_recallable_memory(row):
            continue
        try:
            start, end = validity_bounds(row.get("value"))
        except ValueError:
            unavailable += 1
            continue
        if require_explicit and start is None and end is None:
            unavailable += 1
            continue
        if (start is not None and instant < start) or (end is not None and instant >= end):
            continue
        eligible.append(row)
        relation = _relation_key(row)
        if relation is not None:
            key, object_key = relation
            groups[key].append((row, object_key))
    withheld: set[RecordKey] = set()
    conflicts: list[dict[str, Any]] = []
    for key, candidates in sorted(groups.items()):
        if len({obj for _, obj in candidates}) <= 1:
            continue
        if not any(
            row["value"].get("relation_cardinality") == "one" for row, _ in candidates
        ):
            continue
        withheld.update(record_key(row) for row, _ in candidates)
        conflicts.append({
            "scope": key[0],
            "predicate": key[3],
            "memory_ids": sorted(str(row.get("memory_id") or "") for row, _ in candidates),
            "resolution": "review_required",
        })
    return [row for row in eligible if record_key(row) not in withheld], conflicts, unavailable

def relation_write_conflicts(
    rows: list[dict[str, Any]], candidate: dict[str, Any]
) -> list[dict[str, Any]]:
    """Find overlapping explicit singleton assertions in one owner transaction.

    An unbounded interval is not evidence of succession. Never pick a winner,
    merge typed names with IDs, or infer cardinality for a many-valued relation.
    Historical non-overlapping intervals may coexist.
    """
    relation = _relation_key(candidate)
    if relation is None:
        return []
    key, object_key = relation
    value = candidate["value"]
    start, end = validity_bounds(value)
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        if not is_recallable_memory(row) or row.get("memory_id") == candidate.get("memory_id"):
            continue
        other = _relation_key(row)
        if other is None or other[0] != key or other[1] == object_key:
            continue
        other_value = row["value"]
        if "one" not in (value.get("relation_cardinality"), other_value.get("relation_cardinality")):
            continue
        try:
            other_start, other_end = validity_bounds(other_value)
        except ValueError:
            # Existing invalid intervals cannot safely establish non-overlap.
            other_start, other_end = None, None
        if end is not None and other_start is not None and end <= other_start:
            continue
        if other_end is not None and start is not None and other_end <= start:
            continue
        conflicts.append({
            "memory_id": str(row["memory_id"]),
            "revision": int(row.get("revision") or 1),
        })
    return sorted(conflicts, key=lambda item: item["memory_id"])
