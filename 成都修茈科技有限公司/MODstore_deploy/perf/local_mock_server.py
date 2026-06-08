#!/usr/bin/env python3
"""极简本地 mock，供 perf 脚本（k6 / probe.py）在没有完整业务栈时验证脚本与采集形态。

用法：
    python perf/local_mock_server.py --port 18000 [--latency-ms 5]

约定：
- `/api/health`              -> 200 JSON，模拟 FastAPI health。
- `/api/mod-store/catalog`   -> 200 JSON，含 1 个示例条目，对齐 FHD `scripts/loadtest/config.js`。
- 其他路径                    -> 404 JSON。

仅用于本机验证；不要在生产或对外环境运行，也不要用此服务的输出作为真实容量结论。
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(latency_ms: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if latency_ms > 0:
                time.sleep(latency_ms / 1000.0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/health":
                self._write_json(200, {"status": "ok", "service": "local-mock"})
            elif self.path == "/api/mod-store/catalog":
                self._write_json(
                    200,
                    {
                        "items": [
                            {"id": "demo", "name": "Demo Mod", "version": "0.0.0"},
                        ],
                        "total": 1,
                    },
                )
            elif self.path == "/health/liveness":
                self._write_json(200, {"status": "alive"})
            else:
                self._write_json(404, {"error": "not_found", "path": self.path})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--latency-ms", type=int, default=0, help="每次响应人为延迟（毫秒）")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.latency_ms))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"local-mock listening on http://{args.host}:{args.port} (latency={args.latency_ms}ms)")
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
