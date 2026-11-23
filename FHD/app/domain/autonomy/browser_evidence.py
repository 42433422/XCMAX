"""Single-action browser postconditions and page evidence, with no decision loop."""

from __future__ import annotations

import re
from typing import Any

BROWSER_POSTCONDITION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "expected"],
    "properties": {
        "kind": {"enum": ["url", "text"]},
        "expected": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "pattern": r"[\s\S]*\S[\s\S]*",
        },
        "observation_call_id": {"type": "string", "minLength": 1, "maxLength": 160},
    },
    "allOf": [
        {
            "if": {"properties": {"kind": {"const": "text"}}},
            "then": {"required": ["observation_call_id"]},
        }
    ],
}


def snapshot_text(output: dict[str, Any]) -> str:
    """Use only the actual accessibility snapshot, never echoed code/URL/messages."""
    content = str(output.get("content") or "")
    match = re.search(r"### Snapshot\s*\n```(?:yaml)?\s*\n(.*?)\n```", content, re.S)
    return match.group(1) if match else ""


def snapshot_url(output: dict[str, Any]) -> str:
    """Read only the page header, excluding code echoes and arbitrary page text."""
    content = str(output.get("content") or "")
    content = re.sub(r"```.*?```", "", content, flags=re.S)
    match = re.search(r"^### Page\s*\n(.*?)(?=^### |\Z)", content, re.S | re.M)
    page = match.group(1) if match else ""
    url = re.search(r"^- Page URL: (https?://[^\r\n]+)$", page, re.M)
    return url.group(1).strip() if url else ""


def targets_observed(params: dict[str, Any], snapshot: str) -> bool:
    targets = [params[key] for key in ("target", "ref") if key in params]
    if isinstance(params.get("fields"), list):
        targets.extend(
            field[key]
            for field in params["fields"]
            if isinstance(field, dict)
            for key in ("target", "ref")
            if key in field
        )
    if not targets:
        return True
    # Refs are node metadata, not quoted labels or text values after a YAML colon.
    prefixes = [
        re.sub(r'"(?:\\.|[^"\\])*"', "", line).split(":", 1)[0] for line in snapshot.splitlines()
    ]
    refs = set(re.findall(r"\[ref=([A-Za-z0-9_]+)\]", "\n".join(prefixes)))
    return all(isinstance(target, str) and target in refs for target in targets)
