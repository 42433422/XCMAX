"""Browser decision and page-evidence rules independent of model or tool IO."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    mode: Literal["action", "verify", "finish", "wait"]
    action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    assertion: str = Field(default="", max_length=500)
    evidence_node_id: str = ""
    reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def valid_mode(self) -> BrowserDecision:
        if self.mode == "action":
            if not self.action or self.evidence_node_id:
                raise ValueError("action requires exactly one registered action")
        elif self.action or self.params:
            raise ValueError("only action accepts tool parameters")
        if self.mode == "verify" and not self.assertion:
            raise ValueError("verification requires nonempty visible page text")
        if self.mode == "finish" and not self.evidence_node_id:
            raise ValueError("finish requires an independent verification receipt")
        if self.mode == "wait" and not self.reason:
            raise ValueError("handoff requires a question")
        return self


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
    targets = [params["target"]] if "target" in params else []
    if isinstance(params.get("fields"), list):
        targets.extend(
            field["target"]
            for field in params["fields"]
            if isinstance(field, dict) and "target" in field
        )
    if not targets:
        return True
    # Refs are node metadata, not quoted labels or text values after a YAML colon.
    prefixes = [
        re.sub(r'"(?:\\.|[^"\\])*"', "", line).split(":", 1)[0] for line in snapshot.splitlines()
    ]
    refs = set(re.findall(r"\[ref=([A-Za-z0-9_]+)\]", "\n".join(prefixes)))
    return all(isinstance(target, str) and target in refs for target in targets)
