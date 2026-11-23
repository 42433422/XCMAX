"""Production Sloth alert rules must remain aligned with the existing SLO SSOT.

These are rule-generation and parser regression tests, not claims of live SLO
compliance or physical-device acceptance.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.observability import collect_slo_metrics as slo

SLOTH_SPEC = Path(__file__).resolve().parents[2] / "scripts/observability/sloth.production.yml"
EVENT_BASED_TARGETS = {
    "api-availability": ("SLO-API-01", 99.9, "api_requests_total"),
    "neurobus-delivery": ("SLO-BUS-01", 99.95, "neurobus_events_published_total"),
    "customer-operation-success": ("SLO-BIZ-02", 99.5, "customer_op_total"),
    "external-mod-install-success": ("SLO-BIZ-05", 99.0, "mod_install_total"),
}


def test_sloth_v1_events_match_live_slo_contract() -> None:
    spec = yaml.safe_load(SLOTH_SPEC.read_text(encoding="utf-8"))
    assert spec["version"] == "prometheus/v1"
    assert spec["service"] == "xcagi-production"
    assert spec["labels"]["environment"] == "production"
    names = {entry["name"] for entry in spec["slos"]}
    assert names == set(EVENT_BASED_TARGETS)
    assert len(spec["slos"]) == len(names)
    for entry in spec["slos"]:
        name = entry["name"]
        slo_id, objective, total_metric = EVENT_BASED_TARGETS[name]
        assert entry["objective"] == objective
        assert round(slo.TARGETS[slo_id][1] * 100, 4) == (
            objective
            if slo.TARGETS[slo_id][2] == "ge"
            else 100 - objective
        )
        queries = entry["sli"]["events"]
        assert set(queries) == {"error_query", "total_query"}
        assert total_metric in queries["total_query"]
        assert total_metric in slo.SAMPLE_QUERIES[slo_id]
        assert "{{.window}}" in queries["total_query"]
        assert "{{.window}}" in queries["error_query"]
        assert 'environment="production"' in queries["total_query"]
        assert 'environment="production"' in queries["error_query"]
        assert entry["alerting"]["name"].startswith("XCAGI")

    # Sloth burn alerts and production eligibility are separate gates:
    # only the original collector enforces missing-source and sample floors.
    assert (
        slo.telemetry_admissible(
            {
                "source_status": "available",
                "coverage": 1.0,
                "scrape_coverage": 0.0,
                "readings": {},
            }
        )
        is False
    )


@pytest.mark.parametrize(
    "raw", ["NaN", "nan", "+Inf", "-Inf", "inf", "-inf", "1e999", "", "broken"]
)
def test_prometheus_non_finite_samples_are_missing_evidence(raw: str) -> None:
    assert slo._numeric(raw) is None


def test_prometheus_numeric_sample_preserved() -> None:
    assert slo._numeric("0.0005") == 0.0005


def test_prometheus_multiple_series_refused() -> None:
    response = {
        "status": "success",
        "data": {"result": [{"value": [0, "1"]}, {"value": [0, "0"]}]},
    }
    with patch.object(slo, "_prom_get", return_value=response):
        with pytest.raises(ValueError, match="ambiguous_series"):
            slo.prom_query("http://127.0.0.1:9091", "sum(metric)", attempts=1)


def test_prometheus_broken_vector_refused() -> None:
    response = {
        "status": "success",
        "data": {"result": [{"value": ["only timestamp"]}]},
    }
    with patch.object(slo, "_prom_get", return_value=response):
        with pytest.raises(ValueError, match="invalid_sample"):
            slo.prom_query("http://127.0.0.1:9091", "sum(metric)", attempts=1)


def test_prometheus_empty_vector_is_unknown_not_zero() -> None:
    response = {"status": "success", "data": {"result": []}}
    with patch.object(slo, "_prom_get", return_value=response):
        assert slo.prom_query("http://127.0.0.1:9091", "sum(metric)", attempts=1) is None

def test_ambiguous_production_telemetry_persists_red_evidence(tmp_path: Path) -> None:
    """A live source returning multiple series cannot silently certify one subset."""
    ambiguous = {
        "status": "success",
        "data": {"result": [{"value": [0, "1"]}, {"value": [0, "0"]}]},
    }
    out = tmp_path / "production-slo.json"
    with (
        patch.object(slo, "measure_retention_days", return_value=120.0),
        patch.object(slo, "_prom_get", return_value=ambiguous),
    ):
        evidence, passed = slo.collect(
            prom_url="http://127.0.0.1:9091",
            prom_token="test-only-token",
            window="1d",
            mode="preflight",
            release_id="",
            raw_retention_days=120,
            out_path=out,
        )

    assert passed is False
    assert evidence["all_pass"] is False
    assert evidence["day0_eligible"] is False
    assert evidence["coverage"] == 0
    assert evidence["scrape_coverage"] == 0
    assert any("scrape_source_unavailable:ValueError" in e for e in evidence["source_errors"])
    assert slo.telemetry_admissible(evidence) is False
    assert out.is_file()
