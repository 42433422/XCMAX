"""Real LangGraph/GEPA and local subprocess evidence tests; no production claims."""

import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from retort_engine.evolution_contract import digest, freeze_request, verify_bundle
from retort_engine.evolution_evidence import run_comparison
from retort_engine.evolution_optimizer import CommandTrial, optimize_measured
from retort_engine.evolution_workflow import build_evolution_graph


@pytest.fixture
def protocol():
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[3] / "FHD/config/audit_benchmark_ssot.json"
        ).read_text()
    )
    return freeze_request(
        {
            "request_id": str(uuid4()),
            "title": "恢复后不重复派工",
            "goal": "验证持久流程的故障恢复",
            "repository": "example/product",
            "source_sha": "a" * 40,
            "criterion_ids": ["shared-engine-B2"],
            "checks": [
                {
                    "id": "replay",
                    "criterion_ids": ["shared-engine-B2"],
                    "argv": [sys.executable, "check.py"],
                    "files": {"check.py": "b" * 64},
                    "timeout_seconds": 10,
                }
            ],
        },
        catalog,
    )


class Ports:
    def __init__(self, *, outcome="checks_passed"):
        self.effects = []
        self.outcome = outcome
        self.execution_status = "waiting"
        self.delivery_status = "waiting_delivery"

    def plan(self, protocol):
        return {"public_body": protocol["goal"]}

    def optimize(self, protocol, plan):
        return {"status": "awaiting_measured_baseline"}

    def dispatch(self, state):
        self.effects.append("dispatch")
        return {"request_id": state["protocol"]["request_id"]}

    def collect(self, state):
        return {"status": self.execution_status}

    def verify(self, state):
        return {"status": self.outcome, "evidence_digest": "c" * 64}

    def remember(self, state):
        self.effects.append("knowledge")
        return {"recorded": True}

    def delivery(self, state):
        return {"status": self.delivery_status}


def invoke(path, ports, request_id, value):
    # Close and reopen the actual SQLite checkpointer on every process boundary.
    with SqliteSaver.from_conn_string(str(path)) as saver:
        graph = build_evolution_graph(ports, saver)
        config = {"configurable": {"thread_id": request_id}}
        graph.invoke(value, config, durability="sync")
        state = graph.get_state(config)
        return state.values, [i.value for t in state.tasks for i in t.interrupts]


def approved(pending, value=True):
    return Command(
        resume={"digest": pending[0]["digest"], "approved": value, "actor_id": 1}
    )


def test_actual_checkpoint_restart_preserves_approval_and_external_effects(
    tmp_path, protocol
):
    path = tmp_path / "flow.sqlite"
    ports = Ports()
    request_id = protocol["request_id"]
    state, pending = invoke(path, ports, request_id, {"protocol": protocol})
    assert state["status"] == "awaiting_dispatch_approval" and not ports.effects
    state, pending = invoke(path, ports, request_id, approved(pending))
    assert ports.effects == ["dispatch"] and pending[0]["kind"] == "execution"
    for _ in range(3):
        state, pending = invoke(
            path, ports, request_id, Command(resume={"fake_evidence": "success"})
        )
        assert state["status"] == "waiting_execution" and ports.effects == ["dispatch"]
    ports.execution_status = "completed"
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    assert state["status"] == "awaiting_acceptance" and ports.effects == ["dispatch"]
    state, pending = invoke(path, ports, request_id, approved(pending))
    assert state["status"] == "waiting_delivery" and pending[0]["kind"] == "delivery"
    for _ in range(2):
        state, pending = invoke(
            path, ports, request_id, Command(resume={"status": "deployment_verified"})
        )
        assert state["status"] == "waiting_delivery" and ports.effects == ["dispatch"]
    ports.delivery_status = "deployment_verified"
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    assert state["status"] == "completed" and ports.effects == ["dispatch", "knowledge"]
    state, pending = invoke(path, ports, request_id, None)
    assert not pending and ports.effects == ["dispatch", "knowledge"]


def test_rejected_customer_impact_waits_for_real_compensation_after_restart(
    tmp_path, protocol
):
    path = tmp_path / "feedback.sqlite"
    ports = Ports()
    ports.execution_status = "completed"
    ports.delivery_status = "deployment_verified"
    ports.impact = lambda _: {
        "status": "customer_impact_rejected",
        "reason": "negative_lift",
    }
    result = {"status": "waiting_recovery"}
    ports.recover = lambda _: dict(result)
    request_id = protocol["request_id"]
    state, pending = invoke(
        path, ports, request_id, {"protocol": protocol, "has_customer_feedback": True}
    )
    state, pending = invoke(path, ports, request_id, approved(pending))
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    state, pending = invoke(path, ports, request_id, approved(pending))
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    assert state["status"] == "waiting_recovery" and pending[0]["kind"] == "recovery"
    state, pending = invoke(
        path, ports, request_id, Command(resume={"status": "rollback_verified"})
    )
    assert state["status"] == "waiting_recovery" and "knowledge" not in ports.effects
    result["status"] = "rollback_verified"
    state, pending = invoke(path, ports, request_id, Command(resume=True))
    assert state["status"] == "customer_impact_rejected"
    assert state["recovery"]["status"] == "rollback_verified" and not pending
    assert "knowledge" not in ports.effects


