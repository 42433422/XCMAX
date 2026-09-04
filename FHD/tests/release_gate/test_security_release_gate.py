from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _module():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "security" / "security_release_gate.py"
    )
    spec = importlib.util.spec_from_file_location("security_release_gate", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalizer_module():
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


def _write_reports(directory: Path, mod, now: datetime) -> None:
    directory.mkdir(exist_ok=True)
    for scanner in mod.REQUIRED_SCANNERS:
        (directory / f"{scanner}.json").write_text(
            json.dumps(
                {
                    "available": True,
                    "scanned_at": now.isoformat(),
                    "findings": [],
                }
            )
        )


def test_all_scanners_must_be_fresh_and_zero(tmp_path: Path) -> None:
    mod = _module()
    now = datetime(2026, 9, 4, tzinfo=UTC)
    _write_reports(tmp_path, mod, now)
    assert mod.evaluate(tmp_path, now=now)["passed"] is True

    (tmp_path / "trivy-image.json").unlink()
    failed = mod.evaluate(tmp_path, now=now)
    assert failed["passed"] is False
    assert "trivy-image:report_missing" in failed["blockers"]


def test_high_and_secret_findings_block(tmp_path: Path) -> None:
    mod = _module()
    now = datetime(2026, 9, 4, tzinfo=UTC)
    _write_reports(tmp_path, mod, now)
    (tmp_path / "codeql.json").write_text(
        json.dumps(
            {
                "available": True,
                "scanned_at": now.isoformat(),
                "findings": [{"id": "ql-1", "severity": "high", "status": "open"}],
            }
        )
    )
    (tmp_path / "gitleaks.json").write_text(
        json.dumps(
            {
                "available": True,
                "scanned_at": now.isoformat(),
                "findings": [{"id": "secret-1", "severity": "unknown", "secret": True}],
            }
        )
    )

    failed = mod.evaluate(tmp_path, now=now)

    assert failed["passed"] is False
    assert failed["applicable_open"]["high"] == 1
    assert any("unresolved_secret" in blocker for blocker in failed["blockers"])


def test_scanner_error_json_cannot_be_normalized_as_zero_findings() -> None:
    mod = _normalizer_module()

    for kind, payload in (
        ("codeql", [{"message": "service unavailable", "status": "503"}]),
        ("dependabot", [{"message": "not accessible", "status": "403"}]),
        ("npm-audit", {"error": {"summary": "registry unavailable"}}),
        ("pip-audit", {"error": "index unavailable"}),
        ("trivy", {"ArtifactName": "repo"}),
        ("sarif", {"version": "2.1.0"}),
    ):
        with pytest.raises(ValueError):
            mod._validate_native_payload(kind, payload)


def test_false_positive_requires_independent_fresh_review(tmp_path: Path) -> None:
    mod = _module()
    now = datetime(2026, 9, 4, tzinfo=UTC)
    _write_reports(tmp_path, mod, now)
    finding = {
        "id": "ql-reviewed",
        "severity": "critical",
        "status": "open",
        "author": "developer-a",
        "disposition": "false_positive",
        "false_positive_approval": {
            "reviewer": "security-reviewer-b",
            "evidence": "validated closed command grammar and shell=False",
            "reviewed_at": now.isoformat(),
            "review_due": (now + timedelta(days=30)).isoformat(),
        },
    }
    (tmp_path / "codeql.json").write_text(
        json.dumps({"available": True, "scanned_at": now.isoformat(), "findings": [finding]})
    )
    assert mod.evaluate(tmp_path, now=now)["passed"] is True

    finding["false_positive_approval"]["reviewer"] = "developer-a"
    (tmp_path / "codeql.json").write_text(
        json.dumps({"available": True, "scanned_at": now.isoformat(), "findings": [finding]})
    )
    assert mod.evaluate(tmp_path, now=now)["passed"] is False


def test_dismissed_alert_requires_structured_independent_review() -> None:
    normalizer = _normalizer_module()
    rows = normalizer.normalize(
        "codeql",
        [
            {
                "number": 71,
                "state": "dismissed",
                "rule": {"security_severity_level": "high"},
                "dismissed_by": {"login": "security-reviewer"},
                "dismissed_at": "2026-09-04T00:00:00Z",
                "dismissed_reason": "false positive",
                "dismissed_comment": json.dumps(
                    {
                        "author": "fix-author",
                        "evidence": "review-record-sha256:abc",
                        "review_due": "2026-10-04T00:00:00Z",
                    }
                ),
            }
        ],
    )

    assert rows[0]["status"] == "active"
    assert rows[0]["disposition"] == "false_positive"
    assert rows[0]["author"] == "fix-author"
    assert rows[0]["false_positive_approval"]["reviewer"] == "security-reviewer"


def test_sarif_numeric_and_error_severity_cannot_evade_high_gate() -> None:
    normalizer = _normalizer_module()
    findings = normalizer.normalize(
        "sarif",
        {
            "runs": [
                {
                    "results": [
                        {"ruleId": "electron-unsafe", "level": "error"},
                        {
                            "ruleId": "electron-critical",
                            "properties": {"security-severity": "9.8"},
                        },
                    ]
                }
            ]
        },
    )

    assert [row["severity"] for row in findings] == ["high", "critical"]


def test_codeql_provenance_requires_fresh_exact_sha_for_each_language() -> None:
    normalizer = _normalizer_module()
    now = datetime(2026, 9, 5, tzinfo=UTC)
    sha = "a" * 40
    analyses = [
        {
            "category": "/language:python",
            "commit_sha": sha,
            "created_at": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "category": "/language:javascript-typescript",
            "commit_sha": sha,
            "created_at": (now - timedelta(hours=1)).isoformat(),
        },
    ]

    assert (
        normalizer._validate_codeql_provenance(
            analyses,
            release_sha=sha,
            required_categories=[
                "/language:python",
                "/language:javascript-typescript",
            ],
            now=now,
        )
        == sha
    )

    analyses[1]["commit_sha"] = "b" * 40
    with pytest.raises(ValueError, match="SHA mismatch"):
        normalizer._validate_codeql_provenance(
            analyses,
            release_sha=sha,
            required_categories=[
                "/language:python",
                "/language:javascript-typescript",
            ],
            now=now,
        )


def test_release_gate_rejects_relabelled_scanner_evidence(tmp_path: Path) -> None:
    mod = _module()
    now = datetime(2026, 9, 5, tzinfo=UTC)
    release_sha = "a" * 40
    _write_reports(tmp_path, mod, now)
    for scanner in mod.REQUIRED_SCANNERS:
        path = tmp_path / f"{scanner}.json"
        payload = json.loads(path.read_text())
        payload["release_sha"] = release_sha
        payload["source_sha"] = release_sha
        path.write_text(json.dumps(payload))

    assert mod.evaluate(tmp_path, now=now, release_sha=release_sha)["passed"] is True
    payload = json.loads((tmp_path / "codeql.json").read_text())
    payload["source_sha"] = "b" * 40
    (tmp_path / "codeql.json").write_text(json.dumps(payload))
    failed = mod.evaluate(tmp_path, now=now, release_sha=release_sha)
    assert failed["passed"] is False
    assert "codeql:source_sha_mismatch" in failed["blockers"]


def test_full_scan_collects_and_uploads_evidence_after_individual_scanner_failure() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "security-full-scan.yml"
    ).read_text()

    assert "Build and scan final FHD production image\n        continue-on-error: true" in workflow
    assert "--config /repo/.github/gitleaks-config.toml" in workflow
    assert "--no-emit-local" in workflow
    assert "production-host-rootfs.tar.gz" in workflow
    assert "var/lib/dpkg/status" in workflow
    assert "--skip-db-update" in workflow
    assert "scp " not in workflow
    assert "docker run --rm -v /:/host:ro aquasec/trivy:latest" not in workflow
    assert (
        "continue-on-error: true\n        working-directory: .\n        run: docker build"
        in workflow
    )
    assert "Normalize all scanner reports\n        if: always()" in workflow
    assert "Enforce all-source zero critical/high gate\n        if: always()" in workflow
    assert (
        "Upload auditable security evidence even when gate fails\n        if: always()" in workflow
    )
