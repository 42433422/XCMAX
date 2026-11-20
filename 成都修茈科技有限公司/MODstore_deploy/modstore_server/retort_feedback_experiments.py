"""Approved experiment lifecycle over GrowthBook's v1 API and Retort's durable effects.

GrowthBook owns allocation/statistics. This adapter binds its remote experiment to
an approved local surface, release, cohort and fixed observation window.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

import httpx

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.customer_value_classification import parse_datetime
from modstore_server.integrations.repository_packages import load_repository_module
from modstore_server.models import RetortEvolutionRun, get_session_factory
from modstore_server.retort_feedback_measurements import (
    _number,
    _snapshot,
    _valid_policy,
    growthbook_client,
)


def _digest(value):
    return load_repository_module("retort_engine.evolution_contract").digest(value)


def freeze_experiment_policy(spec):
    """Only operator templates can authorize a live experiment; model output cannot."""
    if not spec:
        return {}
    if not isinstance(spec, dict) or not _valid_policy(spec) or not spec.get("project"):
        raise ValueError("invalid_feedback_experiment_policy")
    life = spec.get("lifecycle")
    if not life:
        return spec
    if not isinstance(life, dict):
        raise ValueError("invalid_feedback_experiment_lifecycle")
    users, weights = life.get("cohort_user_ids"), life.get("weights", [0.5, 0.5])
    if (
        life.get("surface") != "employee_prompt"
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(life.get("employee_id", "")))
        or not isinstance(users, list)
        or not 2 <= len(users) <= 10000
        or any(type(user) is not int or user <= 0 for user in users)
        or len(set(users)) != len(users)
        or spec["minimum_users"] > len(users)
        or type(life.get("duration_hours")) is not int
        or not 1 <= life["duration_hours"] <= 720
        or type(life.get("maturation_hours", 0)) is not int
        or not 0 <= life.get("maturation_hours", 0) <= 168
        or not _number(life.get("coverage"))
        or not 0 < life["coverage"] <= 1
        or not isinstance(weights, list)
        or len(weights) != 2
        or any(not _number(weight) or not 0 < weight < 1 for weight in weights)
        or abs(sum(weights) - 1) > 1e-9
        or spec.get("stats_engine") not in {"bayesian", "frequentist"}
        or any(
            not isinstance(life.get(key), str) or not 1 <= len(life[key]) <= 16000
            for key in ("control_prompt", "treatment_prompt")
        )
        or life["control_prompt"] == life["treatment_prompt"]
        or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(life.get(key, "")))
            for key in ("datasource_id", "assignment_query_id")
        )
    ):
        raise ValueError("invalid_feedback_experiment_lifecycle")
    offline = life.get("offline_evidence")
    if offline and (
        not isinstance(offline, dict)
        or offline.get("verdict") != "candidate_for_approval"
        or offline.get("engine") != "promptfoo@0.126.0"
        or offline.get("prompt_sha256")
        != {
            "control": hashlib.sha256(life["control_prompt"].encode()).hexdigest(),
            "candidate": hashlib.sha256(life["treatment_prompt"].encode()).hexdigest(),
        }
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(offline.get(key, "")))
            for key in ("bundle_sha256", "results_sha256")
        )
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", str(offline.get("files", {}).get(key, "")))
            for key in ("baseline", "candidate", "config", "tests")
        )
    ):
        raise ValueError("training_evidence_unbound")
    return {
        **spec,
        "lifecycle": {
            **life,
            "weights": weights,
            "maturation_hours": life.get("maturation_hours", 0),
        },
    }


def approved_policy(row):
    """Public to surface adapters: verify the same digest as the approved dispatch."""
    effects = json_loads(row.effects_json, {})
    spec = (effects.get("customer_feedback") or effects.get("training_candidate") or {}).get(
        "growthbook"
    ) or {}
    plan, auth = effects.get("plan") or {}, effects.get("authorization") or {}
    if (
        not spec.get("lifecycle")
        or auth.get("approved") is not True
        or auth.get("digest")
        != _digest(
            {
                "protocol": json_loads(row.protocol_json, {}),
                "plan": plan,
                "optimization": effects.get("optimization"),
            }
        )
        or plan.get("feedback_policy", {}).get("growthbook") != spec
    ):
        raise ValueError("experiment_approval_mismatch")
    freeze_experiment_policy(spec)
    return spec, effects


def _save(request_id, progress):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = json_loads(row.effects_json, {})
        effects["experiment"] = progress
        row.effects_json = json_dumps(effects)
        db.commit()


def _post_once(client, request_id, progress, operation, path, body):
    """Unknown outcomes remain pending; subsequent ticks reconcile with authoritative GETs."""
    operations = progress.setdefault("operations", {})
    if operation in operations:
        return
    operations[operation] = {"submitted_at": datetime.now(UTC).isoformat(), "digest": _digest(body)}
    _save(request_id, progress)
    response = client.post(path, json=body)
    response.raise_for_status()
    operations[operation]["http_status"] = response.status_code
    if response.status_code == 202:
        operations[operation]["awaiting_external_approval"] = True
    _save(request_id, progress)


def _matches(experiment, spec, request_id, delivery):
    life, settings = spec["lifecycle"], experiment["settings"]
    variations, phases = experiment["variations"], experiment["phases"]
    phase = phases[-1] if phases else {}
    return (
        experiment["trackingKey"] == f"xcagi-retort-{request_id}"
        and experiment["project"] == spec["project"]
        and experiment["type"] == "standard"
        and not experiment["archived"]
        and experiment["hashAttribute"] == "id"
        and experiment["hashVersion"] == 2
        and f"xcagi-release-{delivery['release_sha']}" in experiment["tags"]
        and f"xcagi-policy-{_digest(spec)}" in experiment["tags"]
        and settings["datasourceId"] == life["datasource_id"]
        and settings.get("assignmentQueryId") == life["assignment_query_id"]
        and settings["statsEngine"] == spec["stats_engine"]
        and settings.get("sequentialTestingEnabled") is False
        and not settings.get("segmentId")
        and not settings.get("queryFilter")
        and not settings.get("activationMetric")
        and not settings.get("secondaryMetrics")
        and [metric["metricId"] for metric in settings["goals"]] == [spec["metric"]]
        and {metric["metricId"] for metric in settings["guardrails"]}
        == {rule["metric"] for rule in spec.get("guardrails", [])}
        and [variation["key"] for variation in variations] == ["0", "1"]
        and len(phases) == 1
        and phase["coverage"] == life["coverage"]
        and phase["seed"] == f"xcagi-retort-{request_id}"
        and phase.get("targetingCondition", "") in {"", "{}"}
        and not phase.get("namespace", {}).get("enabled")
        and not phase.get("prerequisites")
        and not phase.get("savedGroupTargeting")
        and phase["trafficSplit"]
        == [
            {"variationId": variation["variationId"], "weight": weight}
            for variation, weight in zip(variations, life["weights"])
        ]
    )


def _create_payload(spec, request_id, delivery):
    life, key = spec["lifecycle"], f"xcagi-retort-{request_id}"
    return {
        "name": key,
        "trackingKey": key,
        "project": spec["project"],
        "type": "standard",
        "datasourceId": life["datasource_id"],
        "assignmentQueryId": life["assignment_query_id"],
        "status": "draft",
        "autoRefresh": False,
        "hashAttribute": "id",
        "hashVersion": 2,
        "statsEngine": spec["stats_engine"],
        "sequentialTestingEnabled": False,
        "segmentId": "",
        "queryFilter": "",
        "secondaryMetrics": [],
        "metrics": [spec["metric"]],
        "guardrailMetrics": [rule["metric"] for rule in spec.get("guardrails", [])],
        "tags": [f"xcagi-release-{delivery['release_sha']}", f"xcagi-policy-{_digest(spec)}"],
        "variations": [{"key": "0", "name": "Control"}, {"key": "1", "name": "Candidate"}],
        "phases": [
            {
                "name": "Approved fixed window",
                "dateStarted": datetime.now(UTC).isoformat(),
                "seed": key,
                "coverage": life["coverage"],
                "variationWeights": life["weights"],
            }
        ],
    }


def advance_experiment(request_id, delivery, *, state=None, reject=False):
    """Run under Retort's run lock; absent traffic/data never becomes an improvement."""
    progress = {}
    try:
        with get_session_factory()() as db:
            row = db.get(RetortEvolutionRun, request_id)
            spec, effects = approved_policy(row)
        progress = effects.get("experiment") or {}
        if (
            state is None
            or state.get("approval", {}).get("approved") is not True
            or state["approval"].get("digest") != _digest(state["verification"])
        ):
            raise ValueError("experiment_acceptance_unverified")
        if delivery.get("status") != "deployment_verified" or not re.fullmatch(
            r"[0-9a-f]{40}", str(delivery.get("release_sha", ""))
        ):
            raise ValueError("experiment_delivery_unverified")
        if progress.get("release_sha") and progress["release_sha"] != delivery["release_sha"]:
            raise ValueError("experiment_release_changed")
        progress.update(
            release_sha=delivery["release_sha"],
            policy_digest=_digest(spec),
            identity=delivery.get("identity"),
        )
        if reject:
            # Close local traffic first, even if the remote control plane is unavailable.
            progress.update(traffic="control", decision="rollback")
            _save(request_id, progress)
        with growthbook_client() as client:
            listing = client.get(
                "experiments",
                params={
                    "trackingKey": f"xcagi-retort-{request_id}",
                    "projectId": spec["project"],
                    "limit": 2,
                },
            )
            listing.raise_for_status()
            listing = listing.json()
            experiments = listing["experiments"]
            if len(experiments) > 1 or listing.get("hasMore"):
                raise ValueError("experiment_binding_ambiguous")
            if not experiments:
                if reject:
                    return {"status": "withdrawn", "decision": "rollback"}
                _post_once(
                    client,
                    request_id,
                    progress,
                    "create",
                    "experiments",
                    _create_payload(spec, request_id, delivery),
                )
                return {"status": "awaiting_experiment_readback", "decision": "hold"}
            experiment = experiments[0]
            if not _matches(experiment, spec, request_id, delivery):
                raise ValueError("experiment_binding_changed")
            experiment_id = experiment["id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", experiment_id):
                raise ValueError("invalid_experiment_id")
            progress["experiment_id"] = experiment_id
            path = f"experiments/{experiment_id}"
            if experiment["status"] == "draft" and not reject:
                _post_once(client, request_id, progress, "start", f"{path}/start", {})
                return {"status": "awaiting_experiment_start", "decision": "hold"}
            started = parse_datetime(experiment["phases"][0]["dateStarted"])
            deployed = parse_datetime(delivery.get("deployment_completed_at"))
            if not started or not deployed or not deployed <= started <= datetime.now(UTC):
                raise ValueError("experiment_window_unbound")
            if progress.get("started_at") and progress["started_at"] != started.isoformat():
                raise ValueError("experiment_window_changed")
            end = started + timedelta(hours=spec["lifecycle"]["duration_hours"])
            ready = end + timedelta(hours=spec["lifecycle"]["maturation_hours"])
            progress.update(
                started_at=started.isoformat(),
                exposure_ends_at=end.isoformat(),
                evaluation_at=ready.isoformat(),
            )
            if not reject and datetime.now(UTC) < ready and experiment["status"] == "running":
                progress["traffic"] = "experiment" if datetime.now(UTC) < end else "control"
                progress["lease_until"] = min(
                    end, datetime.now(UTC) + timedelta(minutes=15)
                ).isoformat()
                _save(request_id, progress)
                return {
                    "status": "running",
                    "decision": "hold",
                    "experiment_id": experiment_id,
                    "evaluation_at": ready.isoformat(),
                }
            progress["traffic"] = "control"
            _save(request_id, progress)
            measured = {}
            if not reject:
                _post_once(
                    client,
                    request_id,
                    progress,
                    "final_snapshot",
                    f"{path}/snapshot",
                    {"triggeredBy": "schedule"},
                )
                response = client.get(f"{path}/results")
                response.raise_for_status()
                payload = response.json()
                if not _matches(payload["experiment"], spec, request_id, delivery):
                    raise ValueError("experiment_result_binding_changed")
                measured = _snapshot(payload, {**spec, "id": experiment_id}, request_id, delivery)
                observed = parse_datetime(payload["result"].get("dateUpdated"))
                data_end = parse_datetime(payload["result"].get("dateEnd"))
                if (
                    not observed
                    or observed < ready
                    or not data_end
                    or not ready <= data_end <= observed
                    or not payload["result"].get("queryIds")
                    or measured.get("status") not in {"running", "measured", "sample_unverified"}
                ):
                    return {
                        "status": "awaiting_final_snapshot",
                        "decision": "hold",
                        "measurement": measured,
                    }
            decision = "rollback" if reject else measured.get("evaluated_decision", "hold")
            chosen = 1 if decision == "promote" else 0
            variation_id = experiment["variations"][chosen]["variationId"]
            if experiment["status"] != "stopped":
                _post_once(
                    client,
                    request_id,
                    progress,
                    "stop",
                    f"{path}/stop",
                    {
                        "results": (
                            "won"
                            if chosen
                            else "lost" if decision == "rollback" else "inconclusive"
                        ),
                        "enableTemporaryRollout": True,
                        "releasedVariationId": variation_id,
                        "reason": "Approved fixed-window result",
                    },
                )
                return {"status": "awaiting_experiment_stop", "decision": "hold"}
            summary = experiment.get("resultSummary") or {}
            if (
                summary.get("releasedVariationId") != variation_id
                or summary.get("excludeFromPayload") is not False
            ):
                if reject:
                    _post_once(
                        client,
                        request_id,
                        progress,
                        "withdraw",
                        f"{path}/modify-temporary-rollout",
                        {"enableTemporaryRollout": True, "releasedVariationId": variation_id},
                    )
                return {"status": "awaiting_rollout_readback", "decision": "hold"}
            progress.update(
                traffic="candidate" if chosen else "control",
                decision=decision,
                measurement=measured,
                rollout_verified=True,
                closed_at=datetime.now(UTC).isoformat(),
            )
            _save(request_id, progress)
            return {
                **measured,
                "status": "inconclusive" if decision == "hold" else "measured",
                "decision": decision,
                "rollout_verified": True,
                "inconclusive": decision == "hold",
                "observed_at": datetime.now(UTC).isoformat(),
            }
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        if progress:
            progress.update(traffic="control", last_error=type(exc).__name__)
            _save(request_id, progress)
        return {
            "status": "experiment_blocked",
            "decision": "hold",
            "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
        }
