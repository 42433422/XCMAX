from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from retort_engine.core import RetortService


class RetortUIServer:
    def __init__(self) -> None:
        self.service = RetortService()
        self.static_root = Path(__file__).with_name("frontend")
        self.default_project = Path(__file__).resolve().parents[1]

    def handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/health":
                    self._json({"status": "ok"})
                    return
                if parsed.path == "/api/default-project":
                    self._json({"project": str(outer.default_project)})
                    return
                target = outer.static_root / ("index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/"))
                if not target.is_file():
                    self.send_error(404)
                    return
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                payload = self._read_json()
                try:
                    if self.path == "/api/assess":
                        self._json(outer.service.assess(payload))
                    elif self.path == "/api/absorb":
                        self._json(outer.service.absorb(payload))
                    elif self.path == "/api/self-evolve":
                        self._json(outer.service.self_evolve(payload))
                    elif self.path == "/api/record-proof":
                        self._json(outer.service.record_proof(payload))
                    elif self.path == "/api/review-diff":
                        self._json(outer.service.review_diff(payload))
                    elif self.path == "/api/review-pr":
                        self._json(outer.service.review_pr(payload))
                    elif self.path == "/api/publish-pr-dry-run":
                        self._json(outer.service.publish_pr_dry_run(payload))
                    elif self.path == "/api/publish-pr-sandbox":
                        self._json(outer.service.publish_pr_sandbox(payload))
                    elif self.path == "/api/publish-pr-live-probe":
                        self._json(outer.service.publish_pr_live_probe(payload))
                    elif self.path == "/api/cross-project-replay":
                        self._json(outer.service.cross_project_replay(payload))
                    elif self.path == "/api/complex-pr-replay":
                        self._json(outer.service.complex_pr_replay(payload))
                    elif self.path == "/api/task-prioritization-report":
                        self._json(outer.service.task_prioritization_report(payload))
                    elif self.path == "/api/task-dispatch-plan":
                        self._json(outer.service.task_dispatch_plan(payload))
                    elif self.path == "/api/quality-benchmark-report":
                        self._json(outer.service.review_quality_benchmark(payload))
                    elif self.path == "/api/employee-scheduler-stress":
                        self._json(outer.service.employee_scheduler_stress(payload))
                    elif self.path == "/api/generalization-proof-report":
                        self._json(outer.service.generalization_proof_report(payload))
                    elif self.path == "/api/similar-project-radar":
                        self._json(outer.service.similar_project_radar(payload))
                    elif self.path == "/api/similar-project-loop":
                        self._json(outer.service.similar_project_loop(payload))
                    elif self.path == "/api/absorption-saturation":
                        self._json(outer.service.absorption_saturation_report(payload))
                    elif self.path == "/api/llm-review":
                        self._json(outer.service.llm_review(payload))
                    elif self.path == "/api/llm-review-status":
                        self._json(outer.service.llm_review_status(payload))
                    elif self.path == "/api/llm-review-parallel":
                        self._json(outer.service.llm_parallel_review(payload))
                    elif self.path == "/api/llm-review-group-status":
                        self._json(outer.service.llm_parallel_status(payload))
                    else:
                        self.send_error(404)
                except Exception as exc:
                    self._json({"status": "error", "error": str(exc)}, 400)

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or "0")
                return {} if not length else json.loads(self.rfile.read(length).decode("utf-8"))

            def _json(self, payload: dict[str, Any], status: int = 200) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler


def run_ui_server(host: str, port: int) -> None:
    print(f"Retort Blackhole UI: http://{host}:{port}")
    ThreadingHTTPServer((host, port), RetortUIServer().handler()).serve_forever()
