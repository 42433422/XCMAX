"""Read official GrowthBook experiment results and existing customer-value evidence."""

from __future__ import annotations

import math
import os
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from modstore_server.customer_value_classification import parse_datetime


def growthbook_client():
    """Only the operator-configured HTTPS origin receives the service credential."""
    base = os.getenv("MODSTORE_RETORT_GROWTHBOOK_URL", "").rstrip("/")
    token = os.getenv("MODSTORE_RETORT_GROWTHBOOK_API_KEY", "")
    origin = urlsplit(base)
    if (
        not token
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
        or origin.scheme != "https"
    ):
        raise ValueError("growthbook_not_configured")
    return httpx.Client(
        base_url=f"{base}/api/v1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
        follow_redirects=False,
        trust_env=False,
    )


def experiment_measurement(spec, request_id, delivery, *, state=None, reject=False):
    if not spec or not spec.get("project") or not _valid_policy(spec):
        return {"status": "not_configured"}
    if spec.get("lifecycle"):
        from modstore_server.retort_feedback_experiments import advance_experiment

        return advance_experiment(request_id, delivery, state=state, reject=reject)
    try:
        with growthbook_client() as client:
            response = client.get(
                "experiments",
                params={
                    "trackingKey": f"xcagi-retort-{request_id}",
                    "projectId": spec["project"],
                    "limit": 2,
                },
            )
            response.raise_for_status()
            listing = response.json()
            if len(listing["experiments"]) != 1 or listing.get("hasMore"):
                return {"status": "unbound"}
            experiment_id = str(listing["experiments"][0]["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", experiment_id):
                return {"status": "unbound"}
            response = client.get(f"experiments/{experiment_id}/results")
            response.raise_for_status()
            return _snapshot(response.json(), {**spec, "id": experiment_id}, request_id, delivery)
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError, IndexError):
        return {"status": "source_unavailable"}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _valid_policy(spec):
    """These are product risk limits; GrowthBook owns statistical estimation."""
    guards = spec.get("guardrails", [])
    return (
        type(spec.get("minimum_users")) is int
        and spec["minimum_users"] >= 2
        and isinstance(guards, list)
        and len(guards) <= 20
        and all(
            isinstance(rule, dict)
            and isinstance(rule.get("metric"), str)
            and bool(rule["metric"])
            and rule.get("direction", "increase") in {"increase", "decrease"}
            and all(
                _number(rule.get(key, 0)) and rule.get(key, 0) >= 0
                for key in ("minimum_lift", "maximum_regression")
            )
            for rule in [spec, *guards]
        )
        and len({rule["metric"] for rule in [spec, *guards]}) == len(guards) + 1
    )


def _metric_effect(sample, rule, *, guardrail=False, engine=None, variation_ids=None):
    rows = [row for row in sample["metrics"] if row["metricId"] == rule["metric"]]
    if len(rows) != 1 or len(rows[0]["variations"]) != 2:
        raise ValueError("ambiguous experiment metric")
    metric = rows[0]
    if variation_ids and [row.get("variationId") for row in metric["variations"]] != variation_ids:
        raise ValueError("experiment_variation_order_changed")
    control, treatment = metric["variations"]
    analyses = [
        row for row in treatment.get("analyses", []) if not engine or row.get("engine") == engine
    ]
    if (
        any(type(row.get("users")) is not int or row["users"] <= 0 for row in (control, treatment))
        or len(analyses) != 1
    ):
        raise ValueError("unverified experiment arms or analysis")
    values = analyses[0]
    if (
        values.get("errorMessage")
        or any(not _number(values.get(key)) for key in ("percentChange", "ciLow", "ciHigh"))
        or not values["ciLow"] <= values["percentChange"] <= values["ciHigh"]
    ):
        raise ValueError("invalid experiment interval")
    low, high = values["ciLow"], values["ciHigh"]
    direction = rule.get("direction", "increase")
    if direction == "decrease":
        low, high = -high, -low
    tolerated = rule.get("maximum_regression", 0)
    decision = (
        "rollback"
        if high < -tolerated
        else (
            "promote"
            if (low >= -tolerated if guardrail else low > rule.get("minimum_lift", 0))
            else "hold"
        )
    )
    return {
        "metric_id": metric["metricId"],
        "metric_name": metric.get("metricName") or metric["metricId"],
        "lift": values["percentChange"],
        "interval": [values["ciLow"], values["ciHigh"]],
        "direction": direction,
        "decision": decision,
    }


