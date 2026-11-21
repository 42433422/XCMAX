"""Real workflow failures -> private SQL -> paired product validation -> Retort approval."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from modstore_server import capability_trainer as trainer
from modstore_server import workflow_nl_graph as generator
from modstore_server import workflow_nl_training as training
from modstore_server.models import (
    User,
    Workflow,
    WorkflowSandboxRun,
    get_session_factory,
)
from modstore_server.retort_experiment_surfaces import (
    WORKFLOW_NL_PROMPT_PATH,
    WORKFLOW_NL_RESOURCE,
)
from modstore_server.retort_training_candidates import training_plan
from modstore_server.workflow_sandbox_state import sandbox_status_for_workflow
from tests import test_retort_evolution as evolution_tests
from tests.promptfoo_local_only import local_only_environment

setup = evolution_tests.setup

GOOD_GRAPH = {
    "nodes": [
        {"temp_id": "s", "node_type": "start", "config": {}},
        {"temp_id": "e", "node_type": "end", "config": {}},
    ],
    "edges": [{"source_temp_id": "s", "target_temp_id": "e"}],
}


@pytest.fixture
def workflow_training(setup, tmp_path, monkeypatch):
    token = "workflow-training-" + "s" * 32
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256", hashlib.sha256(token.encode()).hexdigest()
    )
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    with get_session_factory()() as db:
        other, outsider = [User(username=uuid4().hex, password_hash="unused") for _ in range(2)]
        db.add_all([other, outsider])
        db.commit()
        cohort = [setup["user"].id, other.id]
        outsider_id = outsider.id
    templates_path = Path(os.environ["MODSTORE_RETORT_PROTOCOLS"])
    templates = json.loads(templates_path.read_bytes())
    templates["restore"]["training_candidate"] = {
        "surface": "workflow_nl_prompt",
        "resource_id": WORKFLOW_NL_RESOURCE,
        "owner_id": setup["user"].id,
        "goal": "Improve real failed workflow graph generation",
        "prompt_path": WORKFLOW_NL_PROMPT_PATH,
        "growthbook": {
            "project": "prod",
            "metric": "workflow-static-success",
            "minimum_users": 2,
            "stats_engine": "frequentist",
            "lifecycle": {
                "surface": "workflow_nl_prompt",
                "resource_id": WORKFLOW_NL_RESOURCE,
                "measurement_scope": "workflow_generation_static_validation",
                "cohort_user_ids": cohort,
                "datasource_id": "warehouse",
                "assignment_query_id": "real-workflow-exposures",
                "duration_hours": 24,
                "coverage": 0.1,
            },
        },
    }
    templates_path.write_text(json.dumps(templates), encoding="utf-8")
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda *_: ("test", "model", None),
    )
    monkeypatch.setattr(generator, "_catalog_lines", lambda *_: "")
    monkeypatch.setattr(generator, "_eskill_catalog_lines", lambda *_: "")
    run = {
        **setup,
        "cohort": cohort,
        "outsider": outsider_id,
        "messages": [],
        "workflows": [],
        "auth": {"Authorization": f"Bearer {token}"},
        "directory": tmp_path,
    }

    async def model(_db, _user, _provider, _model, messages, **_kwargs):
        run["messages"].append(messages)
        return run.get("response", {"ok": True, "content": "invalid generated JSON"})

    monkeypatch.setattr(generator, "chat_dispatch_via_session", model)

    async def generate(user_id=None):
        user_id = user_id or cohort[0]
        with get_session_factory()() as db:
            workflow = Workflow(user_id=user_id, name="Private original graph")
            db.add(workflow)
            db.commit()
            run["workflows"].append(workflow.id)
            return await generator.apply_nl_workflow_graph(
                db,
                db.get(User, user_id),
                workflow_id=workflow.id,
                brief=f"Case {len(run['workflows'])}: private quoted \"task\"\r\n" + "内容" * 1100,
                provider="test",
                model="model",
            )

    run["generate"] = generate
    run["source"] = Path(generator.__file__).read_bytes()

    def github(method, path, body=None):
        assert method == "GET"
        if path.endswith("/commits/main"):
            return {"sha": "a" * 40}
        return {"encoding": "base64", "content": base64.b64encode(run["source"]).decode()}

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    return run


def _clusters(run):
    response = run["client"].get(
        "/api/service/mac-control/training/failures?min_count=1", headers=run["auth"]
    )
    assert response.status_code == 200, response.text
    return [
        cluster
        for cluster in response.json()["clusters"]
        if cluster.get("surface") == "workflow_nl_prompt"
    ]


def _body(run):
    folder = run["directory"]
    clusters = _clusters(run)
    (folder / "clusters.json").write_text(json.dumps(clusters), encoding="utf-8")
    (folder / "source.py").write_bytes(run["source"])
    trainer.main(
        [
            "baseline",
            "--surface",
            "workflow_nl_prompt",
            "--source",
            str(folder / "source.py"),
            "--out",
            str(folder / "baseline.txt"),
        ]
    )
    (folder / "candidate.txt").write_text(
        generator.SYSTEM_PROMPT + "\n再次检查每个节点的必填配置。", encoding="utf-8"
    )
    trainer.main(
        [
            "prepare",
            "--surface",
            "workflow_nl_prompt",
            "--employee-id",
            WORKFLOW_NL_RESOURCE,
            "--clusters",
            str(folder / "clusters.json"),
            "--packs-dir",
            str(folder),
            "--corpus-dir",
            str(folder / "corpus"),
            "--out-dir",
            str(folder / "eval"),
            "--baseline",
            str(folder / "baseline.txt"),
            "--candidate-prompt",
            str(folder / "candidate.txt"),
        ]
    )
    folder = folder / "eval"
    bundle = json.loads((folder / "training-bundle.json").read_bytes())
    tests = json.loads((folder / "tests.json").read_bytes())
    results = []
    for index, case in enumerate(tests):
        for arm, output in enumerate(["invalid generated JSON", json.dumps(GOOD_GRAPH)]):
            grading = training.get_assert(output, {"vars": case["vars"]})
            results.append(
                {
                    "promptIdx": arm,
                    "testIdx": index,
                    "success": grading["pass"],
                    "failureReason": 0 if grading["pass"] else 1,
                    "gradingResult": grading,
                    "error": None if grading["pass"] else "Deterministic assertion failed",
                    "provider": {"id": bundle["provider_id"]},
                    "vars": case["vars"],
                    "response": {"output": output},
                }
            )
    result = {
        "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
        "results": {
            "prompts": [
                {"raw": (folder / bundle["files"][key]["name"]).read_bytes().decode()}
                for key in ("baseline", "candidate")
            ],
            "results": results,
        },
    }
    return {
        "request_key": "workflow-training-" + uuid4().hex,
        "surface": "workflow_nl_prompt",
        "resource_id": WORKFLOW_NL_RESOURCE,
        "source_sha": "a" * 40,
        "workflow_run_id": 77,
        "failure_run_ids": [
            sample["run_id"] for cluster in clusters for sample in cluster["samples"]
        ],
        "bundle_json": (folder / "training-bundle.json").read_bytes().decode(),
        "files": {
            key: (folder / entry["name"]).read_bytes().decode()
            for key, entry in bundle["files"].items()
        },
        "result_json": json.dumps(result),
    }


@pytest.mark.asyncio
async def test_actual_failures_reach_frozen_workflow_candidate_and_original_approval(
    workflow_training,
):
    run = workflow_training
    for user_id in run["cohort"]:
        assert (await run["generate"](user_id))["ok"] is False
    clusters = _clusters(run)
    assert len(clusters) == 1 and clusters[0]["count"] == 2
    assert {sample["task"] for sample in clusters[0]["samples"]} == {
        messages[1]["content"] for messages in run["messages"]
    }
    assert all(len(sample["task"]) > 2000 for sample in clusters[0]["samples"])
    with get_session_factory()() as db:
        rows = (
            db.query(WorkflowSandboxRun)
            .filter(WorkflowSandboxRun.workflow_id.in_(run["workflows"]))
            .all()
        )
        assert len(rows) == 2 and all(row.validate_only and not row.ok for row in rows)
        for row in rows:
            assert (
                sandbox_status_for_workflow(db, db.get(Workflow, row.workflow_id))["status"]
                == "untested"
            )
    body = _body(run)
    endpoint = "/api/service/mac-control/training/candidates"
    assert run["client"].post(endpoint, json=body).status_code == 401
    response = run["client"].post(endpoint, headers=run["auth"], json=body)
    assert response.status_code == 202, response.text
    request_id = response.json()["request_id"]
    assert (
        run["client"].post(endpoint, headers=run["auth"], json=body).json()["request_id"]
        == request_id
    )
    current = evolution_tests.read(run["client"], request_id)
    assert current["status"] == "awaiting_dispatch_approval"
    source = current["effects"]["training_candidate"]
    assert (
        source["prompt_symbol"] == "SYSTEM_PROMPT"
        and source["prompt_path"] == WORKFLOW_NL_PROMPT_PATH
    )
    assert source["growthbook"]["lifecycle"]["surface"] == "workflow_nl_prompt"
    assert source["private_evidence"]["result_json"] == body["result_json"]
    assert "private quoted" not in current["snapshot"]["plan"]["public_body"]
    assert json.loads(training_plan(request_id).splitlines()[-1])["symbol"] == "SYSTEM_PROMPT"
    assert not [call for call in run["calls"] if call[0] == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope", ["workflow_execution_terminal", "workflow_generation_static_validation"]
)
async def test_actual_runtime_failures_require_an_execution_experiment_and_never_claim_offline_business_success(
    workflow_training, monkeypatch, scope
):
    from modstore_server import workflow_event_runner
    from modstore_server.models import WorkflowExecution

    run = workflow_training
    path = Path(os.environ["MODSTORE_RETORT_PROTOCOLS"])
    templates = json.loads(path.read_bytes())
    policy = templates["restore"]["training_candidate"]["growthbook"]
    if scope == "workflow_execution_terminal":
        policy["metric"] = "workflow-run-success"
        policy["guardrails"] = [{"metric": "workflow-run-failure", "direction": "decrease"}]
        policy["lifecycle"].update(
            measurement_scope=scope,
            execution_outcomes={
                "source": "modstore_event_outbox_postgres_v1",
                "success_metric_id": policy["metric"],
                "failure_metric_id": "workflow-run-failure",
                "maximum_treatment_failures": 2,
            },
        )
        path.write_text(json.dumps(templates), encoding="utf-8")
    graph = deepcopy(GOOD_GRAPH)
    graph["edges"][0]["condition"] = "ready == True"
    run["response"] = {"ok": True, "content": json.dumps(graph)}
    monkeypatch.setattr(workflow_event_runner, "require_llm_credit", lambda *_: None)
    monkeypatch.setattr(workflow_event_runner, "consume_llm_credit", lambda *_: None)
    for user_id in run["cohort"]:
        generated = await run["generate"](user_id)
        assert generated["ok"] and generated["sandbox_ok"]
        with pytest.raises(ValueError, match="did not reach end"):
            workflow_event_runner.run_workflow_for_trigger(
                workflow_id=run["workflows"][-1],
                user_id=user_id,
                input_data={
                    "ready": False,
                    "private_original": "synthetic private customer context",
                },
            )
    clusters = _clusters(run)
    assert len(clusters) == 1 and clusters[0]["failure_reason"] == "workflow_execution_failed"
    for sample in clusters[0]["samples"]:
        feedback = sample["generation_context"]["execution_feedback"]
        assert feedback["input"]["ready"] is False
        assert sample["run_id"] == f"workflow-execution:{feedback['execution_id']}"
    body = _body(run)
    results = json.loads(body["result_json"])
    # Both prompts pass static validation. The executed failure supplies a
    # candidate hypothesis, not evidence that the business behavior improved.
    for row in results["results"]["results"]:
        row.update(
            success=True,
            failureReason=0,
            error=None,
            response={"output": json.dumps(GOOD_GRAPH)},
            gradingResult={
                "pass": True,
                "score": 1,
                "reason": "workflow_generation_static_validation",
            },
        )
    body["result_json"] = json.dumps(results)
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    if scope != "workflow_execution_terminal":
        assert response.status_code == 409
        assert "training_execution_experiment_required" in response.text
        return
    assert response.status_code == 202, response.text
    current = evolution_tests.read(run["client"], response.json()["request_id"])
    assert current["status"] == "awaiting_dispatch_approval"
    evidence = current["effects"]["training_candidate"]["growthbook"]["lifecycle"][
        "offline_evidence"
    ]
    assert evidence["improved"] is False and evidence["runtime_verified"] is False
    assert evidence["feedback_scope"] == scope
    assert "private customer" not in current["snapshot"]["plan"]["public_body"]
    with get_session_factory()() as db:
        receipts = (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.workflow_id.in_(run["workflows"]))
            .all()
        )
        assert len(receipts) == 2 and all(row.status == "failed" for row in receipts)
        for row in receipts:
            row.input_data = ""
        db.commit()
    assert _clusters(run) == []  # A failure label without original inputs is never trainable.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["task", "context", "forged_pass", "owner", "baseline", "validator"]
)
async def test_workflow_candidate_rechecks_original_input_owner_baseline_and_real_validation(
    workflow_training, mutation
):
    run = workflow_training
    await run["generate"]()
    body = _body(run)
    bundle, tests, result = (
        json.loads(body["bundle_json"]),
        json.loads(body["files"]["tests"]),
        json.loads(body["result_json"]),
    )
    if mutation in {"task", "context"}:
        if mutation == "task":
            tests[0]["vars"]["task"] = "An unrelated easier task"
            bundle["case_sha256"][0] = trainer._hash(tests[0]["vars"]["task"])
        else:
            tests[0]["vars"]["generation_context"]["target_employee_pack_id"] = "another-employee"
            bundle["case_context_sha256"][0] = training._digest(
                tests[0]["vars"]["generation_context"]
            )
        for row in result["results"]["results"]:
            row["vars"] = tests[0]["vars"]
        body["files"]["tests"] = json.dumps(tests)
        bundle["files"]["tests"]["sha256"] = trainer._hash(body["files"]["tests"])
    elif mutation == "forged_pass":
        result["results"]["results"][1]["response"]["output"] = "invalid generated JSON"
    elif mutation == "owner":
        with get_session_factory()() as db:
            db.get(Workflow, run["workflows"][0]).user_id = run["outsider"]
            db.commit()
    elif mutation == "baseline":
        run["source"] = run["source"].replace("你是 XCAGI".encode(), b"Changed baseline")
    else:
        bundle["validation_sha256"]["workflow_nl_apply.py"] = "0" * 64
    body.update(bundle_json=json.dumps(bundle), result_json=json.dumps(result))
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_commit_failure_keeps_private_input_without_becoming_prompt_training(
    workflow_training, monkeypatch
):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from modstore_server import retort_experiment_runtime as runtime
    from modstore_server.models import WorkflowNode

    run = workflow_training
    original = runtime.record_observation

    def arm_failure(assignment, **kwargs):
        original(assignment, **kwargs)
        kwargs["session"].info["fail_workflow_commit"] = True

    def fail_commit(session):
        if session.info.pop("fail_workflow_commit", False):
            raise OperationalError("commit workflow", {}, RuntimeError("commit unavailable"))

    monkeypatch.setattr(runtime, "record_observation", arm_failure)
    run["response"] = {"ok": True, "content": json.dumps(GOOD_GRAPH)}
    event.listen(Session, "before_commit", fail_commit)
    try:
        result = await run["generate"]()
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert result["ok"] is False and result["error_code"] == "workflow_commit_failed"
    with get_session_factory()() as db:
        workflow_id = run["workflows"][-1]
        assert db.query(WorkflowNode).filter_by(workflow_id=workflow_id).count() == 0
        row = db.query(WorkflowSandboxRun).filter_by(workflow_id=workflow_id).one()
        report = json.loads(row.report_json)
        assert not row.ok and report["training_eligible"] is False
        assert report["generation"]["task"] == run["messages"][-1][1]["content"]
    assert _clusters(run) == []

    monkeypatch.setattr(runtime, "record_observation", original)
    run["response"] = {"ok": True, "content": "invalid generated JSON"}
    assert (await run["generate"]())["ok"] is False
    clusters = _clusters(run)
    assert len(clusters) == 1 and clusters[0]["count"] == 1
    assert clusters[0]["samples"][0]["task"] == run["messages"][-1][1]["content"]


@pytest.mark.asyncio
async def test_graph_flush_failure_keeps_private_input_without_becoming_prompt_training(
    workflow_training,
):
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from modstore_server.models import WorkflowNode

    run = workflow_training
    run["response"] = {"ok": True, "content": json.dumps(GOOD_GRAPH)}

    def fail_graph_flush(session, _context, _instances):
        if any(isinstance(row, WorkflowNode) for row in session.new):
            raise OperationalError("insert workflow node", {}, RuntimeError("database unavailable"))

    event.listen(Session, "before_flush", fail_graph_flush)
    try:
        result = await run["generate"]()
    finally:
        event.remove(Session, "before_flush", fail_graph_flush)
    assert result["ok"] is False and result["error_code"] == "workflow_persistence_failed"
    with get_session_factory()() as db:
        workflow_id = run["workflows"][-1]
        assert db.query(WorkflowNode).filter_by(workflow_id=workflow_id).count() == 0
        row = db.query(WorkflowSandboxRun).filter_by(workflow_id=workflow_id).one()
        report = json.loads(row.report_json)
        assert not row.ok and report["training_eligible"] is False
        assert report["generation"]["task"] == run["messages"][-1][1]["content"]
    assert _clusters(run) == []

    run["response"] = {"ok": True, "content": "invalid generated JSON"}
    assert (await run["generate"]())["ok"] is False
    assert _clusters(run)[0]["count"] == 1


@pytest.mark.asyncio
async def test_only_actual_prompt_failures_in_configured_cohort_become_reproductions(
    workflow_training, monkeypatch
):
    run = workflow_training
    await run["generate"](run["outsider"])
    run["response"] = {"ok": False, "error": "provider unavailable", "status": 503}
    await run["generate"]()
    run["response"] = {"ok": True, "content": json.dumps(GOOD_GRAPH)}
    assert (await run["generate"]())["sandbox_ok"] is True
    assert _clusters(run) == []
    bad_graph = deepcopy(GOOD_GRAPH)
    bad_graph["nodes"].insert(1, {"temp_id": "api", "node_type": "openapi_operation", "config": {}})
    run["response"] = {"ok": True, "content": json.dumps(bad_graph)}
    result = await run["generate"]()
    assert result["ok"] is True and result["sandbox_ok"] is False
    clusters = _clusters(run)
    assert clusters[0]["samples"][0]["validation_errors"]
    context = clusters[0]["samples"][0]["generation_context"]
    assert (
        training.get_assert(json.dumps(bad_graph), {"vars": {"generation_context": context}})[
            "pass"
        ]
        is False
    )
    assert (
        training.get_assert(json.dumps(GOOD_GRAPH), {"vars": {"generation_context": context}})[
            "pass"
        ]
        is True
    )
    monkeypatch.setattr(generator, "SYSTEM_PROMPT", generator.SYSTEM_PROMPT + "new release")
    assert _clusters(run) == []  # Old-baseline failures cannot silently train the next release.


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("PROMPTFOO_CLI"), reason="pinned promptfoo CLI not configured"
)
async def test_pinned_promptfoo_chat_roles_and_python_assertion_reach_candidate(workflow_training):
    """Use the official CLI/provider and Python assertion; only model HTTP is a fixture."""
    run = workflow_training
    await run["generate"]()
    body = _body(run)
    folder = run["directory"] / "eval"
    bundle = json.loads(body["bundle_json"])
    config = json.loads(body["files"]["config"])
    received = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(request)
            messages = request["messages"]
            output = (
                json.dumps(GOOD_GRAPH)
                if messages[0]["content"].endswith("再次检查每个节点的必填配置。")
                else "invalid generated JSON"
            )
            content = json.dumps(
                {
                    "id": "local-contract",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "approved-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": output},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = config["providers"][0]
        provider["config"].update(
            apiBaseUrl=f"http://127.0.0.1:{server.server_port}/v1", apiKey="test-only"
        )
        config["defaultTest"]["options"]["provider"] = provider
        body["files"]["config"] = json.dumps(config)
        (folder / "promptfooconfig.yaml").write_text(body["files"]["config"], encoding="utf-8")
        bundle["files"]["config"]["sha256"] = trainer._hash(body["files"]["config"])
        with local_only_environment(
            folder,
            provider_url=provider["config"]["apiBaseUrl"],
            pythonpath=str(Path(generator.__file__).parents[1]),
        ) as (environment, denied_hosts):
            completed = await asyncio.to_thread(
                subprocess.run,
                [
                    os.environ["PROMPTFOO_CLI"],
                    "eval",
                    "-c",
                    str(folder / "promptfooconfig.yaml"),
                    "-o",
                    str(folder / "actual-result.json"),
                    "--no-cache",
                    "--no-share",
                    "--no-write",
                    "--max-concurrency",
                    "1",
                ],
                cwd=folder,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert completed.returncode in {0, 100}, completed.stdout + completed.stderr
    assert denied_hosts and set(denied_hosts) == {"r.promptfoo.app"}
    assert len(received) == 2
    assert all(
        [message["role"] for message in request["messages"]] == ["system", "user"]
        for request in received
    )
    assert {request["messages"][0]["content"] for request in received} == {
        generator.SYSTEM_PROMPT,
        generator.SYSTEM_PROMPT + "\n再次检查每个节点的必填配置。",
    }
    assert all(
        request["messages"][1]["content"] == run["messages"][0][1]["content"]
        for request in received
    )
    body.update(
        bundle_json=json.dumps(bundle),
        result_json=(folder / "actual-result.json").read_bytes().decode(),
    )
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 202, response.text
