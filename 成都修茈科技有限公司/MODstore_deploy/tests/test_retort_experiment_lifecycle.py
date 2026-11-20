"""Official API contract fixtures, real SDK allocation, and real SQLite observation writes."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from retort_engine.evolution_contract import digest

from modstore_server import retort_experiment_runtime as runtime
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import OutboxEvent, RetortEvolutionRun, User, get_session_factory


class Clock:
    value = datetime(2026, 1, 4, tzinfo=UTC)

    @classmethod
    def now(cls, _tz=None):
        return cls.value


class GrowthBookAPI:
    """An external contract double; its statistics are never used as production evidence."""

    def __init__(self):
        self.experiment = None
        self.calls = []
        self.interval = [0.02, 0.1, 0.18]
        self.users = 4
        self.timeout_after_create = False
        self.approval_required = False
        self.transport = httpx.MockTransport(self.handle)

    def client(self):
        return httpx.Client(base_url="https://growthbook.test/api/v1/", transport=self.transport)

    def handle(self, request):
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if request.method == "GET":
            if path.endswith("/results"):
                return httpx.Response(
                    200,
                    json={
                        "experiment": self.experiment,
                        "result": {
                            "id": "snapshot",
                            "experimentId": "exp",
                            "queryIds": ["warehouse-query"],
                            "dateStart": self.experiment["phases"][0]["dateStarted"],
                            "dateEnd": Clock.now().isoformat(),
                            "dateUpdated": Clock.now().isoformat(),
                            "dimension": {"type": "none"},
                            "results": [
                                {
                                    "totalUsers": self.users,
                                    "checks": {"srm": 0.9},
                                    "metrics": [
                                        {
                                            "metricId": "success",
                                            "variations": [
                                                {"variationId": "var0", "users": 2, "analyses": []},
                                                {
                                                    "variationId": "var1",
                                                    "users": 2,
                                                    "analyses": [
                                                        {
                                                            "engine": "frequentist",
                                                            "ciLow": self.interval[0],
                                                            "percentChange": self.interval[1],
                                                            "ciHigh": self.interval[2],
                                                        }
                                                    ],
                                                },
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "experiments": [self.experiment] if self.experiment else [],
                    "hasMore": False,
                },
            )
        body = json_loads(request.content, {})
        if path.endswith("/experiments"):
            self.experiment = {
                **body,
                "id": "exp",
                "archived": False,
                "variations": [
                    {"key": "0", "variationId": "var0"},
                    {"key": "1", "variationId": "var1"},
                ],
                "settings": {
                    "datasourceId": body["datasourceId"],
                    "assignmentQueryId": body["assignmentQueryId"],
                    "statsEngine": body["statsEngine"],
                    "sequentialTestingEnabled": False,
                    "goals": [{"metricId": "success"}],
                    "guardrails": [],
                },
                "phases": [
                    {
                        **body["phases"][0],
                        "trafficSplit": [
                            {"variationId": "var0", "weight": 0.5},
                            {"variationId": "var1", "weight": 0.5},
                        ],
                    }
                ],
            }
            if self.timeout_after_create:
                raise httpx.ReadTimeout("lost create receipt")
        elif path.endswith("/start"):
            if self.approval_required:
                return httpx.Response(202, json={"confirmation": {"id": "confirmation"}})
            self.experiment["status"] = "running"
            self.experiment["phases"][0]["dateStarted"] = Clock.now().isoformat()
        elif path.endswith("/stop") or path.endswith("/modify-temporary-rollout"):
            self.experiment["status"] = "stopped"
            self.experiment["resultSummary"] = {
                "releasedVariationId": body["releasedVariationId"],
                "excludeFromPayload": False,
            }
        return httpx.Response(200, json={"experiment": self.experiment})


@pytest.fixture
def experiment_run(client, monkeypatch):
    Clock.value = datetime(2026, 1, 4, tzinfo=UTC)
    monkeypatch.setattr(lifecycle, "datetime", Clock)
    monkeypatch.setattr(runtime, "datetime", Clock)
    monkeypatch.setenv("MODSTORE_RETORT_GROWTHBOOK_URL", "https://growthbook.test")
    api, request_id = GrowthBookAPI(), str(uuid4())
    monkeypatch.setattr(lifecycle, "growthbook_client", api.client)
    with get_session_factory()() as db:
        users = [
            User(username=uuid4().hex, password_hash="test-only", is_admin=i == 0) for i in range(5)
        ]
        db.add_all(users)
        db.flush()
        cohort = [user.id for user in users[:4]]
        outsider = users[4].id
        spec = lifecycle.freeze_experiment_policy(
            {
                "project": "prod",
                "metric": "success",
                "minimum_users": 4,
                "stats_engine": "frequentist",
                "lifecycle": {
                    "surface": "employee_prompt",
                    "employee_id": "help-desk",
                    "cohort_user_ids": cohort,
                    "control_prompt": "Approved control",
                    "treatment_prompt": "Approved candidate",
                    "datasource_id": "warehouse",
                    "assignment_query_id": "actual-outbox-exposures",
                    "duration_hours": 1,
                    "coverage": 1,
                },
            }
        )
        protocol, plan = {"request_id": request_id}, {"feedback_policy": {"growthbook": spec}}
        effects = {"customer_feedback": {"growthbook": spec}, "plan": plan, "optimization": {}}
        effects["authorization"] = {
            "approved": True,
            "digest": digest({"protocol": protocol, "plan": plan, "optimization": {}}),
        }
        db.add(
            RetortEvolutionRun(
                id=request_id,
                user_id=users[0].id,
                protocol_json=json_dumps(protocol),
                effects_json=json_dumps(effects),
            )
        )
        db.commit()
    identity = {
        "git_sha": "a" * 40,
        "artifact_sha256": "a" * 64,
        "release_id": "xcagi-1.0.0.7-" + "a" * 40,
        "image_digest": "",
    }
    delivery = {
        "status": "deployment_verified",
        "release_sha": "a" * 40,
        "identity": identity,
        "deployment_completed_at": "2026-01-03T00:00:00+00:00",
    }
    verification = {"status": "checks_passed"}
    state = {
        "protocol": protocol,
        "plan": plan,
        "verification": verification,
        "approval": {"approved": True, "digest": digest(verification)},
    }
    monkeypatch.setattr(runtime, "_identity", lambda: identity)

    def advance(**kwargs):
        return lifecycle.advance_experiment(request_id, delivery, state=state, **kwargs)

    def choose(user=cohort[0], default="Approved control"):
        return runtime.select_variant(
            surface="employee_prompt",
            resource_id="help-desk",
            subject_id=user,
            default_value=default,
        )

    return {
        "id": request_id,
        "api": api,
        "spec": spec,
        "state": state,
        "delivery": delivery,
        "advance": advance,
        "choose": choose,
        "users": cohort,
        "outsider": outsider,
    }


def start(run):
    assert run["advance"]()["status"] == "awaiting_experiment_readback"
    assert run["advance"]()["status"] == "awaiting_experiment_start"
    assert run["advance"]()["status"] == "running"


def test_real_sdk_cohort_allocation_and_only_actual_observations(experiment_run):
    run = experiment_run
    assert run["choose"](default="Approved candidate") == ("Approved control", None)
    start(run)
    value, assignment = run["choose"]()
    assert value in {"Approved control", "Approved candidate"}
    assert run["choose"]()[0] == value
    assert assignment["subject_id"] == str(run["users"][0])
    assert run["choose"](run["outsider"]) == ("Approved control", None)
    assert run["choose"](run["outsider"], default="Approved candidate") == (
        "Approved control",
        None,
    )
    assert run["choose"](0) == ("Approved control", None)
    assert run["choose"](default="Unrelated prompt") == ("Unrelated prompt", None)
    with get_session_factory()() as db:
        assert db.query(OutboxEvent).filter_by(aggregate_id=run["id"]).count() == 0
    runtime.record_observation(assignment, result={"ok": False}, duration_ms=12.5)
    runtime.record_observation(assignment, result={"ok": False}, duration_ms=12.5)
    with get_session_factory()() as db:
        rows = db.query(OutboxEvent).filter_by(aggregate_id=run["id"]).all()
        assert {row.event_name for row in rows} == {"experiment.exposed", "experiment.observed"}
        assert len(rows) == 2
        observed = json_loads(
            next(row.payload_json for row in rows if row.event_name == "experiment.observed"), {}
        )
        assert observed["success"] is False and observed["duration_ms"] == 12.5
        assert "Approved" not in json_dumps(observed)


@pytest.mark.parametrize(
    "interval,decision",
    [([0.02, 0.1, 0.18], "promote"), ([-0.18, -0.1, -0.02], "rollback"), ([-0.1, 0, 0.1], "hold")],
)
def test_fixed_window_readback_controls_promotion_and_retraction(
    experiment_run, interval, decision
):
    run = experiment_run
    run["api"].interval = interval
    start(run)
    Clock.value += timedelta(hours=2)
    assert run["choose"]() == ("Approved control", None)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["choose"]() == ("Approved control", None)
    result = run["advance"]()
    assert result["decision"] == decision and result["rollout_verified"] is True
    assert run["choose"]()[0] == (
        "Approved candidate" if decision == "promote" else "Approved control"
    )
    # A customer rejection withdraws a previously promoted prompt before the network readback.
    assert run["advance"](reject=True)["status"] in {"awaiting_rollout_readback", "measured"}
    assert run["choose"]() == ("Approved control", None)
    assert run["advance"](reject=True)["decision"] == "rollback"


def test_insufficient_sample_stops_without_promotion(experiment_run):
    run = experiment_run
    run["api"].users = 2
    start(run)
    Clock.value += timedelta(hours=2)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    result = run["advance"]()
    assert result["status"] == "inconclusive" and result["decision"] == "hold"
    assert run["choose"]() == ("Approved control", None)


@pytest.mark.parametrize(
    "fault", ["none", "missing_config", "broken_approval", "tracking_unavailable"]
)
def test_employee_cognition_records_real_attempt_and_next_training_reads_failure(
    experiment_run, monkeypatch, fault
):
    import asyncio

    from modstore_server import capability_trainer
    from modstore_server.employee_executor import _cognition_real

    run = experiment_run
    start(run)
    prompts = []
    if fault == "missing_config":
        monkeypatch.delenv("MODSTORE_RETORT_GROWTHBOOK_URL")
    elif fault == "broken_approval":
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, run["id"])
            effects = json_loads(row.effects_json, {})
            effects["authorization"]["digest"] = "0" * 64
            row.effects_json = json_dumps(effects)
            db.commit()
    elif fault == "tracking_unavailable":

        def fail_tracking(_assignment):
            raise OSError("tracking unavailable")

        monkeypatch.setattr(runtime, "begin_observation", fail_tracking)

    async def model(_provider, _model, messages, **_kwargs):
        prompts.append(messages[0]["content"])
        return {"ok": False, "error": "required structured output absent"}

    monkeypatch.setattr("modstore_server.services.llm.chat_dispatch_via_platform_only", model)
    monkeypatch.setattr(
        "modstore_server.prompt_evolution_ab.get_effective_system_prompt",
        lambda _employee, prompt: prompt,
    )
    attempt = _cognition_real(
        {"cognition": {"agent": {"system_prompt": "Approved candidate"}}},
        {"normalized_input": {}},
        {},
        None,
        run["users"][0],
        employee_id="help-desk",
        bench_llm_override=("platform", "approved-model"),
    )
    if fault in {"broken_approval", "tracking_unavailable"}:
        with pytest.raises((ValueError, OSError)):
            asyncio.run(attempt)
        assert prompts == []
        return
    result = asyncio.run(attempt)
    assert result["error"] == "required structured output absent"
    assert prompts == [run["choose"]()[0]]
    if fault == "missing_config":
        assert prompts == ["Approved control"]
        return
    records = capability_trainer.outbox_failures()
    assert len(records) == 1 and records[0]["employee_id"] == "help-desk"
    assert records[0]["error"] == "observed_prompt_execution_failed"
    assert "user_id" not in records[0] and "task" not in records[0]


def test_unknown_create_receipt_is_reconciled_without_duplicate(experiment_run):
    run = experiment_run
    run["api"].timeout_after_create = True
    assert run["advance"]()["status"] == "experiment_blocked"
    assert run["advance"]()["status"] == "awaiting_experiment_start"
    assert run["api"].calls.count(("POST", "/api/v1/experiments")) == 1


def test_external_approval_and_expired_control_lease_cannot_be_bypassed(experiment_run):
    run = experiment_run
    run["api"].approval_required = True
    run["advance"]()
    assert run["advance"]()["status"] == "awaiting_experiment_start"
    assert run["advance"]()["status"] == "awaiting_experiment_start"
    assert run["api"].calls.count(("POST", "/api/v1/experiments/exp/start")) == 1
    assert run["choose"]()[1] is None
    run["api"].experiment["status"] = "running"  # external approver's observed transition
    assert run["advance"]()["status"] == "running"
    assert run["choose"]()[1] is not None
    Clock.value += timedelta(minutes=16)
    assert run["choose"]() == ("Approved control", None)


def test_changed_policy_and_missing_source_do_not_launch(experiment_run, monkeypatch):
    run = experiment_run
    from modstore_server.retort_feedback_measurements import growthbook_client

    monkeypatch.delenv("MODSTORE_RETORT_GROWTHBOOK_API_KEY", raising=False)
    monkeypatch.setattr(lifecycle, "growthbook_client", growthbook_client)
    result = run["advance"]()
    assert (
        result["status"] == "experiment_blocked" and result["reason"] == "growthbook_not_configured"
    )
    assert not run["api"].calls
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        effects["customer_feedback"]["growthbook"]["minimum_users"] = 2
        row.effects_json = json_dumps(effects)
        db.commit()
    assert run["advance"]()["reason"] == "experiment_approval_mismatch"
    assert not run["api"].calls


def test_missing_configuration_or_broken_approval_never_falls_back_to_deployed_candidate(
    experiment_run, monkeypatch
):
    run = experiment_run
    start(run)
    monkeypatch.delenv("MODSTORE_RETORT_GROWTHBOOK_URL")
    assert run["choose"](default="Approved candidate") == ("Approved control", None)
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, run["id"])
        effects = json_loads(row.effects_json, {})
        effects["authorization"]["digest"] = "0" * 64
        row.effects_json = json_dumps(effects)
        db.commit()
    with pytest.raises(ValueError, match="approval_mismatch"):
        run["choose"](default="Approved candidate")
    assert run["choose"](default="New unrelated release") == ("New unrelated release", None)


@pytest.mark.parametrize(
    "key,value",
    [
        ("coverage", True),
        ("duration_hours", 0),
        ("datasource_id", ""),
        ("cohort_user_ids", [1, 1]),
        ("surface", "unregistered_product"),
    ],
)
def test_invalid_experiment_authorization_is_rejected(experiment_run, key, value):
    spec = deepcopy(experiment_run["spec"])
    spec["lifecycle"][key] = value
    with pytest.raises(ValueError, match="lifecycle"):
        lifecycle.freeze_experiment_policy(spec)
