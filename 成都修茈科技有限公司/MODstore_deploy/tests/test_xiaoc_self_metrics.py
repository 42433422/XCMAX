"""Deterministic tests for the narrow self-metrics evidence contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from modstore_server.xiaoc_self_metrics import (
    accrual_projection,
    audit_projection,
    completion_review,
)

SCOPE = "exact-scope"


def cycle(key, *, calls=(), tokens=3, scope=SCOPE, completed=True, day=0, model="m"):
    return {
        "id": "cycle:" + key,
        "kind": "enterprise",
        "model": model,
        "status": "completed" if completed else "failed",
        "created_at": (datetime(2026, 11, 24, tzinfo=UTC) + timedelta(minutes=day)).isoformat(),
        "actual_tokens": tokens,
        "details": {
            "execution_scope": scope,
            "owner_user_id": 7,
            "outbound_journal_version": 1,
            "steps": [{"kind": "model", "request_id": call} for call in calls],
        },
    }


def settled(tokens=3, cents=2):
    return {
        "status": "settled",
        "actual_tokens": tokens,
        "accrued_cost_cents": cents,
        "cost_basis": "approved_company_tariff_accrual",
    }


def test_accrual_uses_exact_calls_and_partial_not_total():
    rows = [
        cycle("known", calls=["r1"]),
        cycle("unknown", calls=["r2"]),
        cycle("old", calls=["r3"], scope="old"),
        cycle("empty", tokens=0),
    ]
    receipts = {"r1": settled(), "r3": settled(cents=900)}
    result = accrual_projection(SCOPE, rows, lambda key: receipts.get(key[3]))
    assert result["known_accrued_cents"] == 2
    assert result["cost_cents"] is None
    assert result["known_cycle_count"] == 2
    assert result["unknown_cycle_count"] == 1
    assert result["supplier_cost_cents"] is None


def test_duplicate_cross_cycle_call_is_ambiguous_even_if_settled():
    rows = [cycle("a", calls=["r1"]), cycle("b", calls=["r1"])]
    result = accrual_projection(SCOPE, rows, lambda _: settled())
    assert result["cost_cents"] is None
    assert result["unknown_cycle_count"] == 2


def test_wrong_token_total_or_unsettled_or_estimated_cost_is_not_real():
    row = cycle("a", calls=["r1"])
    for invalid in (
        settled(tokens=2),
        {**settled(), "status": "pending"},
        {**settled(), "cost_basis": "estimated"},
        {**settled(), "accrued_cost_cents": True},
    ):
        assert accrual_projection(SCOPE, [row], lambda _: invalid)["cost_cents"] is None


def test_missing_journal_does_not_imply_zero_cost():
    row = cycle("a", tokens=0)
    row["details"]["outbound_journal_version"] = None
    assert accrual_projection(SCOPE, [row], lambda _: None)["cost_cents"] is None


def test_portfolio_total_cannot_substitute_for_missing_call_id():
    row = cycle("a", tokens=0)
    row["details"]["steps"] = [{"kind": "portfolio", "decision_id": "d"}]
    assert accrual_projection(SCOPE, [row], lambda _: settled())["cost_cents"] is None


def test_completion_drop_compares_disjoint_same_model_scope_only():
    rows = [cycle(str(i), day=i, completed=i < 10) for i in range(20)]
    rows += [cycle("old", scope="old", day=100), cycle("other", model="other", day=101)]
    result = completion_review(SCOPE, rows)
    assert result["status"] == "review_recommended"
    groups = {row["model"]: row for row in result["groups"]}
    assert groups["m"]["baseline_completion_rate"] == 1
    assert groups["m"]["recent_completion_rate"] == 0
    assert not set(groups["m"]["recent_refs"]) & set(groups["m"]["baseline_refs"])
    assert groups["other"]["status"] == "insufficient_evidence"


def test_unknown_and_unversioned_receipts_are_not_success_or_failure():
    rows = [cycle(str(i), day=i) for i in range(19)]
    unknown = cycle("unknown", day=30)
    unknown.update(status="unknown", actual_tokens=None)
    result = completion_review(SCOPE, rows + [unknown, cycle("old", scope="old", day=31)])
    assert result["status"] == "insufficient_evidence"
    assert result["excluded_unmeasured"] == 1



def test_conflicting_receipt_does_not_inflate_completion_or_hide_risk():
    originals = [cycle(str(index), day=index) for index in range(20)]
    conflict = {**originals[-1], "status": "failed"}
    result = completion_review(SCOPE, originals + [conflict])
    assert result["conflicting_cycle_receipts"] == 1
    assert result["status"] == "review_recommended"
    assert result["groups"][0]["sample_count"] == 19
    assert result["groups"][0]["status"] == "insufficient_evidence"


def test_audit_catalog_requires_exact_18_domains_and_108_anchors(monkeypatch, tmp_path):
    from modstore_server import strategy_bets, strategy_planner

    catalog_dir = tmp_path / "FHD" / "config"
    catalog_dir.mkdir(parents=True)
    catalog_path = catalog_dir / "audit_benchmark_ssot.json"
    domains = [
        {
            "id": f"D{i:02d}",
            "anchor_60": [{"id": f"D{i:02d}-A{j}"} for j in range(3)],
            "anchor_90": [{"id": f"D{i:02d}-B{j}"} for j in range(3)],
        }
        for i in range(18)
    ]
    catalog = {
        "standard_version": "fixture-v1",
        "scoring_version": "fixture-score-v1",
        "domain_count": 18,
        "domains": domains,
    }

    def persist():
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    persist()
    monkeypatch.setattr(strategy_bets, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        strategy_planner,
        "_domain_status",
        lambda: {"domains": [{"domain_id": "D00", "status": "PASS"}]},
    )
    report = audit_projection()
    assert report["status"] == "catalog_only"
    assert report["domain_count"] == 18
    assert report["anchor_count"] == 108
    assert report["standard_sha256"] == hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    assert report["historical_domains"]["D00"]["status"] == "PASS"
    assert all(item["status"] == "unverified" for item in report["anchors"])

    # A shorter catalog cannot quietly improve measured coverage by dropping a test.
    catalog["domains"][0]["anchor_60"].pop()
    persist()
    assert audit_projection() == {"status": "unknown", "reason": "audit_source_unavailable"}

    # Duplicated anchors do not count as independently registered capabilities.
    catalog["domains"][0]["anchor_60"].append(catalog["domains"][1]["anchor_60"][0])
    persist()
    assert audit_projection() == {"status": "unknown", "reason": "audit_source_unavailable"}
