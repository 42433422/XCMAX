import json

from modstore_server.incident_model_router import route_for_incident
from modstore_server.para_delegate_handler import _build_para_prompt, _build_request


def test_role_budgets_and_candidates_come_from_server_policy(monkeypatch):
    monkeypatch.setenv("MODSTORE_INCIDENT_CODEX_SCOUT_MODELS", "fast-model,capable-model")
    scout = route_for_incident(
        event_type="ops.intake.customer_ticket",
        payload={"budget": {"output_tokens": 999999}},
        role="scout",
    )
    fix = route_for_incident(event_type="ops.intake.customer_ticket", payload={}, role="fix")
    assert scout["budget"]["output_tokens"] == 1600
    assert fix["budget"]["output_tokens"] == 4000
    assert scout["budget"]["codex_model_candidates"] == ["fast-model", "capable-model"]


def test_budget_only_override_is_bounded_and_does_not_force_platform_model(monkeypatch):
    monkeypatch.setenv(
        "MODSTORE_INCIDENT_MODEL_ROUTE_JSON",
        json.dumps(
            {
                "role:verify": {
                    "budget": {
                        "context_chars": 1,
                        "output_tokens": 1000000,
                        "reasoning_effort": "invalid",
                    }
                },
            }
        ),
    )
    route = route_for_incident(event_type="x", payload={}, role="verify")
    assert route["budget"]["context_chars"] == 4000
    assert route["budget"]["output_tokens"] == 32768
    assert route["budget"]["reasoning_effort"] == "medium"


def test_para_prompt_contains_actual_executor_candidates_and_requested_budget(
    monkeypatch,
):
    monkeypatch.setenv("MODSTORE_INCIDENT_CODEX_SCOUT_MODELS", "fast-model")
    req = _build_request(
        task="inspect repository",
        employee_id="dynamic-worker",
        input_data={
            "_trusted_incident_team_execution": True,
            "role": "scout",
            "event_type": "example",
            "report_only": True,
            "repo_url": "https://github.com/example/project.git",
        },
    )
    prompt = _build_para_prompt(req)
    assert "codex_model_candidates: fast-model" in prompt
    assert '"reasoning_effort":"low"' in prompt
    assert '"output_tokens":1600' in prompt
    assert "未强制" in prompt
    assert req["execution_budget"]["role"] == "scout"


def test_ordinary_requests_do_not_inherit_incident_budget():
    req = _build_request(task="ordinary task", employee_id="worker", input_data={"role": "fix"})
    assert req["execution_budget"] == {}


def test_platform_cognition_applies_output_token_cap(monkeypatch):
    import asyncio

    from modstore_server.employee_executor import _cognition_real

    captured = {}

    async def dispatch(provider, model, messages, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "content": "scout result", "raw": {}}

    monkeypatch.setattr("modstore_server.services.llm.chat_dispatch_via_platform_only", dispatch)
    result = asyncio.run(
        _cognition_real(
            {"agent": {"model": {"max_tokens": 8000}}},
            {
                "normalized_input": {
                    "_trusted_incident_team_execution": True,
                    "role": "scout",
                }
            },
            {},
            None,
            0,
            task="inspect",
            bench_llm_override=("configured-provider", "configured-model"),
        )
    )
    assert captured["max_tokens"] == 1600
    assert result["provider"] == "configured-provider"
