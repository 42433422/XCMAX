"""Read official GrowthBook experiment results and existing customer-value evidence."""

from __future__ import annotations

import math
import os
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from modstore_server.customer_value_classification import parse_datetime


def experiment_measurement(spec, request_id, delivery):
    if not spec:
        return {"status": "not_configured"}
    minimum = spec.get("minimum_users")
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
        or not spec.get("project")
        or not spec.get("metric")
        or type(minimum) is not int
        or minimum < 2
    ):
        return {"status": "not_configured"}
    try:
        with httpx.Client(
            base_url=f"{base}/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
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


def _snapshot(payload, spec, request_id, delivery):
    experiment, result = payload["experiment"], payload["result"]
    launch, measured = parse_datetime(result["dateStart"]), parse_datetime(result["dateUpdated"])
    deployed = parse_datetime(delivery["verified_at"])
    if (
        experiment["id"] != spec["id"]
        or result["experimentId"] != spec["id"]
        or experiment["type"] != "standard"
        or experiment["project"] != spec["project"]
        or experiment["trackingKey"] != f"xcagi-retort-{request_id}"
        or f"xcagi-release-{delivery['merge_sha']}" not in experiment["tags"]
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
        not isinstance(srm, (float, int))
        or not 0.001 <= srm <= 1
        or sample["totalUsers"] < spec["minimum_users"]
    ):
        return {"status": "sample_unverified"}
    metric = next((row for row in sample["metrics"] if row["metricId"] == spec["metric"]), None)
    if not metric or len(metric["variations"]) != 2:
        return {"status": "sample_unverified"}
    control, treatment = metric["variations"]
    values = treatment["analyses"][0]
    if (
        control.get("users", 0) <= 0
        or treatment.get("users", 0) <= 0
        or values.get("errorMessage")
        or any(not math.isfinite(values[key]) for key in ("percentChange", "ciLow", "ciHigh"))
    ):
        return {"status": "sample_unverified"}
    return {
        "status": "measured" if experiment["status"] == "stopped" else "running",
        "source": "growthbook",
        "experiment_id": experiment["id"],
        "snapshot_id": result["id"],
        "observed_at": measured.isoformat(),
        "metric_id": metric["metricId"],
        "metric_name": metric.get("metricName") or metric["metricId"],
        "sample_size": sample["totalUsers"],
        "lift": values["percentChange"],
        "interval": [values["ciLow"], values["ciHigh"]],
    }


def commercial_measurement(owner_id, delivery):
    """Reuse authoritative payment qualification; scope ledger receipts to the released artifact."""
    from modstore_server.customer_value_evidence import build_customer_value_evidence

    identity = delivery.get("identity") or {}
    artifact = identity.get("artifact_sha256", "")
    deployed = parse_datetime(delivery.get("verified_at"))
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
