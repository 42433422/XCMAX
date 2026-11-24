"""Bounded receipt projection and actual OpenTelemetry span/counter contracts."""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from modstore_server import xiaoc_life_telemetry as telemetry
from modstore_server.xiaoc_life_checkpoint import (
    make_checkpoint,
    recover_checkpoint,
    same_checkpoint,
    zero_usage_checkpoint_compatible,
)


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
        with telemetry.life_operation("graph", cycle_id="secret-cycle-id"):
            pass
        trace_span = exporter.get_finished_spans()[-1]
        assert trace_span.attributes["xiaoc.cycle_sha256"] != "secret-cycle-id"
        assert len(trace_span.attributes["xiaoc.cycle_sha256"]) == 64
        assert "secret-cycle-id" not in str(trace_span.attributes)
        with telemetry.life_operation("tick"):
            pass
        assert telemetry.PROCESS_CPU_SECONDS._value.get() >= 0
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("empty", True),
        ("zero_act", True),
        ("zero_both", True),
        ("nonzero", False),
        ("unknown", False),
        ("earlier_nonzero", False),
        ("later_unknown", False),
        ("reflect_without_act", False),
        ("tampered", False),
        ("wrong_owner", False),
        ("wrong_cycle", False),
        ("wrong_revision", False),
        ("wrong_phase", False),
        ("invalid_container", False),
    ],
)
def test_empty_journal_cannot_override_returned_checkpoint(case, expected):
    zero = _checkpoint(actual_tokens=0)
    reflect = _checkpoint("reflect", actual_tokens=0)
    binding = {"cycle_id": "cycle-1", "owner_user_id": 7, "policy_revision": 3}
    records = {
        "empty": {},
        "zero_act": {"act": zero},
        "zero_both": {"act": zero, "reflect": reflect},
        "nonzero": {"act": _checkpoint(actual_tokens=10)},
        "unknown": {"act": _checkpoint(actual_tokens=None)},
        "earlier_nonzero": {"act": _checkpoint(), "reflect": reflect},
        "later_unknown": {"act": zero, "reflect": _checkpoint("reflect", None)},
        "reflect_without_act": {"reflect": reflect},
        "tampered": {"act": {**zero, "sha256": "invalid"}},
        "wrong_owner": {"act": zero},
        "wrong_cycle": {"act": zero},
        "wrong_revision": {"act": zero},
        "wrong_phase": {"act": reflect},
        "invalid_container": [],
    }[case]
    if case == "wrong_owner":
        binding["owner_user_id"] = 8
    elif case == "wrong_cycle":
        binding["cycle_id"] = "other"
    elif case == "wrong_revision":
        binding["policy_revision"] = 4
    assert zero_usage_checkpoint_compatible(records, **binding) is expected
