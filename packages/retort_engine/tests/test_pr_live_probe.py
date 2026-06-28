from __future__ import annotations

from typing import Any

from retort_engine.contracts import validate_contract
from retort_engine.pr_live_probe import run_live_pr_comment_probe, run_readonly_pr_degradation_probe


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


def test_live_pr_comment_probe_degrades_on_low_permission_write_denied() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, payload: dict[str, Any] | None, token: str) -> tuple[int, dict[str, Any]]:
        calls.append((method, url))
        assert token == "token"
        if method == "GET" and url.endswith("/repos/owner/repo"):
            return 200, {"permissions": {"admin": False, "maintain": False, "push": False, "triage": False}}
        if method == "GET" and url.endswith("/pulls/7"):
            return 200, {"number": 7, "head": {"ref": "feature"}, "base": {"ref": "main"}}
        if method == "POST" and url.endswith("/issues/7/comments"):
            return 403, {"message": "Resource not accessible by integration"}
        raise AssertionError(f"unexpected call {method} {url}")

    result = run_live_pr_comment_probe("https://github.com/owner/repo/pull/7", token="token", transport=transport)

    assert result["status"] == "permission_denied_degraded"
    assert result["summary"]["permission_denied"] is True
    assert result["summary"]["degraded_without_write"] is True
    assert result["summary"]["rollback_verified"] is True
    assert result["summary"]["live_github_write"] is False
    assert result["created_receipts"] == []
    assert result["evidence"]["real_network"] is False
    assert result["evidence"]["transport"] == "injected_transport"
    assert result["evidence"]["degradation"] == "no_comment_created_no_rollback_needed"
    assert ("POST", "https://api.github.com/repos/owner/repo/issues/7/comments") in calls
    assert validate_contract("pr_live_publish_probe_result", result)["valid"] is True


def test_readonly_pr_degradation_probe_uses_no_write_path() -> None:
    calls: list[tuple[str, str]] = []

    def transport(method: str, url: str, payload: dict[str, Any] | None, token: str) -> tuple[int, dict[str, Any]]:
        calls.append((method, url))
        assert token == ""
        if method == "GET" and url.endswith("/repos/owner/repo"):
            return 200, {"name": "repo"}
        if method == "GET" and url.endswith("/pulls/7"):
            return 200, {"number": 7, "head": {"ref": "feature"}, "base": {"ref": "main"}}
        raise AssertionError(f"unexpected call {method} {url}")

    result = run_readonly_pr_degradation_probe("https://github.com/owner/repo/pull/7", transport=transport)

    assert result["status"] == "read_only_degraded"
    assert result["summary"]["live_github_write"] is False
    assert result["summary"]["degraded_without_write"] is True
    assert result["summary"]["degradation_artifact_ready"] is True
    assert result["evidence"]["real_network"] is False
    assert result["evidence"]["transport"] == "injected_transport"
    assert result["evidence"]["degradation_artifact"]["kind"] == "publish_dry_run"
    assert ("GET", "https://api.github.com/repos/owner/repo/pulls/7") in calls
    assert validate_contract("pr_readonly_degradation_probe_result", result)["valid"] is True
