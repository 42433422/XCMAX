"""Native DutyGraph + original CR Git staging + independent source readback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest


def _verified(output):
    return {
        "result": {
            "outputs": [output],
            "verification": {
                "passed": True,
                "checks": [{"name": "native_effect", "ok": True}],
                "ok_count": 1,
                "total_count": 1,
                "failed_count": 0,
            },
            "path_guard": {"ok": True, "checked": True, "violations": []},
        }
    }


@pytest.fixture
def native_graph(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server import admin_duty_graph_api as duty
    from modstore_server import incident_bus, models
    from modstore_server import production_line_employee as consumer
    from modstore_server import production_line_sources as sources
    from modstore_server.employee_change_request_submission import defer_write_as_change_request

    root = tmp_path / "source"
    root.mkdir()
    (root / "site.txt").write_text("original content\n")

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Local fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", "site.txt")
    git("commit", "-m", "fixture baseline")
    sha = git("rev-parse", "HEAD")
    monkeypatch.setenv("MODSTORE_GIT_REPO_ROOT", str(root))
    monkeypatch.setenv("MODSTORE_CR_GIT_BRANCH_ENABLED", "1")
    monkeypatch.setenv("MODSTORE_CR_GH_PR_ENABLED", "0")
    engine = create_engine("sqlite:///" + str(tmp_path / "native.db"))
    for cls in (
        models.User,
        models.EmployeeExecutionMetric,
        models.DutyGraphRun,
        models.DutyGraphRunNode,
        models.EmployeeChangeRequest,
        models.OpsActionAuditLog,
        models.PendingBriefTask,
    ):
        cls.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    for module in (models, duty, consumer):
        monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    with factory() as db:
        db.add(
            models.User(
                id=1,
                username="native-admin",
                password_hash="test-only",
                is_admin=True,
                account_state="active",
            )
        )
        db.add(
            models.User(
                id=2,
                username="native-other",
                password_hash="test-only",
                is_admin=False,
                account_state="active",
            )
        )
        db.commit()
    state = {
        "consumer": consumer,
        "factory": factory,
        "models": models,
        "root": root,
        "git": git,
        "context": {"source_sha": sha, "created_by_user_id": 1, "project_root": str(root)},
        "calls": [],
        "published": True,
        "mode": "change",
        "content": "actual employee output\n",
        "requests": [],
    }
    monkeypatch.setattr(
        duty,
        "list_employees_exec",
        lambda: [
            {"id": eid}
            for eid in (
                "site-content-editor",
                "fhd-core-maintainer",
                "daily-orchestrator",
                "log-monitor-incident",
                "deploy-release-officer",
                "push-update-context-officer",
            )
        ],
    )
    monkeypatch.setattr(duty, "_load_manifest_for_employee", lambda *a, **k: {})
    monkeypatch.setattr(duty, "_build_provider_status_map", lambda *a: {})
    monkeypatch.setattr(duty, "fernet_configured", lambda: True)
    monkeypatch.setattr(
        duty,
        "_analyze_employee_capability",
        lambda *a, **k: {"executable": True, "risk": {"high_risk": False}},
    )
    monkeypatch.setattr(incident_bus, "publish", lambda *a, **k: None)

    def execute_task(*, employee_id, task, input_data, user_id, **kw):
        state["calls"].append((employee_id, input_data))
        if state["mode"] == "text":
            return {"ok": True, "summary": "done"}
        if state["mode"] == "failed":
            return {"ok": False, "error": "native worker rejected"}
        if state["mode"] == "no_effect":
            return _verified({"handler": "agent", "ok": True, "summary": "done"})
        if state["mode"] == "audit":
            with factory() as db:
                row = models.OpsActionAuditLog(
                    user_id=user_id,
                    employee_id=employee_id,
                    handler="shell_exec",
                    command_id="read-pytest-lastfailed",
                    exit_code=0,
                    stdout_excerpt='{"tests/native.py::test_regression": true}',
                    dry_run=False,
                    approval_required=False,
                )
                db.add(row)
                db.commit()
                aid = row.id
            return _verified(
                {
                    "handler": "shell_exec",
                    "ok": True,
                    "audit_log_id": aid,
                    "command_id": "read-pytest-lastfailed",
                }
            )
        cid = defer_write_as_change_request(employee_id, str(root), "site.txt", state["content"])
        return _verified({"handler": "agent", "ok": True, "change_request_ids": [cid]})

    state["execute_task"] = execute_task
    monkeypatch.setattr(
        duty, "get_default_employee_client", lambda: SimpleNamespace(execute_task=execute_task)
    )

    def github(method, path, body=None):
        assert method == "GET"
        state["requests"].append(path)
        repo = "42433422/XCMAX"
        if "/commits/" in path and path.endswith("/pulls"):
            candidate = path.split("/commits/")[1].split("/")[0]
            with factory() as db:
                branch = (
                    db.query(models.EmployeeChangeRequest)
                    .filter_by(staged_commit_sha=candidate)
                    .one()
                    .git_branch
                )
            return [
                {
                    "number": 9,
                    "merged_at": "2026-11-21T10:00:00Z" if state["published"] else None,
                    "head": {"sha": candidate, "ref": branch, "repo": {"full_name": repo}},
                    "base": {"ref": "main", "repo": {"full_name": repo}},
                    "merge_commit_sha": candidate,
                }
            ]
        if "/contents/" in path:
            name, ref = path.split("/contents/")[1].split("?ref=")
            data = subprocess.run(
                ["git", "show", f"{ref}:{name}"], cwd=root, capture_output=True, check=True
            ).stdout
            if state.get("tampered_remote"):
                data = b"different merged bytes"
            return {
                "type": "file",
                "path": name,
                "size": len(data),
                "encoding": "base64",
                "content": base64.b64encode(data).decode(),
                "sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            }
        if "/compare/" in path:
            return {"status": "identical", "merge_base_commit": {"sha": path.split("...")[1]}}
        if "/workflows/" in path:
            target = path.split("head_sha=")[1].split("&")[0]
            state["ci_sha"] = target
            return {"total_count": 1, "workflow_runs": [{"id": 42}]}
        if path.endswith("/runs/42"):
            return {
                "id": 42,
                "head_sha": state["ci_sha"],
                "head_branch": "main",
                "path": sources._CI_PATH,
                "repository": {"full_name": repo},
                "head_repository": {"full_name": repo},
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
        if "/attempts/" in path:
            return {
                "total_count": 2,
                "jobs": [
                    {
                        "id": i + 80,
                        "run_id": 42,
                        "name": name,
                        "status": "completed",
                        "conclusion": "success",
                    }
                    for i, name in enumerate(("security-scan", "container-scan"))
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr(consumer, "github", github)
    monkeypatch.setattr(sources, "github", github)
    yield state
    engine.dispose()


@pytest.mark.parametrize(
    ("step", "employee"),
    [("P1", "site-content-editor"), ("P2", "fhd-core-maintainer"), ("P8", "daily-orchestrator")],
)
def test_real_native_graph_cr_git_and_merged_bytes_are_consumed_once(native_graph, step, employee):
    state = native_graph
    first = state["consumer"].dispatch_employee_step(
        step, employee, "original task", state["context"]
    )
    assert first["result"]["status"] == "completed", first
    second = state["consumer"].dispatch_employee_step(
        step, employee, "original task", state["context"]
    )
    assert second == first
    assert len(state["calls"]) == 1
    assert first["source_sha"] != state["context"]["source_sha"]
    evidence = first["result"]["evidence"]
    assert (
        evidence["artifacts"][0]["sha256"] == hashlib.sha256(state["content"].encode()).hexdigest()
    )
    with state["factory"]() as db:
        run = db.query(state["models"].DutyGraphRun).one()
        node = db.query(state["models"].DutyGraphRunNode).one()
        cr = db.query(state["models"].EmployeeChangeRequest).one()
        assert json.loads(cr.diff_blob)["source_execution"] == {
            "duty_graph_run_id": run.id,
            "duty_graph_node_id": node.id,
            "employee_id": employee,
            "user_id": 1,
        }
        assert db.query(state["models"].PendingBriefTask).one().status == "done"
    assert (state["root"] / "site.txt").read_text() == "original content\n"


@pytest.mark.parametrize("mode", ["text", "no_effect", "failed"])
def test_completed_sql_or_text_does_not_substitute_for_original_effect(native_graph, mode):
    state = native_graph
    state["mode"] = mode
    first = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert first["result"]["status"] in {"waiting_evidence", "failed"}
    state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert len(state["calls"]) == 1


def test_original_pending_pr_resumes_by_readback_without_recreating_task(native_graph):
    state = native_graph
    state["published"] = False
    first = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert first["result"]["status"] == "waiting_evidence"
    assert first["result"]["reason"] == "original_change_not_merged_to_main"
    state["published"] = True
    second = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert second["result"]["status"] == "completed"
    assert len(state["calls"]) == 1


def test_concurrent_same_native_request_dispatches_one_graph(native_graph):
    from concurrent.futures import ThreadPoolExecutor

    state = native_graph

    def dispatch():
        return state["consumer"].dispatch_employee_step(
            "P2", "fhd-core-maintainer", "one concurrent task", state["context"]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatch(), range(2)))
    assert any(row["result"]["status"] == "completed" for row in results), results
    assert dispatch()["result"]["status"] == "completed"
    assert len(state["calls"]) == 1
    with state["factory"]() as db:
        assert db.query(state["models"].PendingBriefTask).count() == 1
        assert db.query(state["models"].DutyGraphRun).count() == 1


def test_lost_dispatch_response_recovers_original_graph_without_replay(native_graph, monkeypatch):
    from modstore_server import employee_orchestrator

    state = native_graph
    original = employee_orchestrator.plan_and_dispatch

    def lose_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("response lost after native commit")

    monkeypatch.setattr(employee_orchestrator, "plan_and_dispatch", lose_response)
    first = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "one uncertain task", state["context"]
    )
    assert first["result"]["status"] == "waiting_evidence"
    second = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "one uncertain task", state["context"]
    )
    assert second["result"]["status"] == "completed", second
    assert len(state["calls"]) == 1


def test_same_employee_same_base_concurrent_cr_cannot_complete_another_graph(
    native_graph, monkeypatch
):
    from modstore_server import admin_duty_graph_api as duty

    state = native_graph
    original = state["execute_task"]

    def borrow(**kwargs):
        if kwargs["task"] == "request-A":
            other = duty.execute_duty_graph_programmatic(
                target_employee_id=kwargs["employee_id"],
                task="request-B",
                input_data=kwargs["input_data"],
                created_by_user_id=kwargs["user_id"],
                include_dependencies=True,
            )
            return other["nodes"][0]["result"]
        return original(**kwargs)

    monkeypatch.setattr(
        duty, "get_default_employee_client", lambda: SimpleNamespace(execute_task=borrow)
    )
    result = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "request-A", state["context"]
    )
    assert result["result"]["status"] == "waiting_evidence", result
    assert result["result"]["reason"] == "change_request_execution_mismatch"
    with state["factory"]() as db:
        assert db.query(state["models"].DutyGraphRun).count() == 2
        assert db.query(state["models"].EmployeeChangeRequest).count() == 1


def test_original_async_runner_preserves_native_change_request_identity(native_graph, monkeypatch):
    from modstore_server import admin_duty_graph_api as duty
    from modstore_server.runtime_async import run_coro_sync

    state = native_graph
    original = state["execute_task"]

    def execute(**kwargs):
        async def produce():
            return original(**kwargs)

        return run_coro_sync(produce())

    monkeypatch.setattr(
        duty, "get_default_employee_client", lambda: SimpleNamespace(execute_task=execute)
    )

    async def in_running_loop():
        return state["consumer"].dispatch_employee_step(
            "P2", "fhd-core-maintainer", "async original writer", state["context"]
        )

    result = asyncio.run(in_running_loop())
    assert result["result"]["status"] == "completed", result


@pytest.mark.parametrize("fail_outer", [False, True])
def test_nested_native_graph_restores_producer_identity_even_after_failure(
    native_graph, monkeypatch, fail_outer
):
    from modstore_server import admin_duty_graph_api as duty
    from modstore_server.employee_change_request_submission import defer_write_as_change_request

    state = native_graph
    original = state["execute_task"]

    def execute(**kwargs):
        if kwargs["task"] == "outer":
            duty.execute_duty_graph_programmatic(
                target_employee_id=kwargs["employee_id"],
                task="inner",
                input_data=kwargs["input_data"],
                created_by_user_id=kwargs["user_id"],
            )
            if fail_outer:
                raise OSError("original worker failed")
        return original(**kwargs)

    monkeypatch.setattr(
        duty, "get_default_employee_client", lambda: SimpleNamespace(execute_task=execute)
    )
    result = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "outer", state["context"]
    )
    assert result["result"]["status"] == ("failed" if fail_outer else "completed"), result
    cid = defer_write_as_change_request(
        "fhd-core-maintainer", str(state["root"]), "site.txt", "outside native graph\n"
    )
    with state["factory"]() as db:
        assert "source_execution" not in json.loads(
            db.get(state["models"].EmployeeChangeRequest, cid).diff_blob
        )


def test_changed_source_drops_previous_ci_run_identity(native_graph):
    state = native_graph
    result = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "native change", {**state["context"], "ci_run_id": 12}
    )
    assert result["result"]["status"] == "completed", result
    assert result["source_sha"] != state["context"]["source_sha"]
    assert result["ci_run_id"] is None


@pytest.mark.parametrize(
    "corruption",
    [
        "owner",
        "request",
        "old_cr",
        "other_source",
        "merged_bytes",
        "node_verification",
        "cr_execution",
        "cr_execution_bool",
    ],
)
def test_native_effect_is_bound_to_original_execution(native_graph, corruption):
    state = native_graph
    first = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert first["result"]["status"] == "completed", first
    with state["factory"]() as db:
        run = db.query(state["models"].DutyGraphRun).one()
        node = db.query(state["models"].DutyGraphRunNode).one()
        cr = db.query(state["models"].EmployeeChangeRequest).one()
        if corruption == "owner":
            run.created_by_user_id = 2
        elif corruption == "request":
            value = json.loads(run.input_data_json)
            value["pending_brief_task_id"] += 1
            run.input_data_json = json.dumps(value)
        elif corruption == "old_cr":
            cr.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        elif corruption == "other_source":
            cr.base_commit_sha = "b" * 40
        elif corruption == "node_verification":
            value = json.loads(node.result_json)
            value["result"]["verification"]["checks"] = []
            node.result_json = json.dumps(value)
        elif corruption in {"cr_execution", "cr_execution_bool"}:
            value = json.loads(cr.diff_blob)
            if corruption == "cr_execution":
                value.pop("source_execution")
            else:
                value["source_execution"]["duty_graph_node_id"] = True
            cr.diff_blob = json.dumps(value)
        else:
            state["tampered_remote"] = True
        db.commit()
    observed = state["consumer"].dispatch_employee_step(
        "P2", "fhd-core-maintainer", "original task", state["context"]
    )
    assert observed["result"]["status"] == "waiting_evidence"
    assert len(state["calls"]) == 1


def test_original_monitoring_audit_is_freshly_checked(native_graph):
    state = native_graph
    state["mode"] = "audit"
    observed = state["consumer"].dispatch_employee_step(
        "P7", "log-monitor-incident", "original monitor", state["context"]
    )
    assert observed["result"]["status"] == "completed", observed
    with state["factory"]() as db:
        db.query(state["models"].OpsActionAuditLog).one().dry_run = True
        db.commit()
    observed = state["consumer"].dispatch_employee_step(
        "P7", "log-monitor-incident", "original monitor", state["context"]
    )
    assert observed["result"]["status"] == "waiting_evidence"
    assert len(state["calls"]) == 1


@pytest.fixture
def published_release(native_graph, tmp_path, monkeypatch):
    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from modstore_server import customer_issue_release_provenance as provenance

    state = native_graph
    sha = state["context"]["source_sha"]
    state["context"]["self_maintenance_run_id"] = "native-maintenance-run"
    common = {
        "repository": "42433422/XCMAX",
        "workflow": "fhd-deploy.yml",
        "ref": "main",
        "environment": "production",
        "merge_sha": sha,
        "action_id": f"release:{sha}",
        "run_id": "native-maintenance-run",
        "workflow_run_id": "98",
        "controller_sha": "c" * 40,
    }
    rows = [
        {**common, "event": "deploy_dispatch_bound"},
        {**common, "event": "deploy_dispatch", "ok": True, "status": "accepted"},
        {
            **common,
            "event": "post_deploy_verified",
            "ok": True,
            "status": "verified",
            "identity_verified": True,
            "git_sha": sha,
            "artifact_sha256": "d" * 64,
            "image_digest": "",
        },
    ]
    ledger = tmp_path / "original-deployment.jsonl"
    ledger.write_text("\n".join(json.dumps(row) for row in rows))
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_LEDGER", str(ledger))
    state["ledger"] = ledger
    state["health_sha"] = sha
    state["installer"] = b"original signed publisher bytes"
    state["served_installer"] = state["installer"]
    state["transport"] = []
    key = Ed25519PrivateKey.generate()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    monkeypatch.setattr(provenance, "UPDATE_PUBLIC_KEY", public)
    signed = f"buildSha: {sha}\nproductVersion: 1.0.0.7\nreleaseId: xcagi-1.0.0.7-{sha}\nfiles:\n  - url: original-installer.bin\n    size: {len(state['installer'])}\n    sha512: {base64.b64encode(hashlib.sha512(state['installer']).digest()).decode()}"
    state["feed"] = (
        signed + "\nsignature: ed25519:" + base64.b64encode(key.sign(signed.encode())).decode()
    )
    monkeypatch.setattr(provenance, "_fetch_text", lambda url: state["feed"])

    def respond(request):
        state["transport"].append(str(request.url))
        assert request.method == "GET"
        if request.url.path.endswith("/api/health"):
            return httpx.Response(
                200, json={"build": {"git_sha": state["health_sha"], "artifact_sha256": "d" * 64}}
            )
        if request.url.path.endswith("/fhd-manifest.json"):
            return httpx.Response(200, json={"git_sha": sha, "sha256": "d" * 64})
        if request.url.path.endswith("original-installer.bin"):
            return httpx.Response(200, content=state["served_installer"])
        raise AssertionError(request.url)

    client = httpx.Client
    monkeypatch.setattr(
        state["consumer"].httpx,
        "Client",
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw),
    )
    return state


@pytest.mark.parametrize("step", ["P5", "P6"])
def test_original_publisher_is_observed_without_redeploy_or_resend(published_release, step):
    from modstore_server import production_line_orchestrator as pipeline

    state = published_release
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    result = asyncio.run(orch.run_step(step, state["context"]))
    assert result.data["result"]["status"] == "completed", result
    assert result.data["result"]["evidence"]["publication_verified"] is True
    assert not state["calls"]
    assert state["transport"]


def test_deployment_approval_rechecks_health_without_dispatching(published_release):
    from modstore_server import production_line_orchestrator as pipeline

    state = published_release
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    first = asyncio.run(orch.run_step("P5", state["context"]))
    assert first.status == pipeline.StepStatus.AWAITING_APPROVAL
    state["health_sha"] = "f" * 40
    second = asyncio.run(orch.approve_step("P5", admin_user_id=1))
    assert second.status == pipeline.StepStatus.WAITING_EVIDENCE
    assert not state["calls"]
    with state["factory"]() as db:
        assert db.query(state["models"].PendingBriefTask).count() == 0


def test_daily_source_resolves_one_original_deployment_without_new_run_id(published_release):
    state = published_release
    state["context"].pop("self_maintenance_run_id")
    result = state["consumer"].observe_published_step("P5", state["context"])
    assert result["result"]["status"] == "completed", result
    assert result["result"]["evidence"]["deployment_run_id"] == "native-maintenance-run"
    assert not state["calls"]


def test_daily_source_does_not_guess_between_deployment_origins(published_release):
    state = published_release
    state["context"].pop("self_maintenance_run_id")
    rows = [json.loads(line) for line in state["ledger"].read_text().splitlines()]
    rows += [{**row, "run_id": "different-original-run"} for row in list(rows)]
    state["ledger"].write_text("\n".join(json.dumps(row) for row in rows))
    result = state["consumer"].observe_published_step("P5", state["context"])
    assert result["result"]["status"] == "waiting_evidence"
    assert not state["transport"]


def test_automatic_daily_chain_cannot_approve_administrator_gate(native_graph, monkeypatch):
    from modstore_server import digest_daily_line_chain as daily
    from modstore_server import production_line_orchestrator as pipeline

    state = native_graph
    orch = pipeline.ProductionLineOrchestrator()
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_AUTO_APPROVE_PIPELINE", "1")
    monkeypatch.setattr(pipeline, "get_production_line_orchestrator", lambda: orch)
    result = asyncio.run(
        daily._run_pipeline_with_optional_auto_approve(["P2", "P3"], state["context"])
    )
    assert result["paused"] is True and result["paused_at_step"] == "P2"
    assert result["status"] == "awaiting_approval"
    assert len(state["calls"]) == 1
    assert (
        asyncio.run(orch.approve_step("P2", admin_user_id=0)).status == pipeline.StepStatus.FAILED
    )


def test_daily_ci_approval_keeps_one_owner_for_following_steps(monkeypatch):
    from modstore_server import digest_daily_line_chain as daily
    from modstore_server import production_line_orchestrator as pipeline

    orch = pipeline.ProductionLineOrchestrator()
    calls = []

    async def execute(step, context):
        calls.append((step.step_id, bool(context.get("_production_read_only"))))
        return {"step": step.step_id, "result": {"ok": True, "status": "completed"}}

    monkeypatch.setattr(orch, "_execute_step", execute)
    monkeypatch.setenv("MODSTORE_RELEASE_TRAIN_AUTO_APPROVE_PIPELINE", "1")
    monkeypatch.setattr(pipeline, "get_production_line_orchestrator", lambda: orch)
    result = asyncio.run(daily._run_pipeline_with_optional_auto_approve(["P3", "P4"], {}))
    assert result["ok"] is True and result["paused"] is False
    assert calls == [("P3", False), ("P3", True), ("P4", False)]


@pytest.mark.parametrize("corruption", ["signature", "artifact_bytes", "foreign_host"])
def test_signed_update_metadata_alone_cannot_verify_another_or_missing_artifact(
    published_release, corruption
):
    state = published_release
    if corruption == "signature":
        state["feed"] += "forged"
    elif corruption == "artifact_bytes":
        state["served_installer"] = b"wrong package"
    else:
        # Even an altered URL cannot pass the original pinned signature check.
        state["feed"] = state["feed"].replace(
            "original-installer.bin", "https://unrelated.invalid/file"
        )
    result = state["consumer"].observe_published_step("P6", state["context"])
    assert result["result"]["status"] == "waiting_evidence"


def test_callback_failure_does_not_repeat_completed_business_effect(monkeypatch):
    from dataclasses import replace

    from modstore_server import production_line_orchestrator as pipeline

    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    monkeypatch.setattr(
        pipeline,
        "ALL_STEPS",
        [replace(orch.get_step("P10"), approval_gate=pipeline.ApprovalGate.NONE)],
    )
    calls = []

    async def execute(step, context):
        calls.append(step.step_id)
        return {"step": step.step_id, "result": {"ok": True}}

    monkeypatch.setattr(orch, "_execute_step", execute)

    def failed_callback(**kw):
        raise OSError("notification failed after execution")

    orch.register_callback("step_completed", failed_callback)
    with pytest.raises(OSError):
        asyncio.run(orch.run_step("P10", {}))
    assert calls == ["P10"]


def test_dispatch_claim_without_original_task_cannot_complete(monkeypatch):
    from modstore_server import employee_orchestrator
    from modstore_server import production_line_orchestrator as pipeline

    monkeypatch.setattr(employee_orchestrator, "plan_and_dispatch", lambda *a, **k: {"ok": True})
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    result = asyncio.run(orch.run_step("P1", {"created_by_user_id": 1}))
    assert result.status not in {
        pipeline.StepStatus.COMPLETED,
        pipeline.StepStatus.AWAITING_APPROVAL,
    }


def test_craft_without_original_customer_graph_cannot_dispatch_unrelated_host(monkeypatch):
    from modstore_server import craft_executor, employee_orchestrator
    from modstore_server import production_line_orchestrator as pipeline

    calls = []

    async def fail(step, **kwargs):
        calls.append(step)
        return {"ok": False, "status": "fail", "error": "original craft rejected"}

    monkeypatch.setattr(craft_executor, "dispatch_craft_step", fail)
    monkeypatch.setattr(
        employee_orchestrator, "plan_and_dispatch", lambda *a, **k: calls.append("host")
    )
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    result = asyncio.run(orch.run_step("P2", {"craft_step_ids": ["spec", "generate"]}))
    assert result.status == pipeline.StepStatus.WAITING_EVIDENCE
    assert calls == []
