"""Bounded, redacted handoffs; execution proof remains in the original receipt."""

from __future__ import annotations

import json
from typing import Any

from modstore_server.customer_issue_delivery_contract import execution_succeeded
from modstore_server.incident_team_handler_digest import (
    handler_output_digest,
    redact_text,
)

_IDENTITY = (
    "event_id",
    "tenant_id",
    "employee_id",
    "attempt_id",
    "verified_fix_attempt_id",
)
_REFERENCES = (
    "task_id",
    "para_task_id",
    "change_request_id",
    "pull_request_url",
    "branch",
    "merge_commit_sha",
)


def role_handoff(result: Any, role: str, *, max_chars: int = 4000) -> dict[str, Any]:
    """Keep field boundaries and provenance when reducing context, never infer success."""
    row = result if isinstance(result, dict) else {}
    saved = row.get("handler_outputs")
    receipt = {**row, "result": saved} if isinstance(saved, dict) else row
    digest = handler_output_digest(receipt)
    nested = row.get("result") if isinstance(row.get("result"), dict) else {}
    outputs = digest.get("outputs") or []
    sources = [row, nested, *outputs]
    handoff: dict[str, Any] = {
        "schema": "incident-role-handoff/v1",
        "role": role,
        "status": redact_text(row.get("status") or digest.get("status") or "unknown", 80),
        "succeeded": execution_succeeded(receipt),
        "identity": {k: redact_text(row[k], 100) for k in _IDENTITY if row.get(k)},
        "summaries": [],
        "blockers": [],
        "next_actions": [],
        "references": [],
        "omitted_items": 0,
    }
    for source in sources:
        for target, keys in (
            ("summaries", ("summary", "output_summary", "change_summary", "cause")),
            ("blockers", ("error", "output_error", "cognition_error")),
            ("next_actions", ("next_step",)),
        ):
            for key in keys:
                if source.get(key):
                    value = redact_text(source[key], 1000 if target == "summaries" else 350)
                    if value not in handoff[target]:
                        if len(handoff[target]) < 4:
                            handoff[target].append(value)
                        else:
                            handoff["omitted_items"] += 1
        ref = {key: redact_text(source[key], 240) for key in _REFERENCES if source.get(key)}
        if ref and ref not in handoff["references"]:
            handoff["references"].append(ref)
    # Trim optional context at field boundaries. Identity/status always survive.
    budget = max(1200, min(int(max_chars), 12000))
    while len(json.dumps(handoff, ensure_ascii=False)) > budget:
        groups = ("summaries", "blockers", "next_actions", "references")
        group = max(groups, key=lambda key: len(json.dumps(handoff[key], ensure_ascii=False)))
        values = handoff[group]
        if not values:
            break
        if isinstance(values[-1], str) and len(values[-1]) > 120:
            values[-1] = values[-1][: max(100, len(values[-1]) // 2)] + "…"
        else:
            values.pop()
        handoff["omitted_items"] += 1
    return handoff


def format_role_handoff(result: Any, role: str, *, max_chars: int = 4000) -> str:
    return json.dumps(role_handoff(result, role, max_chars=max_chars), ensure_ascii=False)
