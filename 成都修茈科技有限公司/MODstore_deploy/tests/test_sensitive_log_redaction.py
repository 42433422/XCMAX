from __future__ import annotations

import asyncio
import logging

from modstore_server import (
    daily_employee_briefs,
    employee_perception_enricher,
    security,
    task_router,
)


def test_task_router_parse_failure_does_not_log_model_output(
    monkeypatch, caplog
) -> None:
    secret = "customer-order-secret"
    monkeypatch.setattr(
        task_router,
        "_load_all_employee_profiles",
        lambda: [{"id": "worker", "name": "Worker"}],
    )
    monkeypatch.setattr(task_router, "_call_llm", lambda *_args, **_kwargs: secret)
    caplog.set_level(logging.WARNING)

    result = task_router.decompose_task("route this task")

    assert result[0].employee_id == "daily-orchestrator"
    assert secret not in caplog.text


def test_daily_brief_failure_does_not_log_or_render_exception(
    monkeypatch, caplog
) -> None:
    secret = "provider-token-secret"

    async def _fail_research(**_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(daily_employee_briefs, "build_research_context", _fail_research)
    monkeypatch.setattr(daily_employee_briefs, "_daily_brief_user_id", lambda: 1)
    caplog.set_level(logging.ERROR)

    rendered = asyncio.run(
        daily_employee_briefs._one_brief_html(
            "employee", "Employee", "provider", "model"
        )
    )

    assert "生成简报失败" in rendered
    assert secret not in rendered
    assert secret not in caplog.text


def test_recent_run_query_failure_does_not_log_exception(monkeypatch, caplog) -> None:
    secret = "database-credential-secret"

    class _Query:
        def filter(self, *_args):
            raise RuntimeError(secret)

    class _Session:
        def query(self, *_args):
            return _Query()

    caplog.set_level(logging.DEBUG)

    assert (
        employee_perception_enricher._recent_runs_from_db(_Session(), "employee") == []
    )
    assert secret not in caplog.text


def test_insecure_defaults_are_rejected_without_printing_secret(
    monkeypatch, capsys
) -> None:
    insecure_values = {
        "MODSTORE_JWT_SECRET": "modstore-dev-secret-change-in-prod",
        "MODSTORE_ADMIN_RECHARGE_TOKEN": "dev-admin-token",
        "MODSTORE_BOOTSTRAP_ADMIN_PASSWORD": "admin123",
        "PAYMENT_SECRET_KEY": "default_secret_key",
    }
    monkeypatch.setenv("MODSTORE_DEPLOY_TIER", "development")
    for name, value in insecure_values.items():
        monkeypatch.setenv(name, value)

    security.ensure_secure_config()

    output = capsys.readouterr().out
    for secret_value in insecure_values.values():
        assert secret_value not in output
