from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts/security/export_codeql_review_packet.py"
    spec = importlib.util.spec_from_file_location("codeql_review_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alert():
    return {
        "number": 7,
        "state": "dismissed",
        "rule": {"id": "py/path-injection", "security_severity_level": "high"},
        "dismissed_comment": "unverified claim: example-sensitive-material",
        "dismissed_by": {"login": "original-author"},
        "most_recent_instance": {"location": {"path": "../outside.py"}},
    }


def test_queue_is_not_an_approval_and_does_not_copy_sensitive_comments(tmp_path):
    alert = _alert()
    packet = _module().build_packet([[alert]], tmp_path, "a" * 40, "b" * 64)
    assert packet["count"] == 1
    item = packet["alerts"][0]
    assert item["approval"] is None
    assert item["review_status"] == "pending_independent_review"
    assert item["source_available"] is False
    assert "example-sensitive-material" not in json.dumps(packet)
    assert (
        item["previous_dismissal"]["comment_sha256"]
        == hashlib.sha256(alert["dismissed_comment"].encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "payload", [{"message": "unavailable"}, [[{"number": 7}]], [_alert(), _alert()]]
)
def test_queue_rejects_error_payloads_and_duplicates(tmp_path, payload):
    with pytest.raises(ValueError):
        _module().build_packet(payload, tmp_path, "a" * 40, "b" * 64)
