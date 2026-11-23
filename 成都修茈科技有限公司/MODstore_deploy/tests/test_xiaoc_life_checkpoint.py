"""Bounded receipt projection and actual OpenTelemetry span/counter contracts."""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from modstore_server import xiaoc_life_telemetry as telemetry
from modstore_server.xiaoc_life_checkpoint import make_checkpoint, recover_checkpoint, same_checkpoint


def _checkpoint(phase="act", actual_tokens=10, recorded_at="2026-11-24T00:00:00+00:00"):
    return make_checkpoint(
        {"cycle_id": "cycle-1", "owner_user_id": 7, "policy_revision": 3, "lease_token": "secret"},
        phase,
        result={
            "status": "completed",
            "facts": [{"private": "private-content"}],
            "goals": [{"id": "g1", "decision_id": "d1", "description": "private-content"}],
        },
        actual_tokens=actual_tokens,
        evidence_refs=["receipt:one", "receipt:one", "x" * 257],
        reflection_status=None,
        recorded_at=recorded_at,
    )


def _recover(records, **changes):
    return recover_checkpoint(
        records,
        **{
            "cycle_id": "cycle-1",
            "owner_user_id": 7,
            "policy_revision": 3,
            "actual_tokens": 10,
            **changes,
        },
    )


def test_projection_excludes_raw_state_and_binds_original_identity():
    entry = _checkpoint()
    assert "secret" not in str(entry) and "private-content" not in str(entry)
    assert entry["evidence_refs"] == ["receipt:one"]
    assert entry["result_refs"] == ["goal:g1", "portfolio:d1"]
    recovered = _recover({"act": entry})
    assert recovered["usage_matches_reported"] is True
    assert not recovered["business_outcome_verified"] and not recovered["replayed"]
    assert _recover({"act": entry}, owner_user_id=8)["status"] == "invalid_checkpoint"
    tampered = {**entry, "reported_tokens": 99}
    assert _recover({"act": tampered})["status"] == "invalid_checkpoint"


def test_newest_reflection_selected_but_unknown_usage_is_not_proof():
    act = _checkpoint()
    reflect = _checkpoint("reflect", None)
    result = _recover({"act": act, "reflect": reflect})
    assert result["phase"] == "reflect" and result["usage_matches_reported"] is None
    assert same_checkpoint(act, _checkpoint(recorded_at="2026-11-24T00:00:01+00:00"))
    assert not same_checkpoint(act, {**act, "recorded_at": "later", "sha256": "different"})
    assert not same_checkpoint(act, _checkpoint(actual_tokens=2))


def test_otel_and_prometheus_observe_return_error_and_cancel_without_payload(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    try:
        gauge = telemetry.ACTIVE.labels("observe")
        before = gauge._value.get()
        with telemetry.life_operation("observe"):
            assert gauge._value.get() == before + 1
        assert gauge._value.get() == before
        with pytest.raises(RuntimeError), telemetry.life_operation("act"):
            raise RuntimeError("private-error")
        with pytest.raises(asyncio.CancelledError), telemetry.life_operation("reflect"):
            raise asyncio.CancelledError()
        spans = exporter.get_finished_spans()
        assert [span.attributes["xiaoc.outcome"] for span in spans] == [
            "returned",
            "error",
            "cancelled",
        ]
        assert all(not span.events for span in spans)
        assert all("private-error" not in str(span.attributes) for span in spans)
        for stage in ("act", "reflect"):
            assert telemetry.ACTIVE.labels(stage)._value.get() == 0
    finally:
        provider.shutdown()
