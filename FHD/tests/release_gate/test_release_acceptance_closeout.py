"""Fail-closed release acceptance; all remote calls are mocked."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts/dev/release_acceptance_closeout.py"
SHA = "a" * 40


def load():
    spec = importlib.util.spec_from_file_location("release_acceptance_closeout", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(issues=None):
    return {
        "schema": "xcagi.download_release.public/v1",
        "download_version": "1.0.0.7",
        "version_lock": "1.0.0.7",
        "release_ready": True,
        "git_sha": SHA,
        "release_id": f"xcagi-1.0.0.7-{SHA}",
        "linked_issues": [42] if issues is None else issues,
    }


def receipt(verdict="accepted"):
    return {
        "version": "1.0.0.7",
        "build_sha": SHA,
        "verdict": verdict,
        "per_platform": {
            "win": {"installed": 1, "failed": 0},
            "mac": {"installed": 1, "failed": 0},
        },
    }


def args():
    return argparse.Namespace(
        release_config="",
        market_base="https://xiu-ci.com",
        market_token="test",
        repo="test/repo",
        token="inert",
        version="",
        channel="stable",
        dry_run=False,
        apply=True,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"linked_issues": []},
        {"linked_issues": None},
        {"release_ready": False},
        {"git_sha": "bad"},
        {"release_id": "wrong"},
        {"version_lock": "1.0.0.6"},
    ],
)
def test_missing_or_unpublished_release_never_reads_receipts(monkeypatch, changes):
    m = load()
    data = {**config(), **changes}
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: data)
    monkeypatch.setattr(
        m,
        "_fetch_acceptance",
        lambda *a: pytest.fail("must not fetch acceptance for invalid release"),
    )
    assert m.run(args()) == 1


def test_receipt_mismatched_sha_never_mutates_issue(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: {**receipt(), "build_sha": "b" * 40})
    monkeypatch.setattr(m, "_http", lambda *a: pytest.fail("must not mutate issues"))
    assert m.run(args()) == 1


def test_persistence_failure_prevents_github_mutation(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: False)

    def github(method, url, token, body=None):
        assert method == "GET"
        return {"number": 42, "state": "open", "labels": []}

    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 1


def test_accepted_closes_original_issue_with_existing_label(monkeypatch):
    m = load()
    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, url, body))
        if method == "GET":
            return {"number": 42, "state": "open", "labels": [{"name": "customer-accepted"}]}
        if method == "PATCH":
            return {"state": "closed"}
        return {"ok": True}

    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert [action[0] for action in calls] == ["GET", "PATCH"]
    assert calls[-1][2] == {"state": "closed", "state_reason": "completed"}


def test_new_acceptance_adds_evidence_and_closes(monkeypatch):
    m = load()
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, body))
        if method == "GET":
            return {"number": 42, "state": "open", "labels": []}
        if method == "PATCH":
            return {"state": "closed"}
        return {"ok": True}

    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt())
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert [action[0] for action in calls] == ["GET", "POST", "POST", "PATCH"]


def test_rejected_reopens_accepted_issue(monkeypatch):
    m = load()
    calls = []

    def github(method, url, token, body=None):
        calls.append((method, body))
        if method == "GET":
            return {"number": 42, "state": "closed", "labels": [{"name": "customer-accepted"}]}
        if method == "PATCH":
            return {"state": "open"}
        return {"ok": True}

    monkeypatch.setattr(m, "_fetch_published_release", lambda _: config())
    monkeypatch.setattr(m, "_fetch_acceptance", lambda *a: receipt("rejected"))
    monkeypatch.setattr(m, "_ensure_label", lambda *a: None)
    monkeypatch.setattr(m, "_record_verdict_local", lambda *a: True)
    monkeypatch.setattr(m, "_http", github)
    assert m.run(args()) == 0
    assert calls[1] == ("PATCH", {"state": "open"})
