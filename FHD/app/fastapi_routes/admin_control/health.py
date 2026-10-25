"""RemoteHealth control-plane operations with explicit callback dependencies."""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from .port_contracts import ErrorPolicy, JsonObject


class RemoteHealth:
    def __init__(
        self,
        *,
        errors: ErrorPolicy,
        remote_host: Callable[[], str],
        remote_port: Callable[[], int],
        default_urlopen: Callable[[], object],
        probe_remote_health_sync: Callable[[], JsonObject],
    ) -> None:
        self._errors = errors
        self._remote_host = remote_host
        self._remote_port = remote_port
        self._default_urlopen = default_urlopen
        self._call_probe_remote_health_sync = probe_remote_health_sync

    def _probe_remote_health_sync(self) -> dict[str, Any]:
        """同步探测远端 HTTP /api/health；供 asyncio.to_thread 调用，避免阻塞事件循环。"""
        # MODstore may share this production host while only listening on loopback.
        # Prefer its configured internal address so the dashboard does not report a
        # false outage when a public-IP hairpin is unavailable.
        internal_base = str(
            os.environ.get("XCMAX_REMOTE_HEALTH_BASE_URL")
            or os.environ.get("MODSTORE_INTERNAL_BASE_URL")
            or os.environ.get("MODSTORE_LOCAL_BASE_URL")
            or ""
        ).strip()
        remote_url = (
            f"{internal_base.rstrip('/')}/api/health"
            if internal_base
            else f"http://{self._remote_host()}:{self._remote_port()}/api/health"
        )
        t0 = time.time()
        try:
            req = urllib.request.Request(remote_url, method="GET")
            if urllib.request.urlopen is self._default_urlopen():
                direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                response_ctx = direct_opener.open(req, timeout=5)
            else:
                response_ctx = urllib.request.urlopen(req, timeout=5)
            with response_ctx as resp:
                latency_ms = round((time.time() - t0) * 1000)
                body = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
                return {
                    "success": True,
                    "data": {
                        "reachable": True,
                        "latency_ms": latency_ms,
                        "version": body.get("version") or body.get("git_sha") or "",
                        "deploy_time": body.get("timestamp") or "",
                        "host": self._remote_host(),
                        "port": self._remote_port(),
                    },
                }
        except self._errors.recoverable() as exc:
            self._errors.logger.debug("remote_status probe failed: %s", exc)
            return {
                "success": True,
                "data": {
                    "reachable": False,
                    "latency_ms": None,
                    "version": "",
                    "deploy_time": "",
                    "host": self._remote_host(),
                    "port": self._remote_port(),
                    "error": str(exc),
                },
            }

    async def remote_status(self):
        """探测远端服务器连接状态（轻量 HTTP GET /api/health）。"""
        return await asyncio.to_thread(self._call_probe_remote_health_sync)
