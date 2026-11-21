"""Exact private RAG cases -> official paired evaluator -> original Retort approvals."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest

from modstore_server import capability_trainer as trainer
from modstore_server import rag_prompt_feedback as feedback
from modstore_server import rag_service
from modstore_server.retort_experiment_surfaces import RAG_PROMPT_PATH
from modstore_server.retort_training_candidates import training_plan
from tests import test_retort_evolution as evolution
from tests import test_retort_rag_consumer as consumer
from tests.promptfoo_local_only import local_only_environment
from tests.test_capability_trainer import corpus_key as corpus_key

setup = evolution.setup
rag_call = consumer.rag_call


@pytest.fixture
def rag_training(setup, rag_call, tmp_path, monkeypatch, corpus_key):
    token = "rag-training-" + "s" * 32
    monkeypatch.setenv(
        "MODSTORE_PARA_DISPATCH_TOKEN_SHA256", hashlib.sha256(token.encode()).hexdigest()
    )
    monkeypatch.setenv("XCAGI_LLM_MODEL", "approved-model")
    monkeypatch.setenv("XCAGI_LLM_BASE_URL", "https://platform.test/v1")
    spec = consumer.rag_spec(
        {
            "project": "prod",
            "metric": "success",
            "minimum_users": 2,
            "stats_engine": "frequentist",
            "lifecycle": {
                "cohort_user_ids": [setup["user"].id, rag_call["user"]],
                "datasource_id": "warehouse",
                "assignment_query_id": "real-rag-exposures",
                "duration_hours": 24,
                "coverage": 0.1,
            },
        },
        rag_service.RAG_SYSTEM_PROMPT,
    )
    template = {
        "name": "RAG 引用完整性",
        "criterion_ids": ["shared-engine-B2"],
        "container_image": "example/test@sha256:" + "c" * 64,
        "checks": [
            {
                "id": "restore",
                "criterion_ids": ["shared-engine-B2"],
                "files": {"check.py": "b" * 64},
                "argv": ["python", "check.py"],
                "timeout_seconds": 10,
            }
        ],
        "training_candidate": {
            "surface": consumer.SURFACE,
            "resource_id": consumer.RESOURCE,
            "owner_id": setup["user"].id,
            "goal": "Improve citation integrity, not business success",
            "prompt_path": RAG_PROMPT_PATH,
            "growthbook": spec,
        },
    }
    rag_call["template_path"].write_text(json.dumps({"rag": template}))
    source = Path(rag_service.__file__).read_bytes()

    def github(method, path, body=None):
        assert method == "GET"
        if path.endswith("/commits/main"):
            return {"sha": "a" * 40}
        return {"encoding": "base64", "content": base64.b64encode(source).decode()}

    monkeypatch.setattr("modstore_server.customer_ticket_github.github", github)
    return {
        **setup,
        "rag": rag_call,
        "directory": tmp_path,
        "source": source,
        "auth": {"Authorization": f"Bearer {token}"},
    }


def _clusters(run):
    response = run["client"].get(
        "/api/service/mac-control/training/failures?min_count=1", headers=run["auth"]
    )
    assert response.status_code == 200, response.text
    return [c for c in response.json()["clusters"] if c.get("surface") == consumer.SURFACE]


def _body(run, *, tamper_context=False):
    folder = run["directory"]
    clusters = _clusters(run)
    assert clusters and clusters[0]["samples"][0]["generation_context"]
    if tamper_context:
        context = clusters[0]["samples"][0]["generation_context"]
        context["sources"][0]["content"] = "伪造替换的资料"
        context["block"] = rag_service.format_retrieved_block(
            [rag_service.RetrievedChunk(**s) for s in context["sources"]]
        )
    (folder / "clusters.json").write_text(json.dumps(clusters))
    (folder / "source.py").write_bytes(run["source"])
    trainer.main(
        [
            "baseline",
            "--surface",
            consumer.SURFACE,
            "--source",
            str(folder / "source.py"),
            "--out",
            str(folder / "baseline.txt"),
        ]
    )
    (folder / "candidate.txt").write_text(rag_service.RAG_SYSTEM_PROMPT + "\n逐一检查引用编号。")
    trainer.main(
        [
            "prepare",
            "--surface",
            consumer.SURFACE,
            "--employee-id",
            consumer.RESOURCE,
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
    cases = json.loads((folder / "tests.json").read_bytes())
    results = []
    for i, case in enumerate(cases):
        for arm, answer in enumerate(["无引用", "原订单数为3。[1]"]):
            grade = feedback.get_assert(answer, {"vars": case["vars"]})
            results.append(
                {
                    "promptIdx": arm,
                    "testIdx": i,
                    "success": grade["pass"],
                    "failureReason": 0 if grade["pass"] else 1,
                    "gradingResult": grade,
                    "error": None if grade["pass"] else "Deterministic assertion failed",
                    "provider": {"id": bundle["provider_id"]},
                    "vars": case["vars"],
                    "response": {"output": answer},
                }
            )
    result = {
        "metadata": {"promptfooVersion": trainer.PROMPTFOO_VERSION},
        "results": {
            "prompts": [
                {"raw": (folder / bundle["files"][k]["name"]).read_bytes().decode()}
                for k in ("baseline", "candidate")
            ],
            "results": results,
        },
    }
    return {
        "request_key": "rag-training-" + uuid4().hex,
        "surface": consumer.SURFACE,
        "resource_id": consumer.RESOURCE,
        "source_sha": "a" * 40,
        "workflow_run_id": 77,
        "failure_run_ids": [s["run_id"] for c in clusters for s in c["samples"]],
        "bundle_json": (folder / "training-bundle.json").read_bytes().decode(),
        "files": {
            k: (folder / entry["name"]).read_bytes().decode()
            for k, entry in bundle["files"].items()
        },
        "result_json": json.dumps(result),
    }


@pytest.mark.asyncio
async def test_actual_rag_failure_reaches_original_candidate_approval(rag_training):
    run = rag_training
    await run["rag"]["call"]()
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
    current = evolution.read(run["client"], request_id)
    assert current["status"] == "awaiting_dispatch_approval"
    source = current["effects"]["training_candidate"]
    assert (
        source["prompt_path"] == RAG_PROMPT_PATH and source["prompt_symbol"] == "RAG_SYSTEM_PROMPT"
    )
    assert source["growthbook"]["lifecycle"]["measurement_scope"] == consumer.MEASUREMENT
    assert "真实私有资料" not in current["snapshot"]["plan"]["public_body"]
    assert json.loads(training_plan(request_id).splitlines()[-1])["symbol"] == "RAG_SYSTEM_PROMPT"
    assert not [call for call in run["calls"] if call[0] == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["context", "forged_grade", "model", "source_hash"])
async def test_rag_training_rejects_unbound_or_self_reported_improvement(
    rag_training, monkeypatch, fault
):
    run = rag_training
    await run["rag"]["call"]()
    if fault == "model":
        monkeypatch.setenv("XCAGI_LLM_MODEL", "different-route")
        with pytest.raises(ValueError, match="training_original_model_unbound"):
            _body(run)
        return
    body = _body(run, tamper_context=fault == "context")
    if fault == "forged_grade":
        result = json.loads(body["result_json"])
        result["results"]["results"][-1]["response"]["output"] = "不存在的引用[99]"
        body["result_json"] = json.dumps(result)
    elif fault == "source_hash":
        body["source_sha"] = "b" * 40
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("PROMPTFOO_CLI"), reason="pinned promptfoo CLI not configured"
)
async def test_pinned_promptfoo_preserves_actual_rag_messages_and_independent_assertion(
    rag_training,
):
    run = rag_training
    await run["rag"]["call"]()
    body = _body(run)
    folder = run["directory"] / "eval"
    bundle = json.loads(body["bundle_json"])
    config = json.loads(body["files"]["config"])
    received = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(request)
            answer = (
                "订单数为3。[1]"
                if "逐一检查引用编号。" in request["messages"][0]["content"]
                else "无引用"
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
                            "message": {"role": "assistant", "content": answer},
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
        (folder / "promptfooconfig.yaml").write_text(body["files"]["config"])
        bundle["files"]["config"]["sha256"] = trainer._hash(body["files"]["config"])
        with local_only_environment(
            folder,
            provider_url=provider["config"]["apiBaseUrl"],
            pythonpath=str(Path(rag_service.__file__).parents[1]),
        ) as (environment, denied):
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
    assert set(denied) <= {"r.promptfoo.app"}
    assert len(received) == 2
    original = run["rag"]["calls"][0]
    assert any(r["messages"] == original for r in received)
    assert all(r["messages"][1:] == original[1:] for r in received)
    body.update(
        bundle_json=json.dumps(bundle),
        result_json=(folder / "actual-result.json").read_bytes().decode(),
    )
    response = run["client"].post(
        "/api/service/mac-control/training/candidates", headers=run["auth"], json=body
    )
    assert response.status_code == 202, response.text
