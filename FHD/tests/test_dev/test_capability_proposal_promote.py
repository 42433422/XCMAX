"""Governance and idempotency tests for capability proposal promotion."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "dev" / "capability_proposal_promote.py"
)
_spec = importlib.util.spec_from_file_location("capability_proposal_promote", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
promote = importlib.util.module_from_spec(_spec)
sys.modules["capability_proposal_promote"] = promote
_spec.loader.exec_module(promote)


def _issue(labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "number": 42,
        "state": "open",
        "title": "[capability-proposal] 新能力候选 abc123",
        "body": ("## 来源：能力提案 (capability_proposal)\n## 结构化上下文\n{}\n## 治理门禁\n"),
        "labels": [
            {"name": name}
            for name in (labels or ["capability-proposal", "auto-generated", "needs-human"])
        ],
    }


def _comment(body: str = "确认实现", association: str = "OWNER") -> dict[str, Any]:
    return {
        "id": 88,
        "body": body,
        "author_association": association,
        "issue_url": "https://api.github.com/repos/acme/repo/issues/42",
    }


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "repo": "acme/repo",
        "token": "token",
        "issue_number": 42,
        "comment_id": 88,
        "workflow_ref": "main",
        "target_branch": "main",
        "dry_run": False,
        "apply": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.parametrize(
    ("issue", "comment", "reason"),
    [
        (_issue(), _comment("批准"), "exact approval"),
        (_issue(), _comment(association="MEMBER"), "repository owner"),
        (_issue(["capability-proposal"]), _comment(), "missing required"),
        ({**_issue(), "pull_request": {}}, _comment(), "pull requests"),
        ({**_issue(), "title": "ordinary issue"}, _comment(), "generated capability"),
    ],
)
def test_validate_promotion_rejects_untrusted_inputs(
    issue: dict[str, Any], comment: dict[str, Any], reason: str
) -> None:
    ok, message = promote._validate_promotion(issue, comment, issue_number=42)
    assert ok is False
    assert reason in message


def test_validate_promotion_accepts_exact_owner_command() -> None:
    ok, message = promote._validate_promotion(_issue(), _comment(), issue_number=42)
    assert ok is True
    assert "owner approved" in message


def test_success_adds_label_writes_pending_receipt_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, Any]]] = []
    patches: list[tuple[str, dict[str, Any]]] = []

    def fake_get(url: str, _token: str) -> Any:
        if url.endswith("/issues/42"):
            return _issue()
        if url.endswith("/issues/comments/88"):
            return _comment()
        if "/issues/42/comments?" in url:
            return []
        raise AssertionError(url)

    def fake_post(url: str, _token: str, body: dict[str, Any]) -> dict[str, Any]:
        posts.append((url, body))
        if url.endswith("/issues/42/comments"):
            return {"id": 999}
        return {}

    monkeypatch.setattr(promote, "_gh_get", fake_get)
    monkeypatch.setattr(promote, "_gh_post", fake_post)
    monkeypatch.setattr(
        promote,
        "_gh_patch",
        lambda url, _token, body: patches.append((url, body)) or {},
    )
    monkeypatch.setattr(promote, "_write_report", lambda _result: Path("report.json"))

    assert promote.run(_args()) == 0
    assert any(url.endswith("/issues/42/labels") for url, _ in posts)
    dispatches = [
        body for url, body in posts if url.endswith("/fhd-ai-issue-implement.yml/dispatches")
    ]
    assert dispatches == [
        {"ref": "main", "inputs": {"issue_number": "42", "target_branch": "main"}}
    ]
    pending = [body["body"] for url, body in posts if url.endswith("/issues/42/comments")]
    assert "promotion-status:dispatching" in pending[0]
    assert "promotion-status:dispatched" in patches[0][1]["body"]


def test_completed_receipt_makes_rerun_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = promote._receipt_marker(42, 88)

    def fake_get(url: str, _token: str) -> Any:
        if url.endswith("/issues/42"):
            return _issue(["capability-proposal", "auto-generated", "needs-human", "ai-implement"])
        if url.endswith("/issues/comments/88"):
            return _comment()
        return [{"id": 999, "body": f"{marker}\n<!-- promotion-status:dispatched -->"}]

    posts: list[Any] = []
    monkeypatch.setattr(promote, "_gh_get", fake_get)
    monkeypatch.setattr(promote, "_gh_post", lambda *args: posts.append(args))
    monkeypatch.setattr(promote, "_write_report", lambda _result: Path("report.json"))

    assert promote.run(_args()) == 0
    assert posts == []


def test_completed_receipt_wins_over_older_failed_attempt() -> None:
    marker = promote._receipt_marker(42, 88)
    receipt = promote._find_receipt(
        [
            {"id": 900, "body": f"{marker}\n<!-- promotion-status:failed -->"},
            {"id": 901, "body": f"{marker}\n<!-- promotion-status:dispatched -->"},
        ],
        marker,
    )
    assert receipt == (901, "dispatched")


def test_pending_receipt_fails_closed_without_duplicate_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = promote._receipt_marker(42, 88)

    def fake_get(url: str, _token: str) -> Any:
        if url.endswith("/issues/42"):
            return _issue()
        if url.endswith("/issues/comments/88"):
            return _comment()
        return [{"id": 999, "body": f"{marker}\n<!-- promotion-status:dispatching -->"}]

    posts: list[Any] = []
    monkeypatch.setattr(promote, "_gh_get", fake_get)
    monkeypatch.setattr(promote, "_gh_post", lambda *args: posts.append(args))
    monkeypatch.setattr(promote, "_write_report", lambda _result: Path("report.json"))

    assert promote.run(_args()) == 1
    assert posts == []


def test_dispatch_failure_updates_receipt_and_rolls_back_new_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted: list[tuple[str, int, str, str]] = []
    patches: list[dict[str, Any]] = []

    def fake_get(url: str, _token: str) -> Any:
        if url.endswith("/issues/42"):
            return _issue()
        if url.endswith("/issues/comments/88"):
            return _comment()
        return []

    def fake_post(url: str, _token: str, body: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("/issues/42/comments"):
            return {"id": 999}
        if url.endswith("/dispatches"):
            raise RuntimeError("dispatch unavailable")
        return {}

    monkeypatch.setattr(promote, "_gh_get", fake_get)
    monkeypatch.setattr(promote, "_gh_post", fake_post)
    monkeypatch.setattr(
        promote,
        "_gh_patch",
        lambda _url, _token, body: patches.append(body) or {},
    )
    monkeypatch.setattr(
        promote,
        "_gh_delete_label",
        lambda repo, number, label, token: deleted.append((repo, number, label, token)),
    )
    monkeypatch.setattr(promote, "_write_report", lambda _result: Path("report.json"))

    assert promote.run(_args()) == 1
    assert "promotion-status:failed" in patches[0]["body"]
    assert deleted == [("acme/repo", 42, "ai-implement", "token")]


@pytest.mark.parametrize("branch", ["refs/heads/main", "HEAD", "../main", "bad branch", "x.lock"])
def test_unsafe_dispatch_ref_is_rejected(monkeypatch: pytest.MonkeyPatch, branch: str) -> None:
    monkeypatch.setattr(promote, "_write_report", lambda _result: Path("report.json"))
    monkeypatch.setattr(
        promote,
        "_gh_get",
        lambda *_args: pytest.fail("unsafe ref must be rejected before GitHub access"),
    )
    assert promote.run(_args(workflow_ref=branch)) == 1
