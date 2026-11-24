"""Fail-closed admission of *fixture-only* independent-audit reports.

Never upgrades an 18-domain anchor to current mastery. Only the original audit
SSOT defines anchors; the source report is retained as a bounded SQL event.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _sha(value: Any, length: int = 64) -> bool:
    return isinstance(value, str) and bool(re.fullmatch("[0-9a-f]{" + str(length) + "}", value))


def read_fixture_summary(report_raw: bytes, standard_raw: bytes) -> dict[str, Any]:
    """Bind a report to the exact SSOT. Its claims remain unverified.

    The checks detect malformed or drifted reports. They cannot establish
    auditor independence or raw JUnit authenticity without external review.
    """
    if not report_raw or len(report_raw) > 2_000_000:
        raise ValueError("independent_fixture_report_size")
    report = json.loads(report_raw)
    standard = json.loads(standard_raw)
    protocol = standard.get("digital_life_evaluation")
    if not isinstance(report, dict) or not isinstance(protocol, dict):
        raise ValueError("independent_fixture_protocol_missing")
    if (
        report.get("standard_sha256") != hashlib.sha256(standard_raw).hexdigest()
        or report.get("standard_version") != standard.get("standard_version")
        or report.get("scoring_version") != standard.get("scoring_version")
        or report.get("protocol_version") != protocol.get("protocol_version")
        or report.get("seeds") != protocol.get("seeds")
        or report.get("score", "invalid") is not None
        or report.get("domain_status") != "UNRATED"
        or report.get("evidence_scope") != "isolated_fixture_only_not_attested"
        or report.get("model_and_budget") != "fixture_only_no_live_model_claim"
    ):
        raise ValueError("independent_fixture_identity_or_scope_mismatch")
    if (
        not _sha(report.get("source_sha"), 40)
        or not _sha(report.get("auditor_source_sha"), 40)
        or report["source_sha"] == report["auditor_source_sha"]
        or not all(_sha(report.get(key)) for key in ("dataset_sha256", "environment_sha256"))
    ):
        raise ValueError("independent_fixture_provenance_missing")
    expected = {s["id"]: s["anchor"] for s in protocol["scenarios"]}
    statuses = {"PASS", "FAIL", "BLOCKED", "NOT RUN"}
    observed: dict[str, dict[str, str]] = {}
    for row in report.get("scenarios", []):
        if not isinstance(row, dict):
            raise ValueError("independent_fixture_malformed_scenario")
        ident = row.get("id")
        layers = row.get("layers")
        if (
            ident not in expected
            or ident in observed
            or row.get("anchor") != expected[ident]
            or not isinstance(layers, dict)
            or set(layers) != set(protocol["layers"])
            or layers.get("integration") not in statuses
            or any(value != "NOT RUN" for name, value in layers.items() if name != "integration")
        ):
            raise ValueError("independent_fixture_anchor_or_layer_mismatch")
        trials = row.get("trials")
        if not isinstance(trials, list):
            raise ValueError("independent_fixture_missing_trials")
        expected_trial_keys = {
            (kind, seed) for seed in protocol["seeds"] for kind in ("positive", "negative")
        }
        seen = set()
        for trial in trials:
            if not isinstance(trial, dict):
                raise ValueError("independent_fixture_malformed_trial")
            key = (trial.get("kind"), trial.get("seed"))
            if key not in expected_trial_keys or key in seen or trial.get("status") not in statuses:
                raise ValueError("independent_fixture_unexpected_trial")
            seen.add(key)
            if trial["status"] == "PASS" and (
                trial.get("returncode") != 0 or not _sha(trial.get("artifact_sha256"))
            ):
                raise ValueError("independent_fixture_pass_without_artifact")
        if layers["integration"] == "PASS" and (
            seen != expected_trial_keys or any(t["status"] != "PASS" for t in trials)
        ):
            raise ValueError("independent_fixture_incomplete_pass")
        if layers["integration"] == "NOT RUN" and trials:
            raise ValueError("independent_fixture_unrun_with_trials")
        observed[ident] = {"anchor": expected[ident], "integration": layers["integration"]}
    if set(observed) != set(expected):
        raise ValueError("independent_fixture_missing_scenario")
    return {
        "report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "standard_sha256": report["standard_sha256"],
        "source_sha": report["source_sha"],
        "auditor_source_sha": report["auditor_source_sha"],
        "dataset_sha256": report["dataset_sha256"],
        "environment_sha256": report["environment_sha256"],
        "scenarios": observed,
        "scope": "historical_fixture_claim_only_not_current_capability",
    }


def record_fixture_report(report_path: Path, standard_path: Path) -> dict[str, str]:
    """Operator CLI only: append a deduplicated original-ledger event."""
    from modstore_server.db.xiaoc_life import XiaoCLifeEvent
    from modstore_server.xiaoc_life_store import _event, _mutate

    report_raw = report_path.read_bytes()
    standard_raw = standard_path.read_bytes()
    summary = read_fixture_summary(report_raw, standard_raw)
    event_id = "self-fixture:" + summary["report_sha256"]

    def record(_data: dict[str, Any], session: Any) -> dict[str, str]:
        if session.get(XiaoCLifeEvent, event_id) is None:
            _event(
                session, event_id, kind="self_fixture_check",
                status="historical_fixture",
                summary="独立隔离回归报告登记，不证明模型、业务、生产或当前能力。",
                evidence_refs=["sha256:" + summary["report_sha256"]],
                details=summary,
            )
        return {"status": "historical_fixture", "evidence_ref": event_id}

    return _mutate(record)


def annotate_unverified_catalog(
    catalog: dict[str, Any], events: list[dict[str, Any]], *, current_sha: str | None
) -> dict[str, Any]:
    """Attach bounded fixture references without changing any anchor verdict."""
    if catalog.get("status") != "catalog_only":
        return catalog
    anchors = {row["anchor_id"]: row for row in catalog["anchors"]}
    seen: set[str] = set()
    for event in events[:20]:
        if event.get("kind") != "self_fixture_check" or event.get("status") != "historical_fixture":
            continue
        details = event.get("details") or {}
        ref = event.get("id")
        if (
            not isinstance(ref, str) or not ref.startswith("self-fixture:")
            or ref in seen or not _sha(details.get("report_sha256"))
            or ref != "self-fixture:" + details["report_sha256"]
            or details.get("standard_sha256") != catalog.get("standard_sha256")
            or not isinstance(details.get("scenarios"), dict)
        ):
            continue
        seen.add(ref)
        for key, row in details["scenarios"].items():
            if not isinstance(row, dict) or row.get("anchor") not in anchors:
                continue
            if row.get("integration") not in {"PASS", "FAIL", "BLOCKED", "NOT RUN"}:
                continue
            anchor = anchors[row["anchor"]]
            anchor.setdefault("fixture_history", [])
            if len(anchor["fixture_history"]) >= 3:
                continue
            anchor["fixture_history"].append({
                "scenario": key,
                "reported_integration": row["integration"],
                "evidence_ref": ref,
                "release_match": bool(current_sha and current_sha == details.get("source_sha")),
                "status": "unverified_fixture_claim_not_capability",
            })
    return catalog

def fixture_trend(events: list[dict[str, Any]], *, current_sha: str | None) -> dict[str, Any]:
    """Compare identical frozen fixture protocols across release SHAs only."""
    unavailable = {"status": "insufficient_comparable_fixture_evidence"}
    if not _sha(current_sha, 40):
        return unavailable
    valid: list[tuple[str, dict[str, Any]]] = []
    for event in events[:20]:
        details = event.get("details") or {}
        if (
            event.get("kind") != "self_fixture_check"
            or event.get("status") != "historical_fixture"
            or event.get("id") != "self-fixture:" + str(details.get("report_sha256"))
            or not _sha(details.get("report_sha256"))
            or not _sha(details.get("source_sha"), 40)
            or not isinstance(details.get("scenarios"), dict)
        ):
            continue
        valid.append((event["id"], details))
    current = next(((ref, row) for ref, row in valid if row["source_sha"] == current_sha), None)
    if current is None:
        return unavailable
    ref, latest = current
    keys = ("standard_sha256", "dataset_sha256", "environment_sha256", "auditor_source_sha")
    for prior_ref, prior in valid:
        if prior["source_sha"] == current_sha or any(prior.get(k) != latest.get(k) for k in keys):
            continue
        if set(prior["scenarios"]) != set(latest["scenarios"]):
            continue
        before = prior["scenarios"]
        after = latest["scenarios"]
        if any(
            not isinstance(before[k], dict)
            or not isinstance(after[k], dict)
            or before[k].get("anchor") != after[k].get("anchor")
            or before[k].get("integration") not in {"PASS", "FAIL", "BLOCKED", "NOT RUN"}
            or after[k].get("integration") not in {"PASS", "FAIL", "BLOCKED", "NOT RUN"}
            for k in before
        ):
            continue
        regression = sorted(
            k for k in before
            if before[k]["integration"] == "PASS" and after[k]["integration"] == "FAIL"
        )
        evidence_lost = sorted(
            k for k in before
            if before[k]["integration"] == "PASS"
            and after[k]["integration"] in {"BLOCKED", "NOT RUN"}
        )
        return {
            "status": "comparable_fixture_only_not_capability_degradation",
            "current_evidence_ref": ref,
            "historical_evidence_ref": prior_ref,
            "fixture_regressions_to_review": regression,
            "fixture_evidence_lost": evidence_lost,
            "rule": "fixture changes are not independently verified skill measurements",
        }
    return unavailable
