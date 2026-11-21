"""The actual fixed OpenCode consumer emits two measured Responses calls."""

from __future__ import annotations

import importlib
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import uvicorn

from modstore_server import strategic_portfolio as p
from modstore_server import strategic_portfolio_runtime as runtime
from tests import test_strategic_remote_bridge as remote_tests

database = remote_tests.database
remote = remote_tests.remote
REPORT = "Support cases decreased from 10 to 8; the service improved by 20%."


def provider(monkeypatch, remote, *, tool_name="read", tool_arguments=None, output_text=REPORT):
    import openai

    client_type = openai.DefaultAsyncHttpxClient
    http = importlib.import_module(client_type.__mro__[1].__module__.split(".")[0])
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        calls = p.portfolio_status(remote.decision_id)["tasks"]["a"]["calls"]
        assert len(calls) == len(seen)
        assert sum(call["status"] == "pending" for call in calls.values()) == 1
        assert request.headers["authorization"] == "Bearer platform-test-key"
        assert payload["store"] is False and payload["stream"] is True
        assert "previous_response_id" not in payload
        if len(seen) == 1:
            item = {
                "type": "function_call",
                "id": "fc_business_notes",
                "call_id": "call_business_notes",
                "name": tool_name,
                "arguments": json.dumps(tool_arguments or {"filePath": "TASK.md"}),
                "status": "completed",
            }
            delta = {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": item["id"],
                "delta": item["arguments"],
            }
        else:
            assert any(
                item.get("type") == "function_call_output"
                and (tool_name != "read" or "decreased from 10 to 8" in item["output"])
                for item in payload["input"]
            )
            item = {
                "type": "message",
                "id": "msg_business_report",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": output_text, "annotations": []}],
            }
            delta = {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": item["id"],
                "delta": output_text,
            }
        response = {
            "id": f"resp-business-{len(seen)}",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": "approved-model-native-snapshot",
            "output": [item],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 8,
                "total_tokens": 128,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        frames = [
            {
                "type": "response.created",
                "response": {
                    **response,
                    "status": "in_progress",
                    "output": [],
                    "usage": None,
                },
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    **item,
                    "status": "in_progress",
                    **({"arguments": ""} if len(seen) == 1 else {"content": []}),
                },
            },
        ]
        if len(seen) > 1:
            frames.append(
                {
                    "type": "response.content_part.added",
                    "output_index": 0,
                    "content_index": 0,
                    "item_id": item["id"],
                    "part": {"type": "output_text", "text": "", "annotations": []},
                }
            )
        frames.extend(
            [
                delta,
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
        )
        body = "".join(
            "event: "
            + frame["type"]
            + "\ndata: "
            + json.dumps({**frame, "sequence_number": index})
            + "\n\n"
            for index, frame in enumerate(frames)
        ).encode()
        return http.Response(200, content=body, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(
        openai,
        "DefaultAsyncHttpxClient",
        lambda **kwargs: client_type(transport=http.MockTransport(respond), **kwargs),
    )
    return seen


@pytest.mark.skipif(
    not os.environ.get("PARA_TEST_OPENCODE_BINARY"),
    reason="requires the pinned OpenCode 1.19.6 binary",
)
def test_existing_actions_controller_real_opencode_sdk_sql_and_native_artifact(
    remote, monkeypatch, tmp_path
):
    binary = os.environ["PARA_TEST_OPENCODE_BINARY"]
    assert subprocess.check_output([binary, "--version"], text=True, timeout=15).strip() == "1.19.6"
    seen = provider(monkeypatch, remote)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(
        uvicorn.Config(remote.app, log_level="error", lifespan="off", ws="none")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    env_file = tmp_path / "executor.json"
    evidence = tmp_path / "evidence"
    env_file.write_text(
        json.dumps(
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_RUN_ID": "42",
                "GITHUB_SHA": remote_tests.SOURCE,
                "GITHUB_REPOSITORY": remote_tests.REPO,
                "PARA_GITHUB_STAGE": "execute",
                "PARA_GITHUB_REQUEST_ID": remote.request_id,
                "PARA_GITHUB_EVIDENCE_DIR": str(evidence),
                "MODSTORE_PARA_DISPATCH_TOKEN": remote_tests.TOKEN,
                "DEVFLEET_FORCE_OPENCODE": "1",
                "PATH": os.environ["PATH"],
                "GITHUB_OUTPUT": str(tmp_path / "job-output"),
            }
        )
    )
    root = Path(__file__).resolve().parents[3]
    env = {
        **os.environ,
        "REPORT_LOOPBACK": f"http://127.0.0.1:{sock.getsockname()[1]}",
        "REPORT_RUNTIME_TOOLS": str(root / "FHD/scripts/autonomy/runtime_tools"),
    }
    try:
        result = subprocess.run(
            [
                "node",
                str(Path(__file__).parent / "fixtures/strategic_report_wire.mjs"),
                str(env_file),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=55,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert not thread.is_alive()
    assert len(seen) == 2
    assert (evidence / "report.md").read_text() == REPORT
    assert (tmp_path / "job-output").read_text() == "strategic_report=true\n"
    saved = p.portfolio_status(remote.decision_id)["tasks"]["a"]
    assert saved["status"] == "running"  # Still waiting for GitHub's native immutable artifact.
    assert [call["status"] for call in saved["calls"].values()] == [
        "settled",
        "settled",
    ]
    assert sum(call["actual_tokens"] for call in saved["calls"].values()) == 256
    receipt = json.loads((evidence / "execution.json").read_text())
    remote.github.publish(receipt, REPORT)
    remote_tests.download_transport(remote, monkeypatch)
    finished = runtime.run_portfolio_cycle(remote.decision_id, owner_user_id=7)
    assert finished["tasks"]["a"]["status"] == "completed"
    assert finished["tasks"]["a"]["execution_receipt"]["output"] == REPORT
    assert finished["tasks"]["a"]["actual_tokens"] == 256
    assert len(remote.github.writes) == 1