@pytest.mark.parametrize(
    "phase", ["dispatch", "acceptance", "verification", "execution"]
)
def test_failed_or_rejected_work_never_becomes_verified_knowledge(
    tmp_path, protocol, phase
):
    path = tmp_path / "flow.sqlite"
    ports = Ports(outcome="failed" if phase == "verification" else "checks_passed")
    request_id = protocol["request_id"]
    state, pending = invoke(path, ports, request_id, {"protocol": protocol})
    state, pending = invoke(
        path, ports, request_id, approved(pending, phase != "dispatch")
    )
    if phase != "dispatch":
        ports.execution_status = "failed" if phase == "execution" else "completed"
        state, pending = invoke(path, ports, request_id, Command(resume=True))
    if phase == "acceptance":
        state, pending = invoke(path, ports, request_id, approved(pending, False))
    assert (
        state["status"] in {"failed", "rejected"} and "knowledge" not in ports.effects
    )
    assert not pending


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["criterion_ids"].append("fake-domain-B1"),
        lambda p: p["checks"].append(p["checks"][0]),
        lambda p: p["checks"][0].update(files={"../check.py": "b" * 64}),
        lambda p: p["checks"][0].update(criterion_ids=["shared-engine-B3"]),
    ],
)
def test_protocol_rejects_unmapped_or_ambiguous_checks(protocol, mutate):
    from retort_engine.evolution_contract import REQUEST_SCHEMA

    request = {k: v for k, v in protocol.items() if k in REQUEST_SCHEMA["properties"]}
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[3] / "FHD/config/audit_benchmark_ssot.json"
        ).read_text()
    )
    mutate(request)
    with pytest.raises(ValueError):
        freeze_request(request, catalog)


def git(path, *args):
    return subprocess.run(
        ["git", *args], cwd=path, check=True, text=True, capture_output=True
    ).stdout.strip()


@pytest.fixture
def comparison(tmp_path, protocol):
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-q")
    git(project, "config", "user.name", "Component Test")
    git(project, "config", "user.email", "components@example.invalid")
    script = b"import os\nfrom pathlib import Path\nassert 'FAKE_SECRET_TOKEN' not in os.environ\nassert Path('value').read_text() == 'fixed'\n"
    (project / "check.py").write_bytes(script)
    (project / "value").write_text("broken")
    git(project, "add", "check.py", "value")
    git(project, "commit", "-qm", "before")
    source = git(project, "rev-parse", "HEAD")
    (project / "value").write_text("fixed")
    git(project, "commit", "-qam", "after")
    target = git(project, "rev-parse", "HEAD")
    before = tmp_path / "before"
    git(project, "worktree", "add", "--detach", str(before), source)
    protocol.update(source_sha=source)
    protocol["checks"][0]["files"] = {"check.py": hashlib.sha256(script).hexdigest()}
    protocol["protocol_digest"] = digest(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    return protocol, before, project, tmp_path / "evidence", target


def test_comparison_uses_real_distinct_commits_and_keeps_domain_unrated(
    comparison, monkeypatch
):
    protocol, before, after, output, target = comparison
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "must-not-reach-tests")
    bundle = run_comparison(
        protocol,
        before=before,
        after=after,
        output=output,
        run_id="42",
        target_sha=target,
        isolation="local_test",
    )
    assert bundle["checks"][0]["before"]["returncode"] != 0
    result = verify_bundle(
        protocol, bundle, output, run_id="42", target_sha=target, isolation="local_test"
    )
    assert (
        result["status"] == "checks_passed"
        and result["score"] is None
        and result["domain_status"] == "UNRATED"
    )
    comparison_report = result["comparison"]
    assert comparison_report["schema"] == "retort.paired-checks/v1"
    assert comparison_report["baseline_sha"] == protocol["source_sha"]
    assert comparison_report["candidate_sha"] == target
    assert comparison_report["baseline_passed"] == 0
    assert comparison_report["candidate_passed"] == comparison_report["total"] == 1
    assert comparison_report["bundle_digest"] == result["evidence_digest"] == digest(bundle)
    pair = comparison_report["checks"][0]
    assert pair["baseline_returncode"] == bundle["checks"][0]["before"]["returncode"]
    assert pair["candidate_log_sha256"] == bundle["checks"][0]["after"]["log_sha256"]
    with pytest.raises(ValueError, match="isolation"):
        verify_bundle(protocol, bundle, output, run_id="42", target_sha=target)
    (output / "replay-after.log").write_text("forged")
    with pytest.raises(ValueError, match="hash"):
        verify_bundle(
            protocol,
            bundle,
            output,
            run_id="42",
            target_sha=target,
            isolation="local_test",
        )


