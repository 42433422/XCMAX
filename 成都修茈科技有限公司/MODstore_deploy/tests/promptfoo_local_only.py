"""Keep the pinned CLI contract fixtures on loopback, including its opt-out ping.

Promptfoo 0.126.0 sends that ping through its proxy-aware fetch even with telemetry
disabled. This proxy never forwards a request or opens an upstream socket. It
rejects HTTPS before TLS, and records only the destination host, never payloads.
The provider is either echo or one explicit loopback HTTP fixture.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


@contextmanager
def local_only_environment(
    directory: Path, *, provider_url: str | None = None, pythonpath: str | None = None
) -> Iterator[tuple[dict[str, str], list[str]]]:
    bypass = ""
    if provider_url is not None:
        provider = urlsplit(provider_url)
        if provider.scheme != "http" or provider.hostname != "127.0.0.1" or not provider.port:
            raise ValueError("promptfoo contract fixtures require an explicit loopback provider")
        bypass = f"127.0.0.1:{provider.port}"
    denied_hosts: list[str] = []

    class DenyProxy(BaseHTTPRequestHandler):
        def deny(self):
            target = urlsplit("//" + self.path if self.command == "CONNECT" else self.path)
            denied_hosts.append(target.hostname or "invalid-destination")
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        do_CONNECT = do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = deny

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), DenyProxy)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = f"http://127.0.0.1:{server.server_port}"
    environment = {
        "PATH": os.environ["PATH"],
        "CI": "1",
        "PROMPTFOO_DISABLE_TELEMETRY": "1",
        "PROMPTFOO_DISABLE_UPDATE": "1",
        "PROMPTFOO_DISABLE_SHARING": "1",
        "PROMPTFOO_DISABLE_REMOTE_GENERATION": "1",
        "PROMPTFOO_SELF_HOSTED": "1",
        "PROMPTFOO_CONFIG_DIR": str(directory / "state"),
        "PROMPTFOO_LOG_DIR": str(directory / "logs"),
        "PROMPTFOO_PYTHON": sys.executable,
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "ALL_PROXY": proxy,
        "NO_PROXY": bypass,
        "http_proxy": proxy,
        "https_proxy": proxy,
        "all_proxy": proxy,
        "no_proxy": bypass,
    }
    if pythonpath is not None:
        environment["PYTHONPATH"] = pythonpath
    try:
        yield environment, denied_hosts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
