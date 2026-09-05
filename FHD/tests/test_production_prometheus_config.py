from __future__ import annotations

from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]


def test_production_prometheus_scrapes_every_slo_runtime_with_truth_labels() -> None:
    payload = yaml.safe_load(
        (FHD_ROOT / "monitoring/prometheus.production.yml").read_text(encoding="utf-8")
    )
    jobs = {row["job_name"]: row for row in payload["scrape_configs"]}
    assert set(jobs) == {
        "fhd-api-stable",
        "fhd-api-staging",
        "modstore-api-production",
    }
    stable = jobs["fhd-api-stable"]["static_configs"][0]
    staging = jobs["fhd-api-staging"]["static_configs"][0]
    modstore = jobs["modstore-api-production"]["static_configs"][0]
    assert stable["labels"]["environment"] == "production"
    assert staging["labels"]["environment"] == "staging"
    assert modstore["labels"]["environment"] == "production"
    assert modstore["targets"] == ["127.0.0.1:9999"]


def test_prometheus_installer_is_atomic_validated_and_recoverable() -> None:
    script = (FHD_ROOT / "scripts/observability/install_production_prometheus_config.sh").read_text(
        encoding="utf-8"
    )
    assert "promtool" in script
    assert 'mv -f "${target}.next" "$target"' in script
    assert "restored" in script
    assert "--storage.tsdb.retention.time=120d" in script
    assert "modstore-api-production" in script
    assert "environment" in script
    assert "health" in script