def _snapshot(payload, spec, request_id, delivery):
    experiment, result = payload["experiment"], payload["result"]
    launch, measured = parse_datetime(result["dateStart"]), parse_datetime(result["dateUpdated"])
    deployed = parse_datetime(delivery.get("deployment_completed_at"))
    release_sha = delivery.get("release_sha")
    if (
        not _valid_policy(spec)
        or not isinstance(release_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40}", release_sha)
        or experiment["id"] != spec["id"]
        or result["experimentId"] != spec["id"]
        or experiment["type"] != "standard"
        or experiment["project"] != spec["project"]
        or experiment["trackingKey"] != f"xcagi-retort-{request_id}"
        or f"xcagi-release-{release_sha}" not in experiment["tags"]
        or not (
            deployed and launch and measured and deployed <= launch <= measured <= datetime.now(UTC)
        )
        or result["dimension"]["type"] != "none"
        or len(result["results"]) != 1
    ):
        return {"status": "unbound"}
    sample = result["results"][0]
    srm = sample["checks"]["srm"]
    if (
        not _number(srm)
        or not 0.001 <= srm <= 1
        or type(sample["totalUsers"]) is not int
        or sample["totalUsers"] < spec["minimum_users"]
    ):
        return {"status": "sample_unverified"}
    try:
        variation_ids = [row["variationId"] for row in experiment.get("variations", [])]
        primary = _metric_effect(
            sample, spec, engine=spec.get("stats_engine"), variation_ids=variation_ids
        )
        guards = [
            _metric_effect(
                sample,
                rule,
                guardrail=True,
                engine=spec.get("stats_engine"),
                variation_ids=variation_ids,
            )
            for rule in spec.get("guardrails", [])
        ]
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"status": "sample_unverified"}
    decisions = [row["decision"] for row in [primary, *guards]]
    decision = (
        "rollback"
        if "rollback" in decisions
        else "promote" if set(decisions) == {"promote"} else "hold"
    )
    return {
        **primary,
        "status": "measured" if experiment["status"] == "stopped" else "running",
        "source": "growthbook",
        "experiment_id": experiment["id"],
        "snapshot_id": result["id"],
        "observed_at": measured.isoformat(),
        "sample_size": sample["totalUsers"],
        "guardrails": guards,
        "evaluated_decision": decision,
        "decision": decision if experiment["status"] == "stopped" else "hold",
    }


def commercial_measurement(owner_id, delivery):
    """Reuse authoritative payment qualification; scope ledger receipts to the released artifact."""
    from modstore_server.customer_value_evidence import build_customer_value_evidence

    identity = delivery.get("identity") or {}
    artifact = identity.get("artifact_sha256", "")
    deployed = parse_datetime(delivery.get("deployment_completed_at"))
    if not isinstance(artifact, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact) or not deployed:
        return {"status": "release_artifact_unavailable"}
    ledger = build_customer_value_evidence(
        window_days=365,
        delivery_scope=(int(owner_id), artifact, deployed),
    )
    if not ledger["value_ledger_ready"]:
        return {"status": "source_unavailable"}
    return {
        "status": "verified" if ledger["paid_acceptance_count"] else "awaiting_paid_outcome",
        "matching_paid_orders": ledger["paid_acceptance_count"],
        "matched_paid_amount_cents": ledger["verified_paid_amount_cents"],
    }
