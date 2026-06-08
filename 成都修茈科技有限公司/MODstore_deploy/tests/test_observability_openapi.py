from __future__ import annotations


def test_metrics_endpoint_exposes_prometheus_text(client):
    r = client.get("/metrics")

    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "modstore_http_requests_total" in r.text


def test_openapi_tags_include_business_domains(client):
    r = client.get("/openapi.json")

    assert r.status_code == 200
    tags = {row["name"] for row in r.json().get("tags", [])}
    assert {"payment", "workflow", "webhooks", "refunds", "catalog"}.issubset(tags)
    assert {"employees", "llm", "realtime", "notifications", "auth", "market"}.issubset(tags)
    health = r.json()["paths"]["/api/health"]["get"]
    assert "200" in health["responses"]
    assert health["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "HealthResponse"
    )
