"""Real TCP faults through Toxiproxy and the production tool/idempotency path.

The HTTP receiver is a synthetic external service with an actual SQLite commit;
it deliberately has no unique business key to hide accidental duplicate writes.
Session replay, worker crashes and upgrade readback remain in their native suites.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.application.agent_orchestrator import tool_permission as permissions
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture
def receiver(tmp_path):
    database = tmp_path / "external-effects.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE effects (request_id TEXT NOT NULL)")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO effects VALUES (?)", (body["request_id"],))
            self.reply(
                {
                    "success": True,
                    "file_name": "fixture.docx",
                    "download_url": "/api/files/fixture.docx",
                    "artifacts": [],
                    "request_id": body["request_id"],
                }
            )

        def do_GET(self):
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT request_id FROM effects ORDER BY rowid"
                ).fetchall()
            self.reply({"request_ids": [row[0] for row in rows]})

        def reply(self, body):
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A client disconnect must not undo the already committed effect.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, database
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def proxy(receiver, native_tool, tmp_path):
    port, _database = receiver
    api_port, proxy_port = _port(), _port()
    with (tmp_path / "toxiproxy.log").open("wb") as log:
        process = subprocess.Popen(
            [native_tool("toxiproxy-server"), "-host", "127.0.0.1", "-port", str(api_port)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{api_port}", trust_env=False, timeout=1
            ) as api:
                deadline = time.monotonic() + 10
                while True:
                    assert process.poll() is None, "Toxiproxy exited before readiness"
                    try:
                        api.get("/version").raise_for_status()
                        break
                    except httpx.TransportError:
                        assert time.monotonic() < deadline, "Toxiproxy did not become ready"
                        time.sleep(0.025)
                api.post(
                    "/proxies",
                    json={
                        "name": "external-receipt",
                        "listen": f"127.0.0.1:{proxy_port}",
                        "upstream": f"127.0.0.1:{port}",
                    },
                ).raise_for_status()
                try:
                    yield api, f"http://127.0.0.1:{proxy_port}"
                finally:
                    api.delete("/proxies/external-receipt").raise_for_status()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize(
    "toxic,attributes",
    [
        ("timeout", {"timeout": 150}),
        ("reset_peer", {"timeout": 150}),
        ("latency", {"latency": 800}),
    ],
)
def test_committed_effect_with_lost_receipt_is_never_replayed(
    proxy, receiver, tmp_path, monkeypatch, toxic, attributes
):
    api, base_url = proxy
    _port_number, effects = receiver
    ledger = tmp_path / "tool-idempotency.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(ledger))
    permissions.clear_idempotent_replay_for_tests()
    calls = []
    original = "original-turn-effect"
    context = {"tenant_id": "421", "task_id": "network-task", "user_id": "421"}
    step = AgentStep(
        node_id="export",
        tool_id="generate_office_document",
        action="execute",
        params={"user_request": "fixture export", "output_format": "docx"},
    )

    def external_dispatch(_tool, _action, params):
        request_id = params["_runtime_context"]["idempotency_key"]
        calls.append(request_id)
        with httpx.Client(trust_env=False, timeout=0.3) as transport:
            response = transport.post(base_url, json={"request_id": request_id})
            response.raise_for_status()
            return response.json()

    # Only the external tool implementation is substituted. Ownership, receipt
    # classification, durable SQL, restart recovery and retry policy are production.
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", external_dispatch
    )
    executor = AgentToolExecutor()
    try:
        assert (
            executor.execute(step, runtime_context={**context, "idempotency_key": "baseline"})[
                "success"
            ]
            is True
        )
        api.post(
            "/proxies/external-receipt/toxics",
            json={
                "name": "lost-receipt",
                "type": toxic,
                "stream": "downstream",
                "attributes": attributes,
            },
        ).raise_for_status()
        result = executor.execute(step, runtime_context={**context, "idempotency_key": original})
        assert result["success"] is False and result["outcome"] == "unknown"
        assert result["retryable"] is False and result["reconciliation_required"] is True
        assert result.get("error_code") != "output_schema_validation_failed"
        with sqlite3.connect(effects) as connection:
            assert connection.execute(
                "SELECT request_id FROM effects ORDER BY rowid"
            ).fetchall() == [("baseline",), (original,)]

        api.delete("/proxies/external-receipt/toxics/lost-receipt").raise_for_status()
        # Observe recovered transport and original committed state through the
        # repaired path. A successful health probe alone is not recovery evidence.
        with httpx.Client(trust_env=False, timeout=2) as transport:
            readback = transport.get(base_url)
            readback.raise_for_status()
            assert readback.json() == {"request_ids": ["baseline", original]}
        permissions.drop_process_idempotency_memory()
        assert permissions.recover_idempotent_claims()["retained_unknown"] == 1
        replay = executor.execute(step, runtime_context={**context, "idempotency_key": original})
        assert replay["outcome"] == "unknown" and replay["retryable"] is False
        assert replay["reconciliation_required"] is True
        assert calls == ["baseline", original]
        with sqlite3.connect(effects) as connection:
            assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 2
        with sqlite3.connect(ledger) as connection:
            assert connection.execute("SELECT COUNT(*) FROM tool_idempotency").fetchone()[0] == 2
    finally:
        permissions.clear_idempotent_replay_for_tests()
