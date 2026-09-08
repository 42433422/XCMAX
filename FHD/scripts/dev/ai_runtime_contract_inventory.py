"""Read-only audit of a supplied ASGI app's mounted API contracts.

Call inventory(app) after the intended registration profile. This module never
constructs an app, starts its lifespan, or invokes any business endpoint.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from starlette.routing import compile_path

from app.application.aiopen.api_contracts import api_schema, mounted_operations


def inventory(app: Any) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    preceding: list[tuple[str, set[str], Any]] = []
    for path, route in mounted_operations(app):
        if not path.startswith("/api/"):
            continue
        methods = set(route.methods or [])
        original = getattr(route, "original_route", route)
        endpoint = getattr(original, "endpoint", None)
        for method in sorted(methods):
            shadowed_by = [
                previous
                for previous, previous_methods, regex in preceding
                if method in previous_methods and "{" not in path and regex.fullmatch(path)
            ]
            operations.append(
                {
                    "path": path,
                    "method": method,
                    "handler": f"{getattr(endpoint, '__module__', '')}.{getattr(endpoint, '__qualname__', '')}",
                    "hidden_from_public_schema": not bool(
                        getattr(route, "include_in_schema", False)
                    ),
                    "static_path_shadowed_by": shadowed_by,
                }
            )
        preceding.append((path, methods, compile_path(path)[0]))
    multiplicity = Counter((row["path"], row["method"]) for row in operations)
    results: dict[tuple[str, str], str] = {}
    for path, method in multiplicity:
        try:
            schema = api_schema(app, {"path": path, "method": method})
            results[path, method] = (
                "available" if schema.get("success") else str(schema.get("code") or "unknown")
            )
        except Exception as exc:  # noqa: BLE001 - collect each schema failure as audit evidence
            # Diagnostic boundary only: do not turn schema exceptions into a
            # fabricated contract or persist arbitrary exception payloads.
            results[path, method] = "error:" + type(exc).__name__
    for row in operations:
        key = (row["path"], row["method"])
        row["registrations"] = multiplicity[key]
        row["schema_status"] = results[key]
    return {
        "scope": "Supplied app registration profile; no startup, endpoint execution, account availability or installed-runtime verification.",
        "business_coverage_percent": None,
        "counts": {
            "registrations": len(operations),
            "unique_path_methods": len(multiplicity),
            "duplicated_path_methods": sum(count > 1 for count in multiplicity.values()),
            "static_shadowed_registrations": sum(
                bool(row["static_path_shadowed_by"]) for row in operations
            ),
            "schema_status_by_unique_operation": dict(sorted(Counter(results.values()).items())),
        },
        "limitations": [
            "Dynamic-versus-dynamic overlap requires concrete request matching.",
            "Non-API catch-all mounts and middleware may further restrict dispatch.",
            "Startup-loaded Mods, roles, data and business effects require independent runtime acceptance.",
        ],
        "operations": operations,
    }
