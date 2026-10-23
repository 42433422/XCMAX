"""Exercise the real entry point with an open stream and a real shutdown signal."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def test_entrypoint_drains_open_stream_within_shutdown_bound(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    script = """
import asyncio, sys, types
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from XCAGI import run_fastapi
root = Path(sys.argv[1])
@asynccontextmanager
async def lifespan(app):
    yield
    (root / 'shutdown-complete').touch()
def factory():
    app = FastAPI(lifespan=lifespan)
    @app.get('/stream')
    async def stream():
        async def events():
            while True:
                yield b'data: alive\\n\\n'
                await asyncio.sleep(0.05)
        return StreamingResponse(events(), media_type='text/event-stream')
    return app
module = types.ModuleType('app.fastapi_app')
module.create_fastapi_app = factory
sys.modules['app.fastapi_app'] = module
run_fastapi._is_frozen = lambda: True
run_fastapi._load_dotenv_if_present = lambda path: None
run_fastapi._persist_runtime_port = lambda *args: None
run_fastapi.main(['--host', '127.0.0.1', '--port', sys.argv[2]])
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("XCAGI_", "FASTAPI_"))
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    log = tmp_path / "server.log"
    connection = None
    with log.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(port)],
            cwd=tmp_path,
            env=env,
            stdout=output,
            stderr=output,
        )
        try:
            deadline = time.monotonic() + 15
            while connection is None and time.monotonic() < deadline:
                try:
                    connection = socket.create_connection(("127.0.0.1", port), timeout=1)
                except OSError:
                    assert process.poll() is None, log.read_text()
                    time.sleep(0.1)
            assert connection is not None, log.read_text()
            connection.sendall(b"GET /stream HTTP/1.1\r\nHost: localhost\r\n\r\n")
            received = b""
            while b"data: alive" not in received:
                received += connection.recv(8192)
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=40)
            # Uvicorn re-raises the received signal after completing lifespan.
            assert process.returncode in (0, -signal.SIGTERM), log.read_text()
            assert (tmp_path / "shutdown-complete").is_file(), log.read_text()
        finally:
            if connection is not None:
                connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
