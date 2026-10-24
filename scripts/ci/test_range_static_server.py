#!/usr/bin/env python3
"""Exercise the local static server's single byte-range contract."""

from __future__ import annotations

import importlib.util
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SERVER_MODULE = (
    Path(__file__).resolve().parents[2]
    / "成都修茈科技有限公司"
    / "scripts"
    / "range_static_server.py"
)
spec = importlib.util.spec_from_file_location("xcmax_range_static_server", SERVER_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load static server from {SERVER_MODULE}")
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="xcmax-range-contract-") as temp_dir:
        root = Path(temp_dir)
        payload = b"0123456789"
        (root / "range.bin").write_bytes(payload)
        (root / "empty.bin").write_bytes(b"")
        server_module.ROOT = root
        server = ThreadingHTTPServer(("127.0.0.1", 0), server_module.RangeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        def request(path: str, range_header: str | None = None):
            req = urllib.request.Request(f"{base_url}/{path}")
            if range_header:
                req.add_header("Range", range_header)
            try:
                response = urllib.request.urlopen(req, timeout=3)
            except urllib.error.HTTPError as exc:
                try:
                    return exc.code, exc.headers, exc.read()
                finally:
                    exc.close()
            with response:
                return response.status, response.headers, response.read()

        try:
            status, headers, body = request("range.bin")
            assert status == 200
            assert body == payload
            assert headers["Accept-Ranges"] == "bytes"

            status, headers, body = request("range.bin", "bytes=2-5")
            assert status == 206
            assert headers["Content-Range"] == "bytes 2-5/10"
            assert body == b"2345"

            status, _, body = request("range.bin", "bytes=7-")
            assert status == 206
            assert body == b"789"

            status, headers, body = request("range.bin", "bytes=-3")
            assert status == 206
            assert headers["Content-Range"] == "bytes 7-9/10"
            assert body == b"789"

            status, _, _ = request("empty.bin", "bytes=0-")
            assert status == 416
            print("static server byte-range contract OK")
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
