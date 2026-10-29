"""Synthetic manifest fixtures test the checker, not real product acceptance."""

import hashlib
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/audit_remediation_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("audit_acceptance_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_NOW = datetime(2026, 10, 29, tzinfo=UTC)
_CATALOG = {"standard_version": "fixture-standard", "scoring_version": "fixture-scoring"}


@pytest.fixture
def bundle(tmp_path):
    payload = b"synthetic validator fixture, not a product acceptance result\n"
    path = tmp_path / "fixture.txt"
    path.write_bytes(payload)
    raw = {"path": path.name, "sha256": hashlib.sha256(payload).hexdigest()}
    source = "a" * 40
    start, end = _NOW - timedelta(days=32), _NOW - timedelta(days=1)
    items = []
    for number in range(1, 16):
        item = {
            "id": number,
            "status": "passed",
            "source_sha": source,
            "evidence_level": "E4",
            "environment": "synthetic fixture",
            "command": "fixture",
            "expected_result": "fixture",
            "observed_result": "fixture",
            "operator": "fixture reviewer",
            "evidence": [dict(raw)],
            "observed_at": end.isoformat(),
            "execution_mode": "real",
            "installed_source_sha": source,
            "artifact_sha256": "b" * 64,
            "provider": "fixture",
            "model_version": "fixture",
            "budget": "fixture",
        }
        if number == 13:
            item["platforms"] = {
                platform: {"installed_source_sha": source, "artifact_sha256": "b" * 64}
                for platform in ("windows", "macos")
            }
        if number == 14:
            item["subsystems"] = [
                "java-payment",
                "flutter-mobile",
                "commerce-backend",
                "marketplace-ui",
            ]
        if number == 15:
            item["window_started_at"] = start.isoformat()
            item["daily_evidence"] = []
            for n in range((end - start).days):
                day = (start.date() + timedelta(days=n)).isoformat()
                content = ("synthetic observation " + day).encode()
                daily_path = tmp_path / f"day-{day}.txt"
                daily_path.write_bytes(content)
                item["daily_evidence"].append(
                    {
                        "date": day,
                        "path": daily_path.name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
        items.append(item)
    return {
        "schema_version": 1,
        "source_sha": source,
        **_CATALOG,
        "protocol": raw,
        "protocol_frozen_at": (_NOW - timedelta(days=35)).isoformat(),
        "items": items,
    }


def check(bundle, root):
    return _MODULE.check_bundle(bundle, root, _CATALOG, now=_NOW)


def test_complete_fixture_only_becomes_ready_for_review(bundle, tmp_path):
    result = check(bundle, tmp_path)
    assert result["checklist_status"] == "READY_FOR_INDEPENDENT_REVIEW"
    assert result["formal_status"] == "UNRATED" and result["score"] is None


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "unknown",
        "skipped",
        "wrong_source",
        "wrong_standard",
        "bad_hash",
        "missing_file",
        "traversal",
        "mock",
        "e2_instead_of_real",
        "wrong_install",
        "missing_artifact",
        "missing_macos",
        "missing_flutter",
        "missing_model",
        "future",
        "short_window",
        "missing_day",
        "missing_operator",
        "late_freeze",
        "null_items",
        "reused_day",
        "bad_level",
        "bad_subsystem",
    ],
)
def test_incomplete_or_misleading_claims_stay_blocked(bundle, tmp_path, change):
    item = bundle["items"][9]
    if change == "missing":
        bundle["items"].pop()
    elif change == "duplicate":
        bundle["items"][-1]["id"] = 1
    elif change in {"unknown", "skipped"}:
        item["status"] = change
    elif change == "wrong_source":
        item["source_sha"] = "c" * 40
    elif change == "wrong_standard":
        bundle["standard_version"] = "changed"
    elif change == "bad_hash":
        item["evidence"][0]["sha256"] = "c" * 64
    elif change == "missing_file":
        item["evidence"][0]["path"] = "missing.txt"
    elif change == "traversal":
        item["evidence"][0]["path"] = "../fixture.txt"
    elif change == "mock":
        item["execution_mode"] = "mock"
    elif change == "e2_instead_of_real":
        item["evidence_level"] = "E2"
    elif change == "wrong_install":
        item["installed_source_sha"] = "c" * 40
    elif change == "missing_artifact":
        item["artifact_sha256"] = "unknown"
    elif change == "missing_macos":
        bundle["items"][12]["platforms"].pop("macos")
    elif change == "missing_flutter":
        bundle["items"][13]["subsystems"].remove("flutter-mobile")
    elif change == "missing_model":
        item["model_version"] = ""
    elif change == "future":
        item["observed_at"] = (_NOW + timedelta(days=1)).isoformat()
    elif change == "short_window":
        bundle["items"][14]["window_started_at"] = (_NOW - timedelta(days=2)).isoformat()
    elif change == "missing_day":
        bundle["items"][14]["daily_evidence"].pop()
    elif change == "missing_operator":
        item["operator"] = ""
    elif change == "late_freeze":
        bundle["protocol_frozen_at"] = _NOW.isoformat()
    elif change == "null_items":
        bundle["items"] = None
    elif change == "reused_day":
        daily = bundle["items"][14]["daily_evidence"]
        daily[-1].update(path=daily[0]["path"], sha256=daily[0]["sha256"])
    elif change == "bad_level":
        item["evidence_level"] = {}
    elif change == "bad_subsystem":
        bundle["items"][13]["subsystems"] = [{}]
    result = check(bundle, tmp_path)
    assert result["checklist_status"] == "BLOCKED"
    assert result["score"] is None


def test_symlink_evidence_and_empty_files_are_rejected(bundle, tmp_path):
    original = tmp_path / "fixture.txt"
    target = tmp_path / "linked.txt"
    target.symlink_to(original)
    bundle["items"][0]["evidence"][0]["path"] = target.name
    assert check(bundle, tmp_path)["checklist_status"] == "BLOCKED"
    original.write_bytes(b"")
    bundle["protocol"]["sha256"] = hashlib.sha256(b"").hexdigest()
    assert check(bundle, tmp_path)["checklist_status"] == "BLOCKED"


def test_nonobject_manifest_is_blocked(tmp_path):
    assert check([], tmp_path)["checklist_status"] == "BLOCKED"
