"""Read-only projection of the original GrowthBook terminal experiment receipt."""

from copy import deepcopy

import pytest

from modstore_server.xiaoc_life_experiment_review import frozen_experiment_projection


def fixture():
    deployment = "2026-11-20T00:00:00+00:00"
    start = "2026-11-20T01:00:00+00:00"
    end = "2026-11-21T01:00:00+00:00"
    observed = "2026-11-21T02:00:00+00:00"
    release = "a" * 40
    delivery = {
        "status": "deployment_verified",
        "release_sha": release,
        "deployment_completed_at": deployment,
        "identity": {"git_sha": release, "artifact_sha256": "b" * 64},
    }
    spec = {
        "metric": "acceptance",
        "minimum_users": 10,
        "direction": "increase",
        "lifecycle": {"cohort_user_ids": list(range(1, 21))},
    }
    measurement = {
        "source": "growthbook",
        "status": "running",
        "experiment_id": "experiment-1",
        "snapshot_id": "snapshot-1",
        "metric_id": "acceptance",
        "direction": "increase",
        "sample_size": 20,
        "lift": 0.1,
        "interval": [0.01, 0.2],
        "evaluated_decision": "promote",
        "observed_at": observed,
    }
    progress = {
        "release_sha": release,
        "identity": deepcopy(delivery["identity"]),
        "policy_digest": "c" * 64,
        "rollout_verified": True,
        "execution_source_verified": True,
        "final_snapshot_sha256": "d" * 64,
        "experiment_id": "experiment-1",
        "final_measurement": measurement,
        "measurement": deepcopy(measurement),
        "decision": "promote",
        "traffic": "candidate",
        "started_at": start,
        "exposure_ends_at": end,
        "evaluation_at": end,
        "closed_at": observed,
    }
    return spec, progress, delivery


@pytest.mark.parametrize("decision", ["promote", "rollback", "hold"])
def test_frozen_experiment_is_observation_only(decision):
    spec, progress, delivery = fixture()
    progress.update(
        decision=decision,
        traffic="candidate" if decision == "promote" else "control",
    )
    for key in ("measurement", "final_measurement"):
        progress[key]["evaluated_decision"] = decision
    original = deepcopy((spec, progress, delivery))
    result = frozen_experiment_projection(spec, progress, delivery, policy_digest="c" * 64)
    assert result["status"] == ("inconclusive" if decision == "hold" else "measured")
    assert result["decision"] == decision
    assert result["finding_type"] == "historical_experiment_estimate_not_general_causal_proof"
    assert (spec, progress, delivery) == original


@pytest.mark.parametrize(
    "change",
    [
        "policy",
        "release",
        "identity",
        "source",
        "rollout",
        "snapshot",
        "decision",
        "early",
        "sample",
        "metric",
        "interval",
        "measurement",
    ],
)
def test_experiment_with_unverified_evidence_is_unknown(change):
    spec, progress, delivery = fixture()
    if change == "policy":
        progress["policy_digest"] = "f" * 64
    elif change == "release":
        delivery["release_sha"] = "f" * 40
    elif change == "identity":
        delivery["identity"]["artifact_sha256"] = "f" * 64
    elif change == "source":
        progress["execution_source_verified"] = False
    elif change == "rollout":
        progress["rollout_verified"] = False
    elif change == "snapshot":
        progress["final_snapshot_sha256"] = ""
    elif change == "decision":
        progress["decision"] = "rollback"
    elif change == "early":
        progress["evaluation_at"] = "2026-11-22T01:00:00+00:00"
    elif change == "measurement":
        progress["measurement"]["lift"] = 99
    else:
        key, value = {
            "sample": ("sample_size", 1),
            "metric": ("metric_id", "another"),
            "interval": ("interval", [0.2, 0.01]),
        }[change]
        progress["measurement"][key] = value
        progress["final_measurement"][key] = value
    assert frozen_experiment_projection(spec, progress, delivery, policy_digest="c" * 64) == {
        "status": "unknown",
        "finding_type": "unknown",
    }


def test_portfolio_experiment_requires_same_frozen_approval_worker_and_terminal(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from modstore_server import strategic_workspace_bridge, strategic_workspace_receipts
    from modstore_server import xiaoc_life_experiment_review as review
    from modstore_server.business_decision_review import proposal_content
    from modstore_server.strategic_portfolio import digest

    spec, progress, delivery = fixture()
    now = datetime(2026, 11, 24, tzinfo=UTC)
    remote = {
        "kind": strategic_workspace_bridge.KIND,
        "original_request_id": "request-1",
    }
    item = {"opportunity_id": "op-1", "input_data": {"remote_execution": remote}}
    proposal = {
        "schema": "xcagi.strategic_portfolio/v1",
        "owner_user_id": 7,
        "goal": "verify effect",
        "period": "one",
        "limits": {"company_budget_id": "approved"},
        "opportunities": [item],
    }
    proposal["proposal_sha256"] = digest(proposal_content(proposal))
    sha = proposal["proposal_sha256"]
    receipt = {"ok": True, "remote_receipt": {"delivery": delivery}}
    task = {
        "status": "completed",
        "result_sha256": digest(receipt),
        "execution_receipt": receipt,
        "calls": {},
        "lease_token": "lease",
        "started_at": "2026-11-19T01:00:00+00:00",
        "completed_at": "2026-11-21T03:00:00+00:00",
        "worker_binding": {
            "decision_id": "d1",
            "opportunity_id": "op-1",
            "owner_user_id": 7,
            "proposal_sha256": sha,
            "adapter": strategic_workspace_bridge.KIND,
            "receipt_id": "request-1",
            "lease_token": "lease",
        },
    }
    state = {
        "authorization": {"user_id": 7, "actor": "admin", "proposal_sha256": sha},
        "proposal_sha256": sha,
        "plan": {"selected": ["op-1"]},
        "tasks": {"op-1": task},
    }
    calls = []
    monkeypatch.setattr(
        strategic_workspace_bridge,
        "original",
        lambda *_args, **_kwargs: (SimpleNamespace(id="request-1"), {}, {"experiment": progress}),
    )
    monkeypatch.setattr(
        strategic_workspace_receipts,
        "validate_terminal",
        lambda *_args: calls.append("terminal"),
    )
    monkeypatch.setattr(
        review,
        "original_experiment_projection",
        lambda _row, release: frozen_experiment_projection(
            spec,
            progress,
            release,
            policy_digest="c" * 64,
        ),
    )

    def project():
        return review.bound_portfolio_experiment(None, "d1", proposal, state, item, now=now)

    result = project()
    assert result["status"] == "measured"
    assert result["proposal_sha256"] == sha and result["decision_id"] == "d1"
    assert result["snapshot_sha256"] == progress["final_snapshot_sha256"]
    assert calls == ["terminal"]
    task["worker_binding"]["owner_user_id"] = 8
    assert project()["status"] == "unknown"
    assert calls == ["terminal"]
    task["worker_binding"]["owner_user_id"] = 7
    task["execution_receipt"]["ok"] = False
    assert project()["status"] == "unknown"
    task["execution_receipt"]["ok"] = True
    state["plan"]["selected"] = []
    assert project()["status"] == "unknown"
