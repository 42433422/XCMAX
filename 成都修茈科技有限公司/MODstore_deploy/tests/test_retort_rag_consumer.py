"""Real employee RAG input, SQL receipts and the original experiment lifecycle."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from modstore_server import rag_prompt_feedback as feedback
from modstore_server import rag_service
from modstore_server import retort_experiment_runtime as runtime
from modstore_server import retort_feedback_experiments as lifecycle
from modstore_server.customer_service_tools import json_loads
from modstore_server.models import (
    KnowledgeCollection,
    KnowledgeMembership,
    OutboxEvent,
    RetortEvolutionRun,
    User,
    get_session_factory,
)
from tests import test_retort_experiment_lifecycle as lifecycle_tests
from tests.test_retort_experiment_lifecycle import Clock, reapprove, start
from tests.test_retort_workflow_execution import ExecutionAPI

experiment_run = lifecycle_tests.experiment_run
SURFACE = "rag_context_prompt"
RESOURCE = "employee_rag_context"
MEASUREMENT = "rag_citation_integrity"


def rag_spec(spec, control):
    spec = deepcopy(spec)
    life = spec["lifecycle"]
    life.pop("employee_id", None)
    life.update(
        surface=SURFACE,
        resource_id=RESOURCE,
        measurement_scope=MEASUREMENT,
        control_prompt=control,
        treatment_prompt=control + "\n核对每个引用编号是否存在。",
        rag_outcomes={
            "source": "modstore_rag_observations_postgres_v1",
            "success_metric_id": "success",
            "failure_metric_id": "failure",
            "maximum_treatment_failures": 2,
        },
    )
    spec["guardrails"] = [{"metric": "failure", "direction": "decrease"}]
    return spec


@pytest.fixture
def rag_call(client, tmp_path, monkeypatch):
    with get_session_factory()() as db:
        user = User(username=uuid4().hex, password_hash="unused", is_admin=True)
        db.add(user)
        db.flush()
        collection = KnowledgeCollection(owner_kind="user", owner_id=str(user.id), name="Private")
        db.add(collection)
        db.commit()
        uid, cid = user.id, collection.id
    template = {
        "training_candidate": {
            "surface": SURFACE,
            "resource_id": RESOURCE,
            "owner_id": uid,
            "growthbook": {"lifecycle": {"surface": SURFACE, "cohort_user_ids": [uid]}},
        }
    }
    path = tmp_path / "protocols.json"
    path.write_text(json.dumps({"rag": template}))
    monkeypatch.setenv("MODSTORE_RETORT_PROTOCOLS", str(path))
    monkeypatch.delenv("MODSTORE_RETORT_GROWTHBOOK_URL", raising=False)
    monkeypatch.setenv("MODSTORE_RAG_RETRIEVAL_MODE", "vector")
    monkeypatch.delenv("MODSTORE_RAG_RERANK", raising=False)

    async def embed(*_args, **_kwargs):
        return [[1.0, 0.0]]

    def query(name, **_kwargs):
        assert name == rag_service.vector_engine.kb_collection_name(cid)
        return [
            {
                "id": "c1",
                "document": "真实私有资料：原客户的订单数为 3。",
                "distance": 0.1,
                "metadata": {"doc_id": "d1", "chunk_id": "c1", "filename": "private.txt"},
            }
        ]

    monkeypatch.setattr(rag_service, "embed_texts", embed)
    monkeypatch.setattr(rag_service.vector_engine, "query", query)
    run = {
        "user": uid,
        "collection": cid,
        "calls": [],
        "output": "无来源回答",
        "template_path": path,
    }

    async def model(provider, model, messages, **_kwargs):
        run["calls"].append(deepcopy(messages))
        if run.get("during_call"):
            run["during_call"]()
        return {"ok": True, "content": run["output"]}

    monkeypatch.setattr("modstore_server.services.llm.chat_dispatch_via_platform_only", model)

    async def call(user_id=None):
        from modstore_server.employee_executor import _cognition_real

        with get_session_factory()() as db:
            return await _cognition_real(
                {
                    "cognition": {
                        "agent": {"system_prompt": "原员工规则"},
                        "knowledge": {"enabled": True, "collection_ids": [cid]},
                    }
                },
                {"normalized_input": {"question": "原客户订单数是多少？"}},
                {},
                db,
                user_id or uid,
                employee_id="rag-helper",
                task="原客户订单数是多少？",
                bench_llm_override=("platform", "approved-model"),
            )

    run["call"] = call
    return run


def _receipts(event_name, *, aggregate_id=None):
    with get_session_factory()() as db:
        query = db.query(OutboxEvent).filter_by(event_name=event_name)
        if aggregate_id:
            query = query.filter_by(aggregate_id=aggregate_id)
        return [json_loads(row.payload_json, {}) for row in query.all()]


@pytest.fixture
def rag_experiment(experiment_run, rag_call, monkeypatch):
    from modstore_server.retort_workflow_metrics import execution_queries

    run = experiment_run
    run["spec"] = rag_spec(run["spec"], rag_service.RAG_SYSTEM_PROMPT)
    run["spec"]["lifecycle"]["cohort_user_ids"].append(rag_call["user"])
    run["spec"] = lifecycle.freeze_experiment_policy(run["spec"])
    reapprove(run)
    api = ExecutionAPI()
    queries = execution_queries(MEASUREMENT)
    api.datasource["assignmentQueries"][0]["sql"] = queries["assignment"]
    for key in ("success", "failure"):
        api.metrics[key]["sql"]["conversionSQL"] = queries[key]
        api.metrics[key]["sql"]["userAggregationSQL"] = "MAX(VALUE)"
    run["api"] = api
    monkeypatch.setattr(lifecycle, "growthbook_client", api.client)
    monkeypatch.setenv("MODSTORE_RETORT_GROWTHBOOK_URL", "https://growthbook.test")
    with get_session_factory()() as db:
        for uid in run["users"]:
            db.add(
                KnowledgeMembership(
                    collection_id=rag_call["collection"],
                    grantee_kind="user",
                    grantee_id=str(uid),
                    permission="read",
                )
            )
        db.commit()
    run["rag"] = rag_call
    return run


def test_rag_contract_uses_its_own_independent_metric(experiment_run):
    spec = rag_spec(experiment_run["spec"], "资料引用规则")
    assert lifecycle.freeze_experiment_policy(spec)["lifecycle"]["surface"] == SURFACE


def test_unconfigured_rag_training_does_not_open_database(monkeypatch):
    monkeypatch.delenv("MODSTORE_RETORT_PROTOCOLS", raising=False)

    def unexpected_database():
        raise AssertionError("an unconfigured offline miner must not require SQL")

    monkeypatch.setattr(feedback, "get_session_factory", unexpected_database)
    assert feedback.failure_records() == []


@pytest.mark.asyncio
async def test_real_rag_failure_is_preserved_for_training_without_claiming_business_success(
    rag_call,
):
    run = rag_call
    result = await run["call"]()
    assert result["reasoning"] == "无来源回答"
    assert "真实私有资料" in run["calls"][0][0]["content"]
    with get_session_factory()() as db:
        receipts = db.query(OutboxEvent).filter_by(event_name="rag.cognition.completed").all()
        assert len(receipts) == 1
        evidence = json_loads(receipts[0].payload_json, {})
        assert evidence["measurement_scope"] == MEASUREMENT
        assert evidence["success"] is False
        assert evidence["business_verified"] is False
        assert evidence["reason"] == "rag_citations_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer,passed,reason",
    [
        ("订单数为 3。[1]", True, MEASUREMENT),
        ("订单数为 3。[99]", False, "rag_citation_out_of_range"),
        ("订单数为 3。[1][0]", False, "rag_citation_out_of_range"),
        ("", False, "rag_answer_empty"),
    ],
)
async def test_actual_rag_observation_uses_independent_citations(
    rag_experiment, answer, passed, reason
):
    run = rag_experiment
    start(run)
    run["rag"]["output"] = answer
    result = await run["rag"]["call"]()
    observed = _receipts("experiment.observed", aggregate_id=run["id"])
    assert len(observed) == 1
    assert observed[0]["success"] is passed
    assert observed[0]["measurement_scope"] == MEASUREMENT
    assert observed[0]["rag_evidence_sha256"]
    assert result["knowledge"]["verification"]["reason"] == reason
    assert result["knowledge"]["verification"]["business_verified"] is False


@pytest.mark.asyncio
async def test_source_grant_revoked_during_call_is_not_returned_or_counted(rag_experiment):
    run = rag_experiment
    start(run)
    subject = run["users"][1]
    run["rag"]["output"] = "订单数为 3。[1]"

    def revoke():
        with get_session_factory()() as db:
            db.query(KnowledgeMembership).filter_by(
                collection_id=run["rag"]["collection"], grantee_id=str(subject)
            ).delete()
            db.commit()

    run["rag"]["during_call"] = revoke
    result = await run["rag"]["call"](subject)
    assert result["error"] == "rag_source_authorization_changed"
    assert result["knowledge"]["items"] == []
    assert _receipts("experiment.observed", aggregate_id=run["id"]) == []


@pytest.mark.asyncio
async def test_withdrawal_during_model_call_archives_without_changing_metrics(rag_experiment):
    run = rag_experiment
    start(run)

    def withdraw():
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, run["id"])
            effects = json_loads(row.effects_json, {})
            effects["experiment"]["traffic"] = "control"
            row.effects_json = json.dumps(effects)
            db.commit()

    run["rag"]["during_call"] = withdraw
    run["rag"]["output"] = "答案[1]"
    result = await run["rag"]["call"]()
    assert result["knowledge"]["verification"]["metric_admitted"] is False
    assert _receipts("experiment.observed", aggregate_id=run["id"]) == []
    assert _receipts(feedback.COMPLETED)[-1]["business_verified"] is False


@pytest.mark.asyncio
async def test_failed_tracking_prevents_actual_model_call(rag_experiment, monkeypatch):
    run = rag_experiment
    start(run)
    original = __import__("modstore_server.eventing.db_outbox", fromlist=["enqueue"])
    enqueue = original.enqueue

    def reject(db, event_name, *args, **kwargs):
        if event_name == feedback.START:
            raise OSError("private SQL unavailable")
        return enqueue(db, event_name, *args, **kwargs)

    monkeypatch.setattr(original, "enqueue", reject)
    with pytest.raises(OSError):
        await run["rag"]["call"]()
    assert run["rag"]["calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["source_sql", "cohort", "authority", "withdraw"])
async def test_no_unauthorized_rag_treatment(rag_experiment, fault):
    run = rag_experiment
    start(run)
    if fault == "source_sql":
        run["api"].metrics["success"]["sql"]["conversionSQL"] = "SELECT 1"
        assert run["advance"]()["status"] == "experiment_blocked"
    elif fault == "cohort":
        run["spec"]["lifecycle"]["cohort_user_ids"].remove(run["rag"]["user"])
        reapprove(run)
    else:
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, run["id"])
            if fault == "authority":
                db.get(User, row.user_id).is_admin = False
            else:
                row.status = "waiting_recovery"
            db.commit()
    await run["rag"]["call"]()
    prompt = run["rag"]["calls"][0][0]["content"]
    assert run["spec"]["lifecycle"]["treatment_prompt"] not in prompt
    assert _receipts("experiment.observed", aggregate_id=run["id"]) == []


@pytest.mark.asyncio
async def test_raw_reproduction_stays_private_and_mining_requires_current_grants(rag_call):
    from modstore_server.eventing.db_outbox import _row_to_record

    await rag_call["call"]()
    records = feedback.failure_records()
    assert len(records) == 1 and records[0]["generation_context"]["sources"]
    with get_session_factory()() as db:
        row = (
            db.query(OutboxEvent)
            .filter_by(
                event_id=f"{feedback.START}:{records[0]['run_id'].removeprefix('rag-cognition:')}"
            )
            .one()
        )
        record = _row_to_record(row)
        public = json.dumps(
            [record.to_envelope(), record.to_domain_event().payload], ensure_ascii=False
        )
        assert "真实私有资料" not in public and "原客户订单数" not in public
        db.get(KnowledgeCollection, rag_call["collection"]).owner_id = "999999"
        db.commit()
    assert feedback.failure_records() == []


@pytest.mark.asyncio
async def test_promoted_rag_prompt_and_withdrawal_reuse_original_lifecycle(rag_experiment):
    run = rag_experiment
    start(run)
    Clock.value += timedelta(hours=2)
    assert run["advance"]()["status"] == "awaiting_experiment_stop"
    assert run["advance"]()["rollout_verified"] is True
    await run["rag"]["call"]()
    assert run["spec"]["lifecycle"]["treatment_prompt"] in run["rag"]["calls"][-1][0]["content"]
    assert _receipts("experiment.observed", aggregate_id=run["id"]) == []
    assert run["advance"](reject=True)["status"] in {"awaiting_rollout_readback", "measured"}
    assert run["advance"](reject=True)["decision"] == "rollback"
    await run["rag"]["call"]()
    assert run["spec"]["lifecycle"]["treatment_prompt"] not in run["rag"]["calls"][-1][0]["content"]


@pytest.mark.asyncio
async def test_rollout_without_training_policy_still_rechecks_source_grants(rag_experiment):
    run = rag_experiment
    start(run)
    Clock.value += timedelta(hours=2)
    run["advance"]()
    assert run["advance"]()["rollout_verified"] is True
    run["rag"]["template_path"].write_text("{}")
    subject = run["users"][1]

    def revoke():
        with get_session_factory()() as db:
            db.query(KnowledgeMembership).filter_by(
                collection_id=run["rag"]["collection"], grantee_id=str(subject)
            ).delete()
            db.commit()

    run["rag"]["during_call"] = revoke
    run["rag"]["output"] = "订单数为 3。[1]"
    result = await run["rag"]["call"](subject)
    assert result["error"] == "rag_source_authorization_changed"
    assert _receipts("experiment.observed", aggregate_id=run["id"]) == []
    assert _receipts("experiment.exposed", aggregate_id=run["id"]) == []
    assert _receipts(feedback.COMPLETED)[-1]["metric_admitted"] is False


@pytest.mark.asyncio
async def test_rag_stop_loss_counts_accounts_not_repeated_answers(rag_experiment):
    from modstore_server.retort_workflow_metrics import execution_queries, execution_stop_loss

    run = rag_experiment
    start(run)
    subjects = []
    for subject in run["users"]:
        _, assignment = runtime.select_variant(
            surface=SURFACE,
            resource_id=RESOURCE,
            subject_id=subject,
            default_value=rag_service.RAG_SYSTEM_PROMPT,
        )
        if assignment and assignment["variation_id"] == "1":
            subjects.append(subject)
    assert len(subjects) >= 2
    for _ in range(3):
        await run["rag"]["call"](subjects[0])
    with get_session_factory()() as db:
        assert not execution_stop_loss(db, db.get(RetortEvolutionRun, run["id"]), run["spec"])
    await run["rag"]["call"](subjects[1])
    with get_session_factory()() as db:
        assert execution_stop_loss(db, db.get(RetortEvolutionRun, run["id"]), run["spec"])
    queries = execution_queries(MEASUREMENT)
    assert all("GROUP BY user_id" in queries[key] for key in ("success", "failure"))
