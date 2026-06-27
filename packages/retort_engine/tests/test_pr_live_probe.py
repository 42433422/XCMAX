from __future__ import annotations

from typing import Any

from retort_engine.contracts import validate_contract
from retort_engine.pr_live_probe import run_live_pr_comment_probe


def test_live_pr_comment_probe_creates_and_rolls_back_with_transport() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, payload: dict[str, Any] | None, token: str) -> tuple[int, dict[str, Any]]:
        calls.append((method, url))
        assert token == "token"
        if method == "GET" and url.endswith("/repos/owner/repo"):
            return 200, {"permissions": {"admin": True, "maintain": True, "push": True}}
        if method == "GET" and url.endswith("/pulls/7"):
            return 200, {"number": 7, "head": {"ref": "feature"}, "base": {"ref": "main"}}
        if method == "POST" and url.endswith("/issues/7/comments"):
            assert payload and "body" in payload
            return 201, {"id": 123, "html_url": "https://github.com/owner/repo/pull/7#issuecomment-123"}
        if method == "DELETE" and url.endswith("/issues/comments/123"):
            return 204, {}
        raise AssertionError(f"unexpected call {method} {url}")

    result = run_live_pr_comment_probe("https://github.com/owner/repo/pull/7", token="token", transport=transport)

    assert result["status"] == "live_rolled_back"
    assert result["summary"]["live_github_write"] is True
    assert result["summary"]["rollback_verified"] is True
    assert result["created_receipts"][0]["comment_id"] == "123"
    assert result["rollback_receipts"][0]["deleted"] is True
    assert ("POST", "https://api.github.com/repos/owner/repo/issues/7/comments") in calls
    assert validate_contract("pr_live_publish_probe_result", result)["valid"] is True
