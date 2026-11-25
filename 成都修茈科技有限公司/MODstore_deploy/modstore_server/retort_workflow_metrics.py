"""Exact GrowthBook 5.2 SQL sources for real workflow execution outcomes.

Generation validation is a different population. These queries consume only
durable execution observations; the composite ID prevents another experiment's
results from becoming this experiment's conversions for the same account.
"""

from __future__ import annotations

import re

from modstore_server.retort_experiment_surfaces import (
    RAG_MEASUREMENT,
    WORKFLOW_CUSTOMER_MEASUREMENT,
    WORKFLOW_EXECUTION_MEASUREMENT,
)


def execution_policy(spec):
    life = spec.get("lifecycle") or {}
    customer = life.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
    rag = life.get("measurement_scope") == RAG_MEASUREMENT
    if life.get("measurement_scope") not in {
        WORKFLOW_EXECUTION_MEASUREMENT,
        WORKFLOW_CUSTOMER_MEASUREMENT,
        RAG_MEASUREMENT,
    }:
        return None
    source = (
        life.get(
            "rag_outcomes" if rag else "customer_outcomes" if customer else "execution_outcomes"
        )
        or {}
    )
    guards = spec.get("guardrails", [])
    if (
        source.get("source")
        != (
            "modstore_rag_observations_postgres_v1"
            if rag
            else (
                "modstore_customer_workflow_postgres_v1"
                if customer
                else "modstore_event_outbox_postgres_v1"
            )
        )
        or source.get("success_metric_id") != spec.get("metric")
        or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(source.get(key, "")))
            for key in ("success_metric_id", "failure_metric_id")
        )
        or spec.get("direction", "increase") != "increase"
        or len(guards) != 1
        or guards[0].get("metric") != source["failure_metric_id"]
        or guards[0].get("direction") != "decrease"
        or type(source.get("maximum_treatment_failures")) is not int
        or not 1 <= source["maximum_treatment_failures"] <= 1000
    ):
        raise ValueError("workflow_execution_metric_scope_required")
    if customer and (
        not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", str(source.get("employee_id", "")))
        or type(source.get("observation_hours")) is not int
        or not 1 <= source["observation_hours"] <= 168
        or life.get("maturation_hours", 0) < source["observation_hours"]
        or life.get("execution_outcomes")
    ):
        raise ValueError("workflow_customer_outcome_contract_required")
    return source


def execution_queries(scope=WORKFLOW_EXECUTION_MEASUREMENT):
    common = "(p->>'subject_id') || ':' || (p->>'request_id') AS user_id, "
    surface = "rag_context_prompt" if scope == RAG_MEASUREMENT else "workflow_nl_prompt"
    where = f"WHERE p->>'surface' = '{surface}' AND p->>'measurement_scope' = '{scope}'"
    assignment = (
        "SELECT "
        + common
        + "p->>'tracking_key' AS experiment_id, p->>'variation_id' AS variation_id, "
        "(p->>'assigned_at')::timestamptz AS timestamp "
        "FROM (SELECT payload_json::jsonb AS p FROM event_outbox "
        "WHERE event_name = 'experiment.exposed') AS events " + where
    )
    outcomes = (
        "SELECT " + common + "(p->>'completed_at')::timestamptz AS timestamp, 1 AS value "
        "FROM (SELECT payload_json::jsonb AS p FROM event_outbox "
        "WHERE event_name = 'experiment.observed') AS events "
        + where
        + (
            " AND p->>'rag_evidence_sha256' IS NOT NULL AND p->>'observation_id' IS NOT NULL"
            if scope == RAG_MEASUREMENT
            else " AND p->>'execution_id' IS NOT NULL"
        )
        + " AND (p->>'success')::boolean IS "
    )
    if scope in {WORKFLOW_CUSTOMER_MEASUREMENT, RAG_MEASUREMENT}:
        outcomes += " "
        queries = {}
        for key, value in (("success", "TRUE"), ("failure", "FALSE")):
            queries[key] = (
                "SELECT user_id, MIN(timestamp) AS timestamp, 1 AS value FROM ("
                + outcomes
                + value
                + (
                    " AND p->>'customer_outcome_evidence_sha256' IS NOT NULL"
                    if scope == WORKFLOW_CUSTOMER_MEASUREMENT
                    else ""
                )
                + ") AS measured GROUP BY user_id"
            )
        return {"assignment": assignment, **queries}
    return {"assignment": assignment, "success": outcomes + "TRUE", "failure": outcomes + "FALSE"}


