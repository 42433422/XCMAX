from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

FHD_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_JOBS = {"fhd-api-stable": "fhd", "modstore-api-production": "modstore"}


def _load(relative: str) -> dict:
    return yaml.safe_load((FHD_ROOT / relative).read_text(encoding="utf-8"))


def test_production_prometheus_scrapes_every_slo_runtime_with_truth_labels() -> None:
    payload = _load("ops/monitoring/prometheus.production.yml")
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
    config = _load("ops/monitoring/prometheus.production.yml")
    real = {
        (job["job_name"], entry["targets"][0], entry["labels"]["service"])
        for job in config["scrape_configs"]
        for entry in job.get("static_configs", [])
        if entry["labels"]["environment"] == "production"
    }
    rules = [
        rule
        for group in _load("ops/monitoring/production-alerts.yml")["groups"]
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
    config = _load("ops/monitoring/alertmanager.production.yml")
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


def test_metrics_endpoint_exports_committed_agent_metrics_and_existing_http_metrics(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from prometheus_client.parser import text_string_to_metric_families

    from app.fastapi_app.middleware_extra import register_prometheus_metrics
    from app.infrastructure.observability import metrics
    from app.utils.metrics import record_api_request

    monkeypatch.delenv("XCAGI_METRICS", raising=False)
    app = FastAPI()
    register_prometheus_metrics(app)
    with TestClient(app) as client:
        before = client.get("/metrics")
        assert before.status_code == 200
        metrics.observe_run_terminal(status="failed")
        record_api_request("GET", "/api/health", 200)
        after = client.get("/metrics")
        repeat = client.get("/metrics")
    assert after.status_code == repeat.status_code == 200
    assert after.headers["content-type"].startswith("text/plain")

    def samples(body):
        values = {}
        for family in text_string_to_metric_families(body):
            for sample in family.samples:
                key = (sample.name, tuple(sorted(sample.labels.items())))
                assert key not in values, f"duplicate exported metric: {key}"
                values[key] = sample.value
        return values

    prior, latest, repeated = map(samples, (before.text, after.text, repeat.text))
    agent = ("xcagi_run_terminal_total", (("status", "failed"),))
    assert latest[agent] == prior.get(agent, 0) + 1
    assert repeated[agent] == latest[agent], "scraping must not create task outcomes"
    assert any(key[0] == "api_requests_total" for key in latest)
    assert any(key[0] == "process_start_time_seconds" for key in latest)


def test_agent_dashboard_uses_file_provisioning_model_and_isolated_scrape_job():
    dashboard = json.loads(
        (FHD_ROOT / "ops/monitoring/grafana/provisioning/dashboards/fhd.json").read_text(
            encoding="utf-8"
        )
    )
    assert "dashboard" not in dashboard, "HTTP API envelopes are not file provisioning models"
    assert dashboard["uid"] == "fhd-performance", "retain the existing dashboard URL"
    assert dashboard["title"] and dashboard["refresh"] == "15s"
    assert len({panel["id"] for panel in dashboard["panels"]}) == len(dashboard["panels"])
    job = next(item for item in dashboard["templating"]["list"] if item["name"] == "job")
    assert job["current"]["value"] == "fhd-api-stable"
    assert not job["multi"] and not job["includeAll"], "production and staging must not be pooled"
    for panel in dashboard["panels"]:
        assert panel["type"] in {"timeseries", "stat"}
        assert panel["fieldConfig"]["defaults"]["noValue"]
        assert all('job="$job"' in target["expr"] for target in panel["targets"])