def test_paired_checks_pass_is_not_an_improvement_score(comparison):
    protocol, before, after, output, target = comparison
    git(before, "checkout", "--detach", target)
    protocol["source_sha"] = target
    protocol["protocol_digest"] = digest(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    (after / "notes.txt").write_text("unrelated change")
    git(after, "add", "notes.txt")
    git(after, "commit", "-qm", "unrelated change")
    target = git(after, "rev-parse", "HEAD")
    bundle = run_comparison(
        protocol,
        before=before,
        after=after,
        output=output,
        run_id="42",
        target_sha=target,
        isolation="local_test",
    )
    report = verify_bundle(
        protocol, bundle, output, run_id="42", target_sha=target, isolation="local_test"
    )
    assert report["comparison"]["baseline_passed"] == 1
    assert report["comparison"]["candidate_passed"] == 1
    assert report["domain_status"] == "UNRATED"
    assert report["score"] is None

    (after / "value").write_text("regressed")
    git(after, "commit", "-qam", "regression")
    target = git(after, "rev-parse", "HEAD")
    bundle = run_comparison(
        protocol,
        before=before,
        after=after,
        output=output,
        run_id="43",
        target_sha=target,
        isolation="local_test",
    )
    with pytest.raises(ValueError, match="independent check failed"):
        verify_bundle(
            protocol, bundle, output, run_id="43", target_sha=target, isolation="local_test"
        )


def test_independent_checks_cannot_be_rewritten_by_candidate(comparison):
    protocol, before, after, output, _target = comparison
    (after / "check.py").write_text("pass\n")
    git(after, "commit", "-qam", "weaken evaluator")
    with pytest.raises(ValueError, match="test/data changed"):
        run_comparison(
            protocol,
            before=before,
            after=after,
            output=output,
            run_id="42",
            target_sha=git(after, "rev-parse", "HEAD"),
            isolation="local_test",
        )


@pytest.mark.parametrize(
    "holdout_expected, expected_status",
    [("fixed", "proposed"), ("original", "no_verified_improvement")],
)
def test_gepa_runs_real_trials_and_cannot_optimize_on_holdout(
    tmp_path, holdout_expected, expected_status
):
    evaluator = tmp_path / "evaluate.py"
    evaluator.write_text(
        "import json, sys\nx=json.load(sys.stdin)\nprint(json.dumps({'score':float(x['candidate']['plan']==x['task']['expected']), 'feedback':'compare expected result'}))\n"
    )
    trial = CommandTrial(
        {
            "project": str(tmp_path),
            "evidence_dir": str(tmp_path / "trials"),
            "check": {
                "id": "measure",
                "criterion_ids": ["shared-engine-B2"],
                "argv": [sys.executable, "evaluate.py"],
                "timeout_seconds": 10,
                "files": {
                    "evaluate.py": hashlib.sha256(evaluator.read_bytes()).hexdigest()
                },
            },
        },
        local_test=True,
    )
    seen = []

    def propose(candidate, reflective_dataset, components_to_update):
        seen.append(reflective_dataset)
        return {"plan": "fixed"}

    result = optimize_measured(
        seed={"plan": "original"},
        trainset=[{"id": "train", "expected": "fixed"}],
        valset=[{"id": "validation", "expected": "fixed"}],
        holdout=[{"id": "secret_holdout", "expected": holdout_expected}],
        trial=trial,
        max_metric_calls=6,
        proposer=propose,
        run_dir=tmp_path / "gepa-search",
    )
    assert (
        result["status"] == expected_status and result["automatically_applied"] is False
    )
    assert "secret_holdout" not in json.dumps(seen) and list(
        (tmp_path / "trials").glob("*/result.log")
    )


def test_gepa_rejects_leaking_holdout_ids():
    with pytest.raises(ValueError, match="separate"):
        optimize_measured(
            seed={"plan": "a"},
            trainset=[{"id": "same"}],
            valset=[{"id": "validation"}],
            holdout=[{"id": "same", "changed": True}],
            trial=lambda *_: {},
            max_metric_calls=6,
        )


def test_independent_worker_binds_management_protocol_and_exact_commits(
    protocol, tmp_path
):
    prepare = runpy.run_path(
        str(
            Path(__file__).resolve().parents[3]
            / "FHD/scripts/autonomy/prepare_retort_verification.py"
        )
    )["prepare"]
    protocol["container_image"] = "example/test@sha256:" + "c" * 64
    protocol["protocol_digest"] = digest(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    env = {
        "PARA_GITHUB_REQUEST_ID": protocol["request_id"],
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "42",
        "GITHUB_REPOSITORY": protocol["repository"],
        "GITHUB_SHA": protocol["source_sha"],
        "MODSTORE_PARA_DISPATCH_TOKEN": "test-only",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "RUNNER_TEMP": str(tmp_path),
    }
    state = {
        "request_id": protocol["request_id"],
        "run_id": 42,
        "repository": protocol["repository"],
        "finished": True,
        "conclusion": "success",
        "benchmark_protocol": protocol,
        "target_sha": "d" * 40,
    }

    def opener(request, timeout):
        assert request.headers["Authorization"] == "Bearer test-only" and timeout == 30
        return io.BytesIO(json.dumps(state).encode())

    prepare(env, opener)
    assert json.loads((tmp_path / "retort-protocol.json").read_text()) == protocol
    assert "target_sha=" + "d" * 40 in (tmp_path / "outputs").read_text()
    for key, invalid in (
        ("run_id", 43),
        ("repository", "other/repo"),
        ("finished", False),
        ("target_sha", protocol["source_sha"]),
        ("benchmark_protocol", {**protocol, "goal": "changed"}),
    ):
        original, state[key] = state[key], invalid
        with pytest.raises(ValueError):
            prepare(env, opener)
        state[key] = original
    with pytest.raises(ValueError):
        prepare({**env, "GITHUB_SHA": "e" * 40}, opener)


@pytest.mark.skipif(
    not os.environ.get("RETORT_TEST_CONTAINER_IMAGE"),
    reason="explicit isolated Docker test image required",
)
def test_real_docker_comparison_cannot_write_project_or_read_host_credentials(
    comparison, monkeypatch
):
    protocol, _before, project, output, _target = comparison
    script = b'test -z "$FAKE_SECRET_TOKEN" || exit 9\nif touch /workspace/forbidden 2>/dev/null; then exit 8; fi\ntest "$(cat value)" = fixed\n'
    (project / "check.sh").write_bytes(script)
    (project / "value").write_text("broken")
    git(project, "add", "check.sh", "value")
    git(project, "commit", "-qm", "container baseline")
    source = git(project, "rev-parse", "HEAD")
    (project / "value").write_text("fixed")
    git(project, "commit", "-qam", "container candidate")
    target = git(project, "rev-parse", "HEAD")
    before = project.parent / "container-before"
    git(project, "worktree", "add", "--detach", str(before), source)
    protocol.update(
        source_sha=source, container_image=os.environ["RETORT_TEST_CONTAINER_IMAGE"]
    )
    protocol["checks"][0].update(
        argv=["sh", "check.sh"],
        files={"check.sh": hashlib.sha256(script).hexdigest()},
        timeout_seconds=30,
    )
    protocol["protocol_digest"] = digest(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "test-only-secret")
    bundle = run_comparison(
        protocol,
        before=before,
        after=project,
        output=output,
        run_id="42",
        target_sha=target,
    )
    assert bundle["checks"][0]["before"]["returncode"] == 1
    assert (
        verify_bundle(protocol, bundle, output, run_id="42", target_sha=target)[
            "status"
        ]
        == "checks_passed"
    )
    assert not (project / "forbidden").exists()


@pytest.mark.skipif(
    not os.environ.get("RETORT_TEST_POSTGRES_DSN"),
    reason="isolated PostgreSQL required",
)
def test_official_postgres_checkpointer_restores_human_interrupt(protocol):
    from langgraph.checkpoint.postgres import PostgresSaver

    dsn = os.environ["RETORT_TEST_POSTGRES_DSN"]
    config = {"configurable": {"thread_id": protocol["request_id"]}}
    ports = Ports()
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        graph = build_evolution_graph(ports, saver)
        graph.invoke({"protocol": protocol}, config, durability="sync")
        pending = [i.value for t in graph.get_state(config).tasks for i in t.interrupts]
    with PostgresSaver.from_conn_string(dsn) as saver:
        graph = build_evolution_graph(ports, saver)
        graph.invoke(approved(pending), config, durability="sync")
        assert graph.get_state(config).values["status"] == "waiting_execution"
    assert ports.effects == ["dispatch"]