def verify_execution_source(client, spec):
    """Read the official API definitions before starting, refreshing or evaluating traffic."""
    source = execution_policy(spec)
    if source is None:
        return
    life = spec["lifecycle"]
    per_account = life.get("measurement_scope") in {WORKFLOW_CUSTOMER_MEASUREMENT, RAG_MEASUREMENT}
    queries = execution_queries(life["measurement_scope"])
    response = client.get(f"data-sources/{life['datasource_id']}")
    response.raise_for_status()
    datasource = response.json()["dataSource"]
    assignments = [
        item
        for item in datasource["assignmentQueries"]
        if item["id"] == life["assignment_query_id"]
    ]
    if (
        datasource["id"] != life["datasource_id"]
        or datasource["type"] != "postgres"
        or len(assignments) != 1
        or assignments[0]["identifierTypes"] != ["user_id"]
        or assignments[0].get("columnMapping")
        or assignments[0]["includesNameColumns"]
        or assignments[0]["dimensionColumns"]
        or assignments[0]["sql"].split() != queries["assignment"].split()
    ):
        raise ValueError("workflow_execution_assignment_source_changed")
    for outcome, direction in (("success", "increase"), ("failure", "decrease")):
        metric_id = source[f"{outcome}_metric_id"]
        response = client.get(f"metrics/{metric_id}")
        response.raise_for_status()
        metric = response.json()["metric"]
        sql = metric.get("sql") or {}
        if (
            metric["id"] != metric_id
            or metric["datasourceId"] != life["datasource_id"]
            or metric["type"] != "binomial"
            or metric["archived"]
            or metric["projects"] != [spec["project"]]
            or metric.get("sqlBuilder")
            or metric.get("mixpanel")
            or metric["behavior"]["goal"] != direction
            or metric["behavior"]["windowSettings"]["type"] != "none"
            or sql.get("identifierTypes") != ["user_id"]
            or sql.get("denominatorMetricId")
            or sql.get("userAggregationSQL", "").upper()
            != ("MAX(VALUE)" if per_account else "SUM(VALUE)")
            or sql.get("conversionSQL", "").split() != queries[outcome].split()
        ):
            raise ValueError("workflow_execution_metric_source_changed")


def execution_stop_loss(db, row, spec):
    source = execution_policy(spec)
    if source is None:
        return False
    from modstore_server.customer_service_tools import json_loads
    from modstore_server.models import OutboxEvent

    failures = 0
    failed_accounts = set()
    for event in db.query(OutboxEvent).filter_by(
        aggregate_id=row.id, event_name="experiment.observed"
    ):
        value = json_loads(event.payload_json, {})
        if (
            value.get("measurement_scope") == spec["lifecycle"]["measurement_scope"]
            and value.get("variation_id") == "1"
            and (
                value.get("rag_evidence_sha256")
                if spec["lifecycle"]["measurement_scope"] == RAG_MEASUREMENT
                else value.get("execution_id")
            )
            and value.get("success") is False
        ):
            if spec["lifecycle"]["measurement_scope"] in {
                WORKFLOW_CUSTOMER_MEASUREMENT,
                RAG_MEASUREMENT,
            }:
                if value.get("subject_id"):
                    failed_accounts.add(str(value["subject_id"]))
            else:
                failures += 1
    failures += len(failed_accounts)
    return failures >= source["maximum_treatment_failures"]


def postpromotion_stop_reason(db, row, spec):
    """Apply the frozen customer stop-loss to separate real rollout receipts.

    Postpromotion samples cannot revise the original GrowthBook A/B result.
    Unknown/corrupt receipts block treatment, never manufacture a new lift.
    """
    from datetime import UTC, datetime

    from modstore_server.customer_service_tools import json_loads
    from modstore_server.retort_training_candidates import postpromotion_effect_snapshot

    if (spec.get("lifecycle") or {}).get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT:
        return ""
    original = execution_policy(spec)
    if original is None:
        return ""
    effects = json_loads(row.effects_json, {})
    evidence = postpromotion_effect_snapshot(db, row, spec, effects, observed_at=datetime.now(UTC))
    if evidence is None:
        # No snapshot is normal before promotion, but an already promoted
        # candidate must not continue with a missing/invalid rollout clock.
        progress = effects.get("experiment") or {}
        if (
            progress.get("traffic") == "candidate"
            and progress.get("decision") == "promote"
            and progress.get("rollout_verified") is True
        ):
            return "workflow_postpromotion_source_unverified"
        return ""
    if evidence["status"] in {"source_unverified", "blocked_source_budget"}:
        return "workflow_postpromotion_source_unverified"
    if evidence["failed_subjects"] >= original["maximum_treatment_failures"]:
        return "workflow_execution_stop_loss"
    return ""
