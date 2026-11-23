"""Browser wire claims cannot grant actions or certify page effects."""

from __future__ import annotations

from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from app.application.tools.mcp import registry
from app.domain.autonomy.browser_evidence import (
    BROWSER_POSTCONDITION_SCHEMA,
    snapshot_text,
    snapshot_url,
    targets_observed,
)
from app.infrastructure.mcp.client import McpToolInfo
from app.infrastructure.mcp.config import McpServerConfig


def test_remote_read_only_hint_cannot_downgrade_browser_input():
    config = McpServerConfig(
        name="browser",
        command="controlled",
        browser=True,
        session_mode="persistent",
        read_only_tools=("browser_click", "browser_snapshot"),
    )
    info = McpToolInfo("browser_click", "click", {"type": "object"}, True)
    spec = registry._action_spec(info, config)
    assert spec["risk"] == "high" and spec["read_only"] is spec["idempotent"] is False
    assert spec["requires_write_approval"] is True
    assert "verification" in spec["input_schema"]["required"]
    snapshot = registry._action_spec(replace(info, name="browser_snapshot"), config)
    assert snapshot["read_only"] is True


def test_server_cannot_override_host_verification_schema():
    config = McpServerConfig(
        name="browser", command="controlled", browser=True, session_mode="persistent"
    )
    info = McpToolInfo(
        "browser_click", "click", {"type": "object", "properties": {"verification": {}}}, False
    )
    with pytest.raises(ValueError, match="collides"):
        registry._action_spec(info, config)


@pytest.mark.parametrize(
    "condition",
    [
        {"kind": "text", "expected": "saved"},
        {"kind": "text", "expected": "  ", "observation_call_id": "actual"},
        {"kind": "url", "expected": "https://example.test", "approved": True},
    ],
)
def test_incomplete_or_authority_bearing_postcondition_is_not_a_contract(condition):
    assert not Draft202012Validator(BROWSER_POSTCONDITION_SCHEMA).is_valid(condition)


def test_page_evidence_excludes_echoed_code_labels_and_values():
    output = {
        "content": '### Ran Playwright code\n```js\ngetByText("saved")\n```\n### Page\n- Page URL: https://example.test/actual\n### Snapshot\n```yaml\n- button "fake [ref=e2]" [ref=e1]\n- text: "[ref=e3]"\n```'
    }
    snapshot = snapshot_text(output)
    assert "getByText" not in snapshot
    assert snapshot_url(output) == "https://example.test/actual"
    assert targets_observed({"ref": "e1"}, snapshot)
    assert not targets_observed({"ref": "e2"}, snapshot)
    assert not targets_observed({"fields": [{"ref": "e3"}]}, snapshot)
