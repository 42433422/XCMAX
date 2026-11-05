from __future__ import annotations

import re
from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_JOBS = {"fhd-api-stable": "fhd", "modstore-api-production": "modstore"}


def _load(relative: str) -> dict:
    return yaml.safe_load((FHD_ROOT / relative).read_text(encoding="utf-8"))


def test_production_prometheus_scrapes_every_slo_runtime_with_truth_labels() -> None:
    payload = _load("monitoring/prometheus.production.yml")
    jobs = {row["job_name"]: row for row in payload["scrape_configs"]}
    assert set(jobs) == {
        "fhd-api-stable",
        "fhd-api-staging",
        "modstore-api-production",
        "alert-drill",
    }
    stable = jobs["fhd-api-stable"]["static_configs"][0]
    staging = jobs["fhd-api-staging"]["static_configs"][0]
    modstore = jobs["modstore-api-production"]["static_configs"][0]
    assert stable["labels"]["environment"] == "production"
    assert staging["labels"]["environment"] == "staging"
    assert modstore["labels"]["environment"] == "production"
    assert modstore["targets"] == ["127.0.0.1:9999"]
    for job, service in PRODUCTION_JOBS.items():
        assert jobs[job]["static_configs"][0]["labels"]["service"] == service
    assert "static_configs" not in jobs["alert-drill"]
    assert payload["rule_files"] == ["production-alerts.yml"]
    managers = payload["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert managers == ["127.0.0.1:19093"]


def test_production_alert_rules_select_only_real_targets() -> None:
    config = _load("monitoring/prometheus.production.yml")
    real = {
        (job["job_name"], entry["targets"][0], entry["labels"]["service"])
        for job in config["scrape_configs"]
        for entry in job.get("static_configs", [])
        if entry["labels"]["environment"] == "production"
    }
    rules = [
        rule for group in _load("monitoring/production-alerts.yml")["groups"]
        for rule in group["rules"]
    ]
    assert rules
    for rule in rules:
        expr = rule["expr"]
        assert rule["labels"]["severity"] in {"critical", "warning", "drill"}
        if rule["labels"]["severity"] == "drill":
            assert 'environment="drill"' in expr
            continue
        assert 'environment="production"' in expr
        for job in re.findall(r'job=~?"([^"]+)"', expr):
            assert set(job.split("|")) <= {name for name, _instance, _service in real}
        for job, instance in re.findall(r'job="([^"]+)",service="[^"]+",instance="([^"]+)"', expr):
            assert any(job == name and instance == inst for name, inst, _service in real)
    assert {"XcmaxProductionTargetDown", "XcmaxProductionScrapeCoverageBelow99"} <= {
        rule["alert"] for rule in rules
    }


def test_alertmanager_routes_every_alert_to_secret_ops_channel() -> None:
    config = _load("monitoring/alertmanager.production.yml")
    receivers = {row["name"]: row for row in config["receivers"]}
    assert set(receivers) == {"ops-webhook"}
    hook = receivers["ops-webhook"]["webhook_configs"][0]
    assert "url" not in hook
    assert hook["url_file"] == "/etc/alertmanager/secrets/ops_webhook_url"
    assert hook["send_resolved"] is True
    assert config["route"]["receiver"] == "ops-webhook"


def test_prometheus_installer_is_atomic_validated_and_recoverable() -> None:
    script = (FHD_ROOT / "scripts/observability/install_production_prometheus_config.sh").read_text(
        encoding="utf-8"
    )
    ensure = (FHD_ROOT / "scripts/observability/ensure_production_prometheus.sh").read_text(
        encoding="utf-8"
    )
    assert "promtool" in script
    assert "amtool" in script
    assert 'mv -f "${target}.next" "$target"' in script
    assert "restored" in script
    assert "ensure_production_prometheus.sh" in script
    assert "--storage.tsdb.retention.time=120d" in ensure
    assert "docker start" in ensure
    assert "docker run" not in ensure
    assert "modstore-api-production" in script
    assert "/api/v1/rules" in script
    assert "/api/v1/alertmanagers" in script
    assert "OPS_ALERT_WEBHOOK_URL" in script


def test_alert_drill_records_full_timeline_and_always_cleans_up() -> None:
    script = (FHD_ROOT / "scripts/observability/run_alert_drill.sh").read_text(encoding="utf-8")
    for step in (
        "injected",
        "firing",
        "alertmanager_received",
        "notified",
        "handled",
        "resolved",
        "resolved_notified",
    ):
        assert f'"{step}"' in script
    assert "trap 'rm -f \"$sd_file\"' EXIT" in script
    assert '"environment": "drill"' in script
