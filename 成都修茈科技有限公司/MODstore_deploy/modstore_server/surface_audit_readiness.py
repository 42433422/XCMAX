"""Aggregate per-service readiness without treating a disabled start as success."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List

from modstore_server.surface_audit_runtime import _parse_port

logger = logging.getLogger(__name__)
ServiceResult = dict[str, Any]


@dataclass(frozen=True)
class SurfaceDependencyChecks:
    playwright: Callable[[], ServiceResult]
    fhd_api: Callable[[int], ServiceResult]
    vite: Callable[[int, int], ServiceResult]
    marketing: Callable[[int], ServiceResult]
    modstore_api: Callable[[int], ServiceResult]
    android: Callable[[], ServiceResult]
    internal_api_base: Callable[[], str]
    is_local_url: Callable[[str], bool]

    def run(self) -> Dict[str, Any]:
        """截图前确保本地依赖就绪；返回各服务探活/拉起结果。"""
        out: Dict[str, Any] = {"ok": True, "services": {}}
        ps_enabled = (
            os.environ.get("MODSTORE_SURFACE_AUDIT_PS_ENABLED", "1") or ""
        ).strip().lower() not in ("0", "false", "no", "off")
        ps_base = (
            os.environ.get("MODSTORE_SURFACE_AUDIT_PS_BASE_URL")
            or os.environ.get("SURFACE_AUDIT_BASE_URL")
            or "http://127.0.0.1:5001"
        ).rstrip("/")
        api_url = (
            os.environ.get("SURFACE_AUDIT_API_URL")
            or os.environ.get("MODSTORE_SURFACE_AUDIT_API_URL")
            or "http://127.0.0.1:5102"
        ).rstrip("/")
        digest_base = (
            os.environ.get("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL") or "https://xiu-ci.com"
        ).rstrip("/")
        internal_api = self.internal_api_base()
        api_port = _parse_port(api_url, 5102)
        web_port = _parse_port(ps_base, 5001)
        modstore_port = _parse_port(internal_api, 8788)
        out["services"]["playwright"] = self.playwright()
        if ps_enabled and self.is_local_url(ps_base):
            out["services"]["fhd_api"] = self.fhd_api(api_port)
            out["services"]["vite_ps"] = self.vite(web_port, api_port)
        if self.is_local_url(digest_base):
            mkt_port = _parse_port(
                os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:5176",
                5176,
            )
            out["services"]["marketing"] = self.marketing(mkt_port)
        if self.is_local_url(internal_api):
            out["services"]["modstore_api"] = self.modstore_api(modstore_port)
        out["services"]["android_emulator"] = self.android()
        failures: List[str] = []
        for name, service in out["services"].items():
            if not isinstance(service, dict):
                failures.append(f"{name}:invalid_result")
            elif service.get("error"):
                failures.append(f"{name}:{service['error']}")
            elif not service.get("ok"):
                failures.append(f"{name}:not_ready")
            elif name in ("fhd_api", "vite_ps", "modstore_api", "marketing") and not (
                service.get("skipped") or service.get("ready")
            ):
                failures.append(f"{name}:not_ready")
        out["ok"] = not failures
        if failures:
            out["failures"] = failures
            logger.warning("surface audit deps incomplete: %s", failures)
        else:
            logger.info("surface audit deps ready")
        return out
