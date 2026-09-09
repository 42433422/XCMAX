"""Stable dependency-first order; cycles and their dependents remain blocked."""

import heapq

from .manifest import ModMetadata, _normalize_dependencies


def order_mods(
    mods: list[ModMetadata], loaded_ids: set[str]
) -> tuple[list[ModMetadata], list[str]]:
    by_id = {item.id: item for item in mods}
    waiting: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {mid: set() for mid in by_id}
    for mid, item in by_id.items():
        waiting[mid] = {
            dep
            for dep in _normalize_dependencies(item.dependencies)
            if dep != "xcagi" and dep in by_id and dep not in loaded_ids
        }
        for dep in waiting[mid]:
            dependents[dep].add(mid)

    def priority(mid: str) -> tuple[bool, str, str]:
        return not by_id[mid].primary, mid.lower(), mid

    ready = [priority(mid) for mid, deps in waiting.items() if not deps]
    heapq.heapify(ready)
    ordered = []
    while ready:
        _, _, mid = heapq.heappop(ready)
        ordered.append(by_id[mid])
        for child in dependents[mid]:
            waiting[child].remove(mid)
            if not waiting[child]:
                heapq.heappush(ready, priority(child))
    blocked = sorted((mid for mid, deps in waiting.items() if deps), key=priority)
    return ordered, blocked
