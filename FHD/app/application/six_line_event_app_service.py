"""六线事件轨应用服务：匹配路由、派发 backlog/incident。"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.six_line.event_route import EventRoute
from app.infrastructure.six_line import event_route_loader as loader
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class SixLineEventAppService:
    def __init__(self) -> None:
        self._cfg: dict[str, Any] | None = None

    def _config(self) -> dict[str, Any]:
        if self._cfg is None:
            self._cfg = loader.load_routes_config()
        return self._cfg

    def _all_routes(self) -> list[EventRoute]:
        cfg = self._config()
        routes: list[EventRoute] = []
        for key in ("operations_line", "cross_line", "incident_defaults"):
            for raw in cfg.get(key) or []:
                if isinstance(raw, dict) and raw.get("id"):
                    routes.append(EventRoute.from_dict(raw))
        return routes

    def match_route(
        self,
        *,
        step_id: str | None = None,
        status: str = "progress",
        event_type: str | None = None,
    ) -> EventRoute | None:
        sid = (step_id or "").strip()
        if not sid and not event_type:
            return None
        if event_type:
            for route in self._all_routes():
                if route.matches_event_type(event_type):
                    if not sid or route.matches_step_status(sid, status):
                        return route
        if sid:
            for route in self._all_routes():
                if route.matches_step_status(sid, status):
                    return route
        return None

    def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        step_id = str(payload.get("step_id") or "").strip()
        status = str(payload.get("status") or "progress").strip()
        event_type = payload.get("event_type")
        if event_type is not None:
            event_type = str(event_type).strip() or None

        route = self.match_route(step_id=step_id, status=status, event_type=event_type)
        at = loader.utc_now_iso()
        audit: dict[str, Any] = {
            "step_id": step_id,
            "status": status,
            "event_type": event_type,
            "payload": payload.get("payload") or {},
            "at": at,
        }

        if not route:
            audit["matched"] = False
            audit["action"] = "unrouted"
            loader.append_audit(audit)
            return {"success": True, "matched": False, "action": "unrouted"}

        audit["matched"] = True
        audit["route_id"] = route.id
        audit["action"] = route.action
        audit["priority"] = route.priority
        loader.append_audit(audit)

        body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        results: list[dict[str, Any]] = []

        if route.action == "digest_backlog":
            entry = {
                "route_id": route.id,
                "step_id": step_id or route.line_step,
                "dispatch_line": route.dispatch_line,
                "list_kind": route.list_kind or "patches",
                "priority": route.priority,
                "event_type": event_type or route.event_type,
                "payload": body,
                "at": at,
            }
            loader.append_backlog(entry)
            results.append({"sink": "digest_backlog", "entry": entry})

        if route.action == "incident" or route.also_incident:
            inc_type = (
                event_type or route.event_type or route.also_incident or "ops.intake.task.queued"
            )
            entry = {
                "route_id": route.id,
                "event_type": inc_type,
                "priority": route.priority,
                "step_id": step_id or route.line_step,
                "six_line": route.six_line,
                "payload": body,
                "at": at,
            }
            posted = self._post_incident_remote(entry)
            if not posted:
                loader.append_incident_outbox(entry)
            results.append({"sink": "incident_bus", "remote": posted, "entry": entry})

        return {
            "success": True,
            "matched": True,
            "route_id": route.id,
            "action": route.action,
            "priority": route.priority,
            "results": results,
        }

    def _post_incident_remote(self, entry: dict[str, Any]) -> bool:
        import os

        base = (os.environ.get("XCAGI_MARKET_BASE_URL") or "").rstrip("/")
        if not base:
            return False
        try:
            import httpx

            secret = (os.environ.get("XCAGI_OPS_LINE_HOOK_SECRET") or "").strip()
            headers = {"Content-Type": "application/json"}
            if secret:
                headers["X-Ops-Line-Secret"] = secret
            r = httpx.post(
                f"{base}/api/admin/production-line/incident",
                json=entry,
                headers=headers,
                timeout=5.0,
            )
            return r.is_success
        except RECOVERABLE_ERRORS:
            logger.debug("incident remote post skipped", exc_info=True)
            return False

    def status_snapshot(self) -> dict[str, Any]:
        cfg = self._config()
        recent = loader.read_recent_audit(30)
        route_ids = [a.get("route_id") for a in recent if a.get("route_id")]
        graph_nodes: list[str] = []
        for a in recent[-5:]:
            rid = a.get("route_id")
            if rid:
                graph_nodes.append("ROUTER")
        return {
            "operations_routes": len(cfg.get("operations_line") or []),
            "cross_line_routes": len(cfg.get("cross_line") or []),
            "incident_defaults": len(cfg.get("incident_defaults") or []),
            "digest_backlog_pending": loader.count_jsonl_pending("six_line_digest_backlog.jsonl"),
            "incident_pending": loader.count_jsonl_pending("incident_outbox.jsonl"),
            "last_event_at": recent[-1].get("at") if recent else None,
            "recent_route_ids": list(dict.fromkeys(route_ids))[:8],
            "version": cfg.get("version"),
        }

    def list_backlog_for_digest(self, limit: int = 200) -> list[dict[str, Any]]:
        """供 08:00 Vibe / 补丁清单合并读取（不删除行，由运维归档）。"""

        path = loader._customer_service_dir() / "six_line_digest_backlog.jsonl"
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        out: list[dict[str, Any]] = []
        import json

        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


def get_six_line_event_app_service() -> SixLineEventAppService:
    return SixLineEventAppService()
