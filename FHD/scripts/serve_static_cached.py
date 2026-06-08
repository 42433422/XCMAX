"""
Dev static file server with long-lived cache headers for webfonts.

Reduces Chrome's "Slow network is detected ... Fallback font" noise when serving
Font Awesome (or similar) from a local dev server on e.g. port 5001.

By default, paths under /api/ are reverse-proxied to the FHD FastAPI app
(http://127.0.0.1:8000) so the frontend can use same-origin URLs like
http://localhost:5001/api/customers/list while you run the API on PORT 8000.

全景仪表盘（``scripts/serve_xcagi_dashboard.sh``） additionally forwards:
  /metrics/*     → FHD ``/metrics``
  /prometheus/*  → Prometheus (strip ``/prometheus`` prefix)
  /grafana/*     → Grafana (strip ``/grafana`` prefix, optional basic auth)

Usage (from your frontend dist or public folder):
  python scripts/serve_static_cached.py --port 5001 --directory path/to/dist
  # Terminal 2: cd XCAGI && python run.py   (FastAPI on 5000)
"""

from __future__ import annotations

import argparse
import base64
import http.server
import shutil
import socketserver
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path


class CachedStaticHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        path_only = self.path.split("?", 1)[0].lower()
        if path_only.endswith((".woff", ".woff2", ".ttf", ".eot", ".otf")):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        super().end_headers()


_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


class DevStaticHandler(CachedStaticHandler):
    """Serves static files; forwards /api /metrics /prometheus /grafana when configured."""

    _API_DISABLED_MSG = (
        "This URL is an API path, but --no-api-proxy is set (or api_backend is empty). "
        "Restart without --no-api-proxy so /api/* is forwarded to the FastAPI app "
        "(default http://127.0.0.1:8000), or point the frontend at that origin directly."
    )

    def _path_only(self) -> str:
        return self.path.split("?", 1)[0]

    def _resolve_proxy(self) -> tuple[str, str] | None:
        path = self._path_only()
        if path.startswith("/api"):
            backend = getattr(self.server, "api_backend", None)
            if backend:
                return str(backend).rstrip("/"), self.path
            return None
        if path == "/metrics" or path.startswith("/metrics/"):
            backend = getattr(self.server, "api_backend", None)
            if backend:
                return str(backend).rstrip("/"), self.path
            return None
        if path.startswith("/prometheus"):
            backend = getattr(self.server, "prometheus_backend", None)
            if backend:
                suffix = self.path[len("/prometheus") :] or "/"
                return str(backend).rstrip("/"), suffix
            return None
        if path.startswith("/grafana"):
            backend = getattr(self.server, "grafana_backend", None)
            if backend:
                suffix = self.path[len("/grafana") :] or "/"
                return str(backend).rstrip("/"), suffix
            return None
        return None

    def _should_proxy(self) -> bool:
        return self._resolve_proxy() is not None

    def _proxy_to_backend(self) -> None:
        resolved = self._resolve_proxy()
        if not resolved:
            return
        backend, rel_path = resolved
        target = backend.rstrip("/") + rel_path
        data: bytes | None = None
        if self.command in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", 0) or 0)
            data = self.rfile.read(length) if length else b""
        req = urllib.request.Request(target, data=data, method=self.command)
        for key, value in self.headers.items():
            lk = key.lower()
            if lk in _HOP_BY_HOP or lk == "host":
                continue
            req.add_header(key, value)
        if self._path_only().startswith("/grafana"):
            user = getattr(self.server, "grafana_user", None)
            password = getattr(self.server, "grafana_pass", None)
            if user and password and not req.has_header("Authorization"):
                token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
                req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() in _HOP_BY_HOP:
                        continue
                    self.send_header(k, v)
                self.end_headers()
                shutil.copyfileobj(resp, self.wfile)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() in _HOP_BY_HOP:
                    continue
                self.send_header(k, v)
            self.end_headers()
            body = e.read()
            if body:
                self.wfile.write(body)
        except urllib.error.URLError as e:
            reason = getattr(e.reason, "winerror", None) or e.reason
            msg = f"Proxy backend not reachable ({target}): {reason!s}."
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))

    def _reject_api_without_proxy(self) -> bool:
        """Avoid misleading 404 from static lookup for /api/* when proxy is off."""
        if getattr(self.server, "api_backend", None):
            return False
        if not self._path_only().startswith("/api"):
            return False
        self.send_response(503, "API proxy disabled")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(self._API_DISABLED_MSG.encode("utf-8"))
        return True

    def do_GET(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        self.send_error(405, "Method not allowed")

    def do_PUT(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        self.send_error(405, "Method not allowed")

    def do_PATCH(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        self.send_error(405, "Method not allowed")

    def do_DELETE(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        if self._reject_api_without_proxy():
            return
        self.send_error(405, "Method not allowed")

    def do_OPTIONS(self) -> None:
        if self._should_proxy():
            self._proxy_to_backend()
            return
        super().do_OPTIONS()


class _ApiProxyTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        RequestHandlerClass,
        *,
        api_backend: str | None = None,
        prometheus_backend: str | None = None,
        grafana_backend: str | None = None,
        grafana_user: str | None = None,
        grafana_pass: str | None = None,
        bind_and_activate: bool = True,
    ) -> None:
        self.api_backend = api_backend
        self.prometheus_backend = prometheus_backend
        self.grafana_backend = grafana_backend
        self.grafana_user = grafana_user
        self.grafana_pass = grafana_pass
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=5001, help="TCP port (default 5001)")
    p.add_argument(
        "--directory",
        default=".",
        help="Root directory to serve (default current directory)",
    )
    p.add_argument(
        "--api-backend",
        default="http://127.0.0.1:8000",
        help="Forward /api/* and /metrics to this origin (default http://127.0.0.1:8000).",
    )
    p.add_argument(
        "--prometheus-backend",
        default="",
        help="Forward /prometheus/* to this origin (e.g. http://127.0.0.1:9091).",
    )
    p.add_argument(
        "--grafana-backend",
        default="",
        help="Forward /grafana/* to this origin (e.g. http://127.0.0.1:3000).",
    )
    p.add_argument("--grafana-user", default="", help="Optional Grafana basic-auth user.")
    p.add_argument("--grafana-pass", default="", help="Optional Grafana basic-auth password.")
    p.add_argument(
        "--no-api-proxy",
        action="store_true",
        help="Serve only static files; do not proxy /api/*.",
    )
    args = p.parse_args()
    root = str(Path(args.directory).resolve())
    api_backend = None if args.no_api_proxy else str(args.api_backend).strip().rstrip("/") or None
    prometheus_backend = str(args.prometheus_backend).strip().rstrip("/") or None
    grafana_backend = str(args.grafana_backend).strip().rstrip("/") or None
    grafana_user = str(args.grafana_user).strip() or None
    grafana_pass = str(args.grafana_pass).strip() or None
    handler = partial(DevStaticHandler, directory=root)
    with _ApiProxyTCPServer(
        (args.host, args.port),
        handler,
        api_backend=api_backend,
        prometheus_backend=prometheus_backend,
        grafana_backend=grafana_backend,
        grafana_user=grafana_user,
        grafana_pass=grafana_pass,
    ) as httpd:
        extras = []
        if api_backend:
            extras.append(f"/api|/metrics -> {api_backend}")
        if prometheus_backend:
            extras.append(f"/prometheus -> {prometheus_backend}")
        if grafana_backend:
            extras.append(f"/grafana -> {grafana_backend}")
        extra = ("; " + "; ".join(extras)) if extras else ""
        print(f"Serving {root} at http://{args.host}:{args.port}/{extra}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
