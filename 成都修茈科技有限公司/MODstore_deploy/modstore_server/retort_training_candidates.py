"""Translate frozen capability-trainer candidates into existing Retort approvals."""

from __future__ import annotations

import base64
import hashlib
import json
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


def create_training_candidate(body):
    """The service may propose; existing admin checkpoint approvals own execution."""
    from modstore_server import retort_evolution as service
    from modstore_server.capability_trainer import mine
    from modstore_server.customer_ticket_github import configuration, github
    from modstore_server.maintenance_loop.store import ledger_path
    from modstore_server.retort_evolution_api import _templates
    from modstore_server.retort_feedback_experiments import freeze_experiment_policy
    from modstore_server.retort_feedback_recovery import freeze_recovery_policy

    if len(json_dumps(body).encode()) > 2_000_000:
        raise ValueError("training_candidate_too_large")
    candidates = [
        (key, template)
        for key, template in _templates().items()
        if (template.get("training_candidate") or {}).get("employee_id") == body["employee_id"]
    ]
    if len(candidates) != 1:
        raise ValueError("training_employee_template_unbound")
    template_id, template = candidates[0]
    policy = template["training_candidate"]
    owner_id = policy.get("owner_id")
    if type(owner_id) is not int or owner_id <= 0:
        raise ValueError("training_owner_unbound")
    proposal = _candidate(body)
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
            str(sample["run_id"])
            for cluster in mine(ledger_path(), days=14, min_count=1)
            if cluster["employee_id"] == body["employee_id"]
            for sample in cluster["samples"]
            if sample.get("run_id")
        }
        if not body["failure_run_ids"] or not set(body["failure_run_ids"]).issubset(observed):
            raise ValueError("training_failure_source_unbound")
        repository = configuration()["repository"]
        if github("GET", f"/repos/{repository}/commits/main")["sha"] != body["source_sha"]:
            raise ValueError("training_baseline_not_current_main")
        prompt_path = policy.get("prompt_path", "")
        path = Path(prompt_path)
        if not prompt_path or path.is_absolute() or ".." in path.parts or path.name != "prompt.txt":
            raise ValueError("training_prompt_path_unbound")
        content = github(
            "GET",
            f"/repos/{repository}/contents/{quote(prompt_path, safe='/')}?ref={body['source_sha']}",
        )
        if (
            content.get("encoding") != "base64"
            or base64.b64decode(content["content"], validate=False).decode("utf-8")
            != proposal["control_prompt"]
        ):
            raise ValueError("training_baseline_prompt_changed")
        growthbook = dict(policy.get("growthbook") or {})
        growthbook["lifecycle"] = {**(growthbook.get("lifecycle") or {}), **proposal}
        if growthbook["lifecycle"].get("employee_id") != body["employee_id"]:
            raise ValueError("training_experiment_surface_unbound")
        growthbook = freeze_experiment_policy(growthbook)
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
                "employee_id": body["employee_id"],
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
            "expected_sha256": life["offline_evidence"]["prompt_sha256"]["control"],
            "replacement": life["treatment_prompt"],
            "offline_evidence": life["offline_evidence"],
        }
    )


def read_training_impact(request_id, state):
    with get_session_factory()() as db:
        row = db.get(RetortEvolutionRun, request_id)
        source = json_loads(row.effects_json, {}).get("training_candidate") if row else None
    if not source:
        return None
    from modstore_server.retort_feedback_measurements import experiment_measurement

    experiment = experiment_measurement(
        source["growthbook"], request_id, state["delivery"], state=state
    )
    status, reason = "waiting_customer_impact", "awaiting_experiment_result"
    if experiment.get("rollout_verified"):
        if experiment.get("decision") == "promote":
            status, reason = "customer_impact_verified", ""
        else:
            status, reason = "customer_impact_rejected", (
                "experiment_inconclusive"
                if experiment.get("inconclusive")
                else "experiment_regression"
            )
    return {
        "status": status,
        "reason": reason,
        "source": "growthbook",
        "experiment": experiment,
        "release_sha": state["delivery"].get("release_sha"),
        "verified_at": experiment.get("observed_at"),
    }
