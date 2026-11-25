"""Perception health must fail closed on missing, stale or revoked source evidence."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.application.enterprise_cognition.perception import observe_enterprise
from app.application.enterprise_cognition.service import cognition_result_verified
from app.domain.enterprise_cognition.contracts import CognitionRequest, INPUT_MODELS

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
SCOPE = {"tenant_id": "11", "actor_id": "7", "mod_id": ""}


def _snapshot(entity_type="journal_entry", entity_id="620", **overrides):
    source = {
        "journal_entry": "journal_entries",
        "order": "sales_orders",
        "customer": "customers",
    }.get(entity_type, entity_type)
    version = "a" * 64
    row = {
        **SCOPE,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": source,
        "read_only": True,
        "freshness": "fresh",
        "knowledge_kind": "fact",
        "state": {
            "status": "posted",
            "debit_total": "10.00",
            "credit_total": "9.00",
        },
        "source_version": "sha256:" + version,
        "observed_at": (NOW - timedelta(seconds=1)).isoformat(),
        "expires_at": (NOW + timedelta(seconds=29)).isoformat(),
        "evidence": [
            {
                "tenant_id": SCOPE["tenant_id"],
                "actor_id": SCOPE["actor_id"],
                "mod_id": SCOPE["mod_id"],
                "source": source,
                "row_id": entity_id,
                "content_sha256": version,
            }
        ],
    }
    return {**row, **overrides}


class ProjectionStub:
    def __init__(self, by_type=None, *, denied=(), revoke_on=(), has_more=()):
        self.by_type = by_type or {}
        self.denied = set(denied)
        self.revoke_on = set(revoke_on)
        self.more = set(has_more)
        self.calls = []

    def list_refs(self, entity_type, *, limit, **scope):
        self.calls.append(("list", entity_type, limit, scope))
        if entity_type in self.denied:
            raise PermissionError("enterprise_permission_denied")
        rows = self.by_type.get(entity_type, [])
        return {
            "refs": [
                {"entity_type": entity_type, "entity_id": row["entity_id"]}
                for row in rows[:limit]
            ],
            "has_more": entity_type in self.more or len(rows) > limit,
            "freshness": "fresh",
        }

    def get(self, entity_type, entity_id, *, force_refresh, **scope):
        self.calls.append(("get", entity_type, entity_id, force_refresh, scope))
        if (entity_type, entity_id) in self.revoke_on:
            raise PermissionError("enterprise_permission_denied")
        return next(
            row
            for row in self.by_type[entity_type]
            if row["entity_id"] == entity_id
        )


def _observe(reader, **kwargs):
    return observe_enterprise(reader, **SCOPE, now=NOW, **kwargs)


def test_empty_authoritative_reads_never_fabricate_zero_business_metrics():
    reader = ProjectionStub()
    result = _observe(reader)
    assert result["source_checks_completed"] is True
    assert result["observation_verified"] is False
    assert result["enterprise_wide_verified"] is False
    assert result["business_metrics_verified"] is False
    assert result["domains"]["B01"]["required_metrics"]["cash_flow"]["knowledge_kind"] == "unknown"
    assert result["domains"]["B02"]["required_metrics"]["churn_risk"]["knowledge_kind"] == "unknown"
    assert result["domains"]["B03"]["required_metrics"]["conversion_rate"]["knowledge_kind"] == "unknown"
    assert result["domains"]["B04"]["status"] == "not_connected"
    assert result["domains"]["B05"]["status"] == "not_connected"
    assert result["domains"]["B06"]["status"] == "not_connected"
    assert result["domains"]["B08"]["status"] == "not_connected"
    assert result["domains"]["B10"]["source_statuses"]["fund"] == "no_visible_records"
    assert result["anomaly_candidates"] == []


def test_source_backed_journal_mismatch_is_read_only_deterministic_review_candidate():
    reader = ProjectionStub({"journal_entry": [_snapshot()]})
    first = _observe(reader)
    second = _observe(reader)
    assert first["observed_fact_count"] == 1
    assert first["domains"]["B01"]["status"] == "partially_observed"
    assert first["domains"]["B09"]["proactive_detection_verified"] is False
    assert first["business_data_written"] is False
    (candidate,) = first["anomaly_candidates"]
    assert candidate["kind"] == "journal_unbalanced"
    assert candidate["knowledge_kind"] == "inference"
    assert candidate["requires_human_review"] is True
    assert candidate["execution_authorized"] is False
    assert candidate["source_version"] == _snapshot()["source_version"]
    assert second["anomaly_candidates"][0]["candidate_id"] == candidate["candidate_id"]
    assert all(
        call[-1] == SCOPE
        for call in reader.calls
        if call[0] in {"list", "get"}
    )


def test_balanced_or_unposted_journals_never_infer_unbalanced_alert():
    for state in [
        {"status": "posted", "debit_total": "10", "credit_total": "10.00"},
        {"status": "draft", "debit_total": "10", "credit_total": "9"},
        {"status": "posted", "debit_total": None, "credit_total": "9"},
    ]:
        result = _observe(ProjectionStub({"journal_entry": [_snapshot(state=state)]}))
        assert result["observed_fact_count"] == 1
        assert result["anomaly_candidates"] == []


def test_expired_or_corrupted_snapshot_is_not_displayed_as_current_fact():
    rows = [
        _snapshot(expires_at=(NOW - timedelta(seconds=1)).isoformat()),
        _snapshot(evidence=[]),
        _snapshot(tenant_id="22"),
        _snapshot(source_version="sha256:not-a-hash"),
        _snapshot(observed_at=(NOW + timedelta(minutes=5)).isoformat()),
    ]
    for row in rows:
        result = _observe(ProjectionStub({"journal_entry": [row]}))
        source = result["domains"]["B01"]["sources"][1]
        assert source["status"] in {"stale", "unknown"}
        assert result["observed_fact_count"] == 0
        assert result["anomaly_candidates"] == []
        assert all("snapshot" not in item for item in source["samples"])


def test_permission_revoked_between_list_and_read_discards_all_sampled_evidence():
    first = _snapshot()
    second = _snapshot(entity_id="621")
    reader = ProjectionStub(
        {"journal_entry": [first, second]},
        revoke_on={("journal_entry", "621")},
    )
    result = _observe(reader)
    journal = result["domains"]["B01"]["sources"][1]
    assert journal["status"] == "permission_denied"
    assert journal["samples"] == []
    assert result["observed_fact_count"] == 0
    assert result["anomaly_candidates"] == []


def test_list_permission_denial_does_not_expose_customer_records_or_count():
    reader = ProjectionStub({"customer": [_snapshot("customer", "4")]}, denied={"customer"})
    result = _observe(reader)
    customer = result["domains"]["B02"]
    assert customer["status"] == "unknown"
    assert customer["sources"][0] == {
        "source": "customer", "status": "permission_denied", "samples": []
    }
    assert not any(call[0] == "get" and call[1] == "customer" for call in reader.calls)


def test_bounded_sampling_cannot_be_claimed_as_full_enterprise_coverage():
    reader = ProjectionStub({"order": [_snapshot("order", "12")]}, has_more={"order"})
    result = _observe(reader, limit_per_source=1)
    assert result["domains"]["B03"]["sources"][0]["status"] == "partial_sample"
    assert result["enterprise_wide_verified"] is False
    assert result["domains"]["B03"]["required_metrics"]["conversion_rate"]["knowledge_kind"] == "unknown"


def test_diagnostic_contract_rejects_client_identity_and_unbounded_scan():
    assert CognitionRequest(action="perceive", params={}).action == "perceive"
    assert cognition_result_verified("perceive", {}, {"source_checks_completed": True})
    assert not cognition_result_verified("perceive", {}, {"source_checks_completed": False})
    for invalid in [{"limit_per_source": 6}, {"limit_per_source": True}, {"tenant_id": 22}]:
        with pytest.raises(ValidationError):
            INPUT_MODELS["perceive"].model_validate(invalid)
