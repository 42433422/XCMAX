from pathlib import Path


def test_compose_declares_core_services_and_healthchecks():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for service in ("postgres:", "redis:", "rabbitmq:", "api:", "payment-service:", "market:"):
        assert service in compose
    assert "/api/health" in compose
    assert "/actuator/health" in compose
    assert "REDIS_URL" in compose


def test_flyway_migration_contains_shared_payment_tables():
    migration = Path(
        "java_payment_service/src/main/resources/db/migration/V1__modstore_core_schema.sql"
    ).read_text(encoding="utf-8")
    for table in ("users", "orders", "refund_requests", "plan_templates", "entitlements"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
