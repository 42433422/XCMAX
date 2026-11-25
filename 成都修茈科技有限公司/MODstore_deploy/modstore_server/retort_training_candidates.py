"""Translate frozen capability-trainer candidates into existing Retort approvals."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from modstore_server.customer_service_tools import json_dumps, json_loads
from modstore_server.models import RetortEvolutionRun, User, get_session_factory


def _candidate(body):
    from modstore_server.capability_trainer import candidate_for_experiment

    bundle, files = json.loads(body["bundle_json"]), body["files"]
    names = {
        "baseline": "baseline_prompt.md",
        "candidate": "candidate_prompt.md",
        "config": "promptfooconfig.yaml",
        "tests": "tests.json",
    }
    if set(files) != set(names) or set(bundle.get("files", {})) != set(names):
        raise ValueError("training_bundle_files_incomplete")
    with TemporaryDirectory(prefix="retort-training-") as directory:
        root = Path(directory)
        for key, name in names.items():
            if bundle["files"][key].get("name") != name:
                raise ValueError("training_bundle_path_invalid")
            (root / name).write_text(files[key], encoding="utf-8")
        (root / "training-bundle.json").write_text(body["bundle_json"], encoding="utf-8")
        (root / "result.json").write_text(body["result_json"], encoding="utf-8")
        return candidate_for_experiment(root / "training-bundle.json", root / "result.json")


def _preverify_business_sources(body, bundle, spec):
    """Authorize original SQL fixtures before the seal can execute native packages."""
    from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
    from modstore_server.workflow_training_dataset import (
        BUSINESS_SCOPE,
        is_business_case,
    )

    life = spec.get("lifecycle") or {}
    tests = json.loads(body["files"]["tests"])
    if not isinstance(tests, list) or any(
        not isinstance(test, dict) or not isinstance(test.get("vars"), dict) for test in tests
    ):
        raise ValueError("training_bundle_tests_invalid")
    variables = [test["vars"] for test in tests]
    for item in variables:
        context = item.get("generation_context") or {}
        if not isinstance(context, dict) or not isinstance(
            context.get("execution_feedback") or {}, dict
        ):
            raise TypeError("training_bundle_tests_invalid")
    business = any(is_business_case(item) for item in variables)
    customer = life.get("measurement_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
    if not customer:
        if business or bundle.get("measurement_scope") == BUSINESS_SCOPE:
            raise ValueError("training_customer_experiment_required")
        return None
    case_ids = bundle.get("case_ids") or []
    if (
        life.get("surface") != "workflow_nl_prompt"
        or bundle.get("surface") != "workflow_nl_prompt"
        or body.get("surface") != "workflow_nl_prompt"
        or body.get("resource_id") != "workflow_nl_generator"
        or life.get("resource_id") != "workflow_nl_generator"
        or bundle.get("measurement_scope") != BUSINESS_SCOPE
        or not business
        or not case_ids
        or len(case_ids) != len(set(case_ids))
        or len(variables) != len(case_ids)
        or any(
            len(bundle.get(key, [])) != len(case_ids)
            for key in ("case_sha256", "case_context_sha256")
        )
    ):
        raise ValueError("training_customer_evidence_required")

    from modstore_server.workflow_execution_feedback import execution_failure_records
    from modstore_server.workflow_nl_training import _digest
    from modstore_server.workflow_training_dataset import partition_cases
    from modstore_server.workflow_training_replay import validate_replay_manifest

    # mine() also reads a maintenance JSONL ledger. Only the original SQL
    # producer may authorize customer-source bindings, even if a ledger entry
    # claims the same run id and supplies a self-consistent collection of hashes.
    records = deepcopy(
        execution_failure_records(
            days=14,
            cohort=life["cohort_user_ids"],
            baseline=bundle["prompt_sha256"]["control"],
        )
    )
    requested = body["failure_run_ids"]
    if (
        not requested
        or len(requested) != len(set(requested))
        or not set(requested).issubset({record["run_id"] for record in records})
    ):
        raise ValueError("training_customer_source_unbound")
    selected, sources, selected_runs = [], {}, set()
    for case_id, task_hash, context_hash, supplied in zip(
        case_ids, bundle["case_sha256"], bundle["case_context_sha256"], variables
    ):
        matching = [
            record
            for record in records
            if record["run_id"] in requested
            and hashlib.sha256(record["task_excerpt"].encode()).hexdigest() == task_hash
            and _digest(record["generation_context"]) == context_hash
        ]
        if (
            len(matching) != 1
            or supplied.get("case_id") != case_id
            or supplied.get("task") != matching[0]["task_excerpt"]
            or supplied.get("generation_context") != matching[0]["generation_context"]
        ):
            raise ValueError("training_customer_source_unbound")
        record = matching[0]
        context = record["generation_context"]
        feedback = context.get("execution_feedback") or {}
        outcome = feedback.get("customer_outcome") or {}
        manifest = context.get("customer_business_replay") or {}
        replay = validate_replay_manifest(manifest)
        required = outcome.get("required_artifacts") or []
        expected_paths = set(replay["expected_output_paths"])
        if (
            record.get("user_id") not in life["cohort_user_ids"]
            or record["run_id"] != f"workflow-customer:{feedback.get('execution_id')}"
            or feedback.get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT
            or feedback.get("failure_kind") != "business_outcome_failed"
            or outcome.get("classification") != "business_failure"
            or outcome.get("reason") != "customer_goal_not_met"
            or outcome.get("success") is not False
            or outcome.get("customer_policy") != life.get("customer_outcomes")
            or any(
                manifest.get(key) != value
                for key, value in {
                    "contract_sha256": outcome.get("contract_sha256"),
                    "source_evidence_sha256": outcome.get("evidence_sha256"),
                    "user_id": record.get("user_id"),
                    "workflow_id": record.get("workflow_id"),
                    "execution_id": feedback.get("execution_id"),
                    "input_sha256": _digest(feedback.get("input")),
                    "graph_fingerprint": feedback.get("graph_fingerprint"),
                }.items()
            )
            or not required
            or len(required) != len(expected_paths)
            or any(not isinstance(artifact, dict) for artifact in required)
            or {artifact.get("output_path") for artifact in required} != expected_paths
        ):
            raise ValueError("training_customer_source_unbound")
        sources[case_id] = {
            **{
                key: replay[key]
                for key in (
                    "manifest_sha256",
                    "source_group_sha256",
                    "expected_reference_sha256",
                    "expected_output_paths",
                )
            },
            "contract_sha256": outcome["contract_sha256"],
            "source_evidence_sha256": outcome["evidence_sha256"],
        }
        selected.append({"generation_context": context})
        selected_runs.add(record["run_id"])
    if selected_runs != set(requested):
        raise ValueError("training_customer_source_unbound")
    partitioned = partition_cases(selected)
    if (
        bundle.get("case_partitions") != [case["evaluation_partition"] for case in partitioned]
        or bundle.get("case_source_groups") != [case["source_group_sha256"] for case in partitioned]
        or any(
            supplied.get(key) != original[key]
            for supplied, original in zip(variables, partitioned)
            for key in ("evaluation_partition", "source_group_sha256")
        )
    ):
        raise ValueError("training_customer_holdout_unbound")
    return sources


def _customer_candidate_sources(bundle, spec, sources):
    """Match independent replay receipts against the pre-execution SQL snapshot."""
    from modstore_server.retort_experiment_surfaces import WORKFLOW_CUSTOMER_MEASUREMENT
    from modstore_server.workflow_training_dataset import BUSINESS_SCOPE

    life = spec.get("lifecycle") or {}
    offline = life.get("offline_evidence") or {}
    if life.get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT:
        if (
            offline.get("feedback_scope") == WORKFLOW_CUSTOMER_MEASUREMENT
            or offline.get("measurement_scope") == BUSINESS_SCOPE
        ):
            raise ValueError("training_customer_experiment_required")
        return
    evidence = offline.get("business_evidence")
    if (
        not sources
        or offline.get("measurement_scope") != BUSINESS_SCOPE
        or offline.get("feedback_scope") != WORKFLOW_CUSTOMER_MEASUREMENT
        or offline.get("runtime_verified") is not True
        or offline.get("holdout_verified") is not True
        or not isinstance(evidence, dict)
        or set(evidence) != set(sources)
        or set(evidence) != set(bundle["case_ids"])
    ):
        raise ValueError("training_customer_evidence_required")
    for case_id, source in sources.items():
        measured = evidence[case_id]
        if (
            not isinstance(measured, dict)
            or any(
                measured.get(key) != value
                for key, value in source.items()
                if key != "expected_output_paths"
            )
            or not isinstance(measured.get("output_sha256"), dict)
            or set(measured["output_sha256"]) != set(source["expected_output_paths"])
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", str(value))
                for value in measured["output_sha256"].values()
            )
        ):
            raise ValueError("training_customer_source_unbound")


def create_training_candidate(body):
    """The service may propose; existing admin checkpoint approvals own execution."""
    from modstore_server import retort_evolution as service
    from modstore_server.capability_trainer import (
        mine,
        prompt_from_source,
        training_identity,
    )
    from modstore_server.customer_ticket_github import configuration, github
    from modstore_server.maintenance_loop.store import ledger_path
    from modstore_server.retort_evolution_api import _templates
    from modstore_server.retort_experiment_surfaces import (
        RAG_MEASUREMENT,
        RAG_PROMPT_PATH,
        WORKFLOW_NL_PROMPT_PATH,
        surface_identity,
    )
    from modstore_server.retort_feedback_experiments import freeze_experiment_policy
    from modstore_server.retort_feedback_recovery import freeze_recovery_policy

    if len(json_dumps(body).encode()) > 2_000_000:
        raise ValueError("training_candidate_too_large")
    surface, resource = training_identity(body)
    candidates = [
        (key, template)
        for key, template in _templates().items()
        if (policy := template.get("training_candidate"))
        and policy.get(
            "surface",
            (policy.get("growthbook", {}).get("lifecycle") or {}).get("surface", "employee_prompt"),
        )
        == surface
        and policy.get("employee_id" if surface == "employee_prompt" else "resource_id") == resource
    ]
    if len(candidates) != 1:
        raise ValueError("training_employee_template_unbound")
    template_id, template = candidates[0]
    policy = template["training_candidate"]
    owner_id = policy.get("owner_id")
    if type(owner_id) is not int or owner_id <= 0:
        raise ValueError("training_owner_unbound")
    request_id = str(uuid5(NAMESPACE_URL, f"xcagi:training:{body['request_key']}"))
    source_digest = hashlib.sha256(json_dumps(body).encode()).hexdigest()
    with service.run_lock(request_id):
        with get_session_factory()() as db:
            owner = db.get(User, owner_id)
            if (
                owner is None
                or not owner.is_admin
                or getattr(owner, "is_active", True) is False
                or owner.deleted_at is not None
                or owner.account_state in {"disabled", "suspended", "blocked", "deleted"}
            ):
                raise ValueError("training_owner_unavailable")
            previous = db.get(RetortEvolutionRun, request_id)
            if previous:
                source = json_loads(previous.effects_json, {}).get("training_candidate") or {}
                if previous.user_id != owner_id or source.get("submission_digest") != source_digest:
                    raise ValueError("training_candidate_request_conflict")
                return request_id
        observed = {
            str(sample["run_id"]): sample
            for cluster in mine(ledger_path(), days=14, min_count=1)
            if training_identity(cluster) == (surface, resource)
            for sample in cluster["samples"]
            if sample.get("run_id")
        }
        if not body["failure_run_ids"] or not set(body["failure_run_ids"]).issubset(observed):
            raise ValueError("training_failure_source_unbound")
        source_hashes = {
            hashlib.sha256(observed[run_id]["task"].encode("utf-8")).hexdigest()
            for run_id in body["failure_run_ids"]
            if isinstance(observed[run_id].get("task"), str) and observed[run_id]["task"].strip()
        }
        bundle = json.loads(body["bundle_json"])
        cases = bundle["case_sha256"]
        if not cases or not set(cases).issubset(source_hashes):
            raise ValueError("training_reproduction_source_unbound")
        if surface in {"workflow_nl_prompt", "rag_context_prompt"}:
            from modstore_server.workflow_nl_training import _digest

            pairs = {
                (
                    hashlib.sha256(sample["task"].encode()).hexdigest(),
                    _digest(sample["generation_context"]),
                )
                for run_id in body["failure_run_ids"]
                if (sample := observed[run_id]).get("prompt_sha256")
                == bundle["prompt_sha256"]["control"]
            }
            contexts = bundle.get("case_context_sha256", [])
            if (
                bundle.get("surface") != surface
                or len(contexts) != len(cases)
                or not set(zip(cases, contexts)).issubset(pairs)
            ):
                raise ValueError("training_workflow_reproduction_unbound")
        repository = configuration()["repository"]
        if github("GET", f"/repos/{repository}/commits/main")["sha"] != body["source_sha"]:
            raise ValueError("training_baseline_not_current_main")
        prompt_path = policy.get("prompt_path", "")
        path = Path(prompt_path)
        if (
            not prompt_path
            or path.is_absolute()
            or ".." in path.parts
            or (
                path.name != "prompt.txt"
                if surface == "employee_prompt"
                else prompt_path
                != (RAG_PROMPT_PATH if surface == "rag_context_prompt" else WORKFLOW_NL_PROMPT_PATH)
            )
        ):
            raise ValueError("training_prompt_path_unbound")
        content = github(
            "GET",
            f"/repos/{repository}/contents/{quote(prompt_path, safe='/')}?ref={body['source_sha']}",
        )
        if (
            content.get("encoding") != "base64"
            or hashlib.sha256(
                prompt_from_source(
                    base64.b64decode(content["content"], validate=False).decode("utf-8"),
                    surface=surface,
                ).encode()
            ).hexdigest()
            != bundle["prompt_sha256"]["control"]
        ):
            raise ValueError("training_baseline_prompt_changed")
        growthbook = dict(policy.get("growthbook") or {})
        sources = _preverify_business_sources(body, bundle, growthbook)
        proposal = _candidate(body)
        if surface == "rag_context_prompt" and (
            proposal["offline_evidence"].get("measurement_scope") != RAG_MEASUREMENT
            or (growthbook.get("lifecycle") or {}).get("measurement_scope") != RAG_MEASUREMENT
        ):
            raise ValueError("training_rag_experiment_required")
        if (
            proposal["offline_evidence"].get("feedback_scope") == "workflow_execution_terminal"
            and (growthbook.get("lifecycle") or {}).get("measurement_scope")
            != "workflow_execution_terminal"
        ):
            raise ValueError("training_execution_experiment_required")
        growthbook["lifecycle"] = {**(growthbook.get("lifecycle") or {}), **proposal}
        if surface_identity(growthbook["lifecycle"]) != (surface, resource):
            raise ValueError("training_experiment_surface_unbound")
        growthbook = freeze_experiment_policy(growthbook)
        _customer_candidate_sources(bundle, growthbook, sources)
        request = {key: template[key] for key in ("criterion_ids", "checks", "container_image")}
        request.update(
            request_id=request_id,
            title=template["name"],
            goal=policy["goal"],
            repository=repository,
            source_sha=body["source_sha"],
        )
        return service.create_run(
            request,
            owner_id,
            training_candidate={
                "template_id": template_id,
                "surface": surface,
                **(
                    {"employee_id": resource}
                    if surface == "employee_prompt"
                    else {
                        "resource_id": resource,
                        "prompt_symbol": (
                            "RAG_SYSTEM_PROMPT"
                            if surface == "rag_context_prompt"
                            else "SYSTEM_PROMPT"
                        ),
                    }
                ),
                "submission_digest": source_digest,
                "failure_run_ids": body["failure_run_ids"],
                "workflow_run_id": body["workflow_run_id"],
                "prompt_path": prompt_path,
                "growthbook": growthbook,
                "recovery": freeze_recovery_policy(policy.get("recovery")),
                "private_evidence": {
                    key: body[key] for key in ("files", "bundle_json", "result_json")
                },
            },
        )


def verify_customer_training_release(spec, effects, delivery):
    """A customer training trial consumes the approved prompt from its real release."""
    from modstore_server.retort_experiment_surfaces import (
        WORKFLOW_CUSTOMER_MEASUREMENT,
        WORKFLOW_NL_PROMPT_PATH,
        WORKFLOW_NL_RESOURCE,
    )

    source = effects.get("training_candidate")
    life = spec.get("lifecycle") or {}
    if not source or life.get("measurement_scope") != WORKFLOW_CUSTOMER_MEASUREMENT:
        return
    from fastapi import HTTPException

    from modstore_server import workflow_nl_graph
    from modstore_server.capability_trainer import prompt_from_source
    from modstore_server.customer_ticket_github import configuration, github

    if (
        life.get("surface") != "workflow_nl_prompt"
        or source.get("surface") != "workflow_nl_prompt"
        or source.get("resource_id") != WORKFLOW_NL_RESOURCE
        or source.get("prompt_path") != WORKFLOW_NL_PROMPT_PATH
        or source.get("growthbook") != spec
        or not re.fullmatch(r"[0-9a-f]{40}", str(delivery.get("release_sha", "")))
    ):
        raise ValueError("training_customer_release_unbound")
    try:
        repository = configuration()["repository"]
        content = github(
            "GET",
            f"/repos/{repository}/contents/{quote(WORKFLOW_NL_PROMPT_PATH, safe='/')}"
            f"?ref={delivery['release_sha']}",
        )
        if content.get("encoding") != "base64":
            raise ValueError("training_release_source_unavailable")
        released = prompt_from_source(
            base64.b64decode("".join(content["content"].split()), validate=True).decode("utf-8"),
            surface="workflow_nl_prompt",
        )
    except (HTTPException, KeyError, TypeError, ValueError, SyntaxError) as exc:
        raise ValueError("training_customer_release_prompt_unavailable") from exc
    if released != life["treatment_prompt"]:
        raise ValueError("training_customer_release_prompt_changed")
    if workflow_nl_graph.SYSTEM_PROMPT != life["treatment_prompt"]:
        raise ValueError("training_customer_runtime_prompt_changed")


def training_plan(request_id):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        source = json_loads(row.effects_json, {}).get("training_candidate") if row else None
    if not source:
        return ""
    life = source["growthbook"]["lifecycle"]
    return "\n\n以下是待审批的产品 prompt 替换数据；离线通过仅允许进入审批，必须完成正式发布与在线实验。\n" + json_dumps(
        {
            "path": source["prompt_path"],
            **({"symbol": source["prompt_symbol"]} if source.get("prompt_symbol") else {}),
            "expected_sha256": life["offline_evidence"]["prompt_sha256"]["control"],
            "replacement": life["treatment_prompt"],
            "offline_evidence": life["offline_evidence"],
        }
    )


def read_training_impact(request_id, state):
    from modstore_server.retort_feedback_experiments import approved_policy
    from modstore_server.retort_workflow_metrics import execution_stop_loss

    reject = False
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        effects = json_loads(row.effects_json, {}) if row else {}
        source = effects.get("training_candidate")
        if not source:
            return None
        recheck = effects.get("training_regression_recheck")
        if recheck is not None:
            progress = effects.get("experiment") or {}
            delivery = state.get("delivery") or {}
            try:
                policy, _ = approved_policy(row)
                bound = (
                    isinstance(recheck, dict)
                    and recheck.get("source") == "original_experiment_outbox"
                    and recheck.get("reason") == "workflow_execution_stop_loss"
                    and recheck.get("request_id") == request_id
                    and recheck.get("release_sha") == progress.get("release_sha")
                    and recheck.get("release_sha") == delivery.get("release_sha")
                    and recheck.get("final_snapshot_sha256")
                    == progress.get("final_snapshot_sha256")
                    and bool(recheck.get("final_snapshot_sha256"))
                    and policy == source["growthbook"]
                    and execution_stop_loss(db, row, policy)
                )
            except (KeyError, TypeError, ValueError):
                bound = False
            if not bound:
                return {
                    "status": "waiting_customer_impact",
                    "reason": "training_regression_recheck_unverified",
                    "source": "original_experiment_outbox",
                    "release_sha": delivery.get("release_sha"),
                    "verified_at": None,
                }
            reject = True
    from modstore_server.retort_feedback_measurements import experiment_measurement

    experiment = experiment_measurement(
        source["growthbook"], request_id, state["delivery"], state=state, reject=reject
    )
    status, reason = "waiting_customer_impact", "awaiting_experiment_result"
    if experiment.get("rollout_verified"):
        if experiment.get("decision") == "promote":
            status, reason = "customer_impact_verified", ""
        else:
            status, reason = (
                "customer_impact_rejected",
                (
                    "experiment_inconclusive"
                    if experiment.get("inconclusive")
                    else "experiment_regression"
                ),
            )
    return {
        "status": status,
        "reason": reason,
        "source": "growthbook",
        "experiment": experiment,
        "release_sha": state["delivery"].get("release_sha"),
        "verified_at": experiment.get("observed_at"),
    }


def postpromotion_effect_snapshot(db, row, policy, effects, *, observed_at):
    """Observe actual approved-rollout outbox receipts, not a synthetic uplift.

    The original GrowthBook trial owns the randomized causal decision. Once
    the temporary rollout starts there is no concurrent control arm, so the
    post-rollout stream may only establish absolute observed outcomes.
    """
    from datetime import UTC, datetime

    from modstore_server.models import OutboxEvent
    from modstore_server.retort_experiment_surfaces import (
        RAG_MEASUREMENT,
        WORKFLOW_CUSTOMER_MEASUREMENT,
    )

    def aware(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.utcoffset() is not None else None

    progress = effects.get("experiment") or {}
    life = policy.get("lifecycle") or {}
    start = aware(progress.get("closed_at"))
    if (
        start is None
        or start.utcoffset() is None
        or observed_at.tzinfo is None
        or start > observed_at
        or progress.get("traffic") != "candidate"
        or progress.get("decision") != "promote"
        or progress.get("rollout_verified") is not True
    ):
        return None
    start = start.astimezone(UTC)
    now = observed_at.astimezone(UTC)
    source_digests, subjects, failed_subjects, unique_executions = [], set(), set(), set()
    successes = failures = 0
    unverified = False
    query = (
        db.query(OutboxEvent)
        .filter_by(aggregate_id=row.id, event_name="experiment.postpromotion_observed")
        .order_by(OutboxEvent.id)
        .limit(10001)
    )
    records = list(query)
    if len(records) > 10000:
        return {
            "status": "blocked_source_budget",
            "scope": "postpromotion_absolute_outcomes_not_causal_lift",
            "window_start": start.isoformat(),
            "observed_through": now.isoformat(),
        }
    for event in records:
        item = json_loads(event.payload_json, {})
        if not isinstance(item, dict) or item.get("assignment_stage") != "approved_rollout":
            continue
        completed = aware(item.get("completed_at"))
        assigned = aware(item.get("assigned_at"))
        if completed is None or assigned is None:
            unverified = True
            continue
        completed = completed.astimezone(UTC)
        assigned = assigned.astimezone(UTC)
        if not start <= assigned <= completed <= now:
            if completed > now or assigned < start:
                unverified = True
            continue
        if (
            item.get("request_id") != row.id
            or item.get("experiment_id") != progress.get("experiment_id")
            or item.get("release_sha") != progress.get("release_sha")
            or item.get("policy_digest") != progress.get("policy_digest")
            or item.get("measurement_scope") != life.get("measurement_scope")
            or item.get("variation_id") != "1"
            or type(item.get("success")) is not bool
            or not item.get("observation_id")
            or not item.get("subject_id")
            or type(item.get("user_id")) is not int
            or str(item["user_id"]) != str(item["subject_id"])
        ):
            unverified = True
            continue
        scope = life.get("measurement_scope")
        if scope == WORKFLOW_CUSTOMER_MEASUREMENT:
            original = item.get("customer_outcome_evidence_sha256")
            if not isinstance(original, str) or not re.fullmatch(r"[0-9a-f]{64}", original):
                unverified = True
                continue
        elif scope == RAG_MEASUREMENT:
            original = item.get("rag_evidence_sha256")
            if not isinstance(original, str) or not re.fullmatch(r"[0-9a-f]{64}", original):
                unverified = True
                continue
        else:
            # Other surfaces have no approved-rollout terminal evidence contract.
            unverified = True
            continue
        execution = item.get("execution_id") or item["observation_id"]
        key = (str(item["subject_id"]), str(execution))
        if key in unique_executions:
            unverified = True
            continue
        unique_executions.add(key)
        subjects.add(str(item["subject_id"]))
        successes += int(item["success"])
        failures += int(not item["success"])
        if not item["success"]:
            failed_subjects.add(str(item["subject_id"]))
        source_digests.append(hashlib.sha256(event.payload_json.encode()).hexdigest())
    sample_count = successes + failures
    return {
        "status": (
            "source_unverified" if unverified else "observational_only" if sample_count else "unknown"
        ),
        "scope": "postpromotion_absolute_outcomes_not_causal_lift",
        "reason": (
            "invalid_original_receipts"
            if unverified
            else "no_control_arm_after_rollout" if sample_count else "no_verified_postpromotion_outcomes"
        ),
        "source": "original_experiment_outbox",
        "experiment_id": progress.get("experiment_id"),
        "release_sha": progress.get("release_sha"),
        "policy_digest": progress.get("policy_digest"),
        "window_start": start.isoformat(),
        "observed_through": now.isoformat(),
        "observations": sample_count,
        "successes": successes,
        "failures": failures,
        "unique_subjects": len(subjects),
        "failed_subjects": len(failed_subjects),
        "source_events_sha256": hashlib.sha256(
            json_dumps(sorted(source_digests)).encode()
        ).hexdigest(),
        "independently_verified_lift": False,
    }


def request_postpromotion_regression_rechecks():
    """Reopen the original Retort impact/recovery tail after a late live stop-loss.

    The existing product outbox decides whether treatment traffic regressed.
    Keep a bounded daily cumulative observation history without claiming causal
    uplift after GrowthBook's randomized window. A compare-and-swap claim
    prevents duplicate graph re-entry; no business write is replayed.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select, update

    from modstore_server.retort_feedback_experiments import (
        approved_policy,
        traffic_block_reason,
    )

    claimed = 0
    with get_session_factory()() as db:
        with db.scalars(
            select(RetortEvolutionRun).where(
                RetortEvolutionRun.status == "completed",
                RetortEvolutionRun.effects_json.contains('"training_candidate"', autoescape=True),
            )
        ).yield_per(32) as rows:
            for row in rows:
                original = row.effects_json
                effects = json_loads(original, {})
                source, experiment = effects.get("training_candidate"), effects.get("experiment")
                if (
                    not isinstance(source, dict)
                    or not isinstance(experiment, dict)
                    or experiment.get("traffic") != "candidate"
                    or experiment.get("decision") != "promote"
                    or experiment.get("rollout_verified") is not True
                ):
                    continue
                try:
                    policy, verified = approved_policy(row)
                except (ValueError, KeyError, TypeError):
                    continue
                if (
                    verified.get("training_candidate") != source
                    or policy != source.get("growthbook")
                ):
                    continue
                block = traffic_block_reason(db, row, verified)
                if not block:
                    # One cumulative as-of snapshot per UTC day; never a causal
                    # uplift claim, nor fabricated control-group observations.
                    observed_at = datetime.now(UTC)
                    existing = effects.get("training_online_observations") or {}
                    history = existing.get("snapshots") if isinstance(existing, dict) else None
                    if history is None:
                        history = []
                    if (
                        not isinstance(history, list)
                        or any(not isinstance(item, dict) for item in history)
                    ):
                        continue
                    snapshot_date = observed_at.date().isoformat()
                    if not any(item.get("snapshot_date") == snapshot_date for item in history):
                        snapshot = postpromotion_effect_snapshot(
                            db, row, policy, effects, observed_at=observed_at
                        )
                        if snapshot is not None:
                            effects["training_online_observations"] = {
                                "source": "original_experiment_outbox",
                                "scope": "cumulative_absolute_observation_not_causal_lift",
                                "snapshots": [
                                    *history[-29:],
                                    {**snapshot, "snapshot_date": snapshot_date},
                                ],
                            }
                            db.execute(
                                update(RetortEvolutionRun)
                                .where(
                                    RetortEvolutionRun.id == row.id,
                                    RetortEvolutionRun.status == "completed",
                                    RetortEvolutionRun.effects_json == original,
                                )
                                .values(
                                    effects_json=json_dumps(effects),
                                    updated_at=observed_at,
                                )
                            )
                    continue
                if block != "workflow_execution_stop_loss":
                    continue
                effects["training_regression_recheck"] = {
                    "source": "original_experiment_outbox",
                    "reason": "workflow_execution_stop_loss",
                    "request_id": row.id,
                    "release_sha": experiment.get("release_sha"),
                    "final_snapshot_sha256": experiment.get("final_snapshot_sha256"),
                }
                result = db.execute(
                    update(RetortEvolutionRun)
                    .where(
                        RetortEvolutionRun.id == row.id,
                        RetortEvolutionRun.status == "completed",
                        RetortEvolutionRun.effects_json == original,
                    )
                    .values(
                        status="impact_recheck",
                        effects_json=json_dumps(effects),
                        updated_at=datetime.now(UTC),
                    )
                )
                claimed += int(result.rowcount == 1)
        db.commit()
    return claimed
