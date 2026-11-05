"""Gitleaks disposition registry application in normalize_security_report."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path


def _normalizer_module():
    script = (
        Path(__file__).resolve().parents[1]
        / ".."
        / "scripts"
        / "security"
        / "normalize_security_report.py"
    ).resolve()
    # FHD/tests/test_security -> FHD/scripts/security
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "security"
        / "normalize_security_report.py"
    )
    spec = importlib.util.spec_from_file_location("normalize_security_report", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gitleaks_disposition_registry_closes_matched_secrets(tmp_path: Path, monkeypatch) -> None:
    normalizer = _normalizer_module()
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    evidence = {
        "schema": "gitleaks-disposition-evidence/v1",
        "n": 1,
        "disposition": "live-rejected",
        "note": "unit",
    }
    ev_text = __import__("json").dumps(evidence, indent=2) + "\n"
    sha = hashlib.sha256(ev_text.encode()).hexdigest()
    root = tmp_path / "disp"
    (root / "evidence").mkdir(parents=True)
    (root / "evidence" / "n01.json").write_text(ev_text, encoding="utf-8")
    registry = {
        "schema": "gitleaks-disposition-registry/v1",
        "rows": [
            {
                "key": "generic-api-key|FHD/mobile_relay_desktop.json|abc|3",
                "closed": True,
                "disposition": "live-rejected",
                "author": "codex-security-remediation",
                "reviewer": "42433422",
                "reviewed_at": "2026-11-01T01:00:00Z",
                "review_due": "2027-01-30T00:00:00Z",
                "evidence": "unit attestation",
                "evidence_files": ["evidence/n01.json"],
                "attestation_sha256": sha,
            }
        ],
    }
    (root / "registry.json").write_text(__import__("json").dumps(registry), encoding="utf-8")
    findings = [
        {
            "id": "generic-api-key",
            "severity": "high",
            "status": "open",
            "applicable": True,
            "secret": True,
            "path": "FHD/mobile_relay_desktop.json",
            "line": 3,
            "commit_sha": "abc",
        },
        {
            "id": "generic-api-key",
            "severity": "high",
            "status": "open",
            "applicable": True,
            "secret": True,
            "path": "other.json",
            "line": 1,
            "commit_sha": "def",
        },
    ]
    out = normalizer.apply_gitleaks_disposition(
        findings, registry_path=root / "registry.json", now=now
    )
    assert out[0]["secret"] is False
    assert out[0]["status"] == "closed"
    assert out[1]["secret"] is True
    assert out[1]["status"] == "open"
