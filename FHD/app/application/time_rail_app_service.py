"""时间轨 workflow 图 + runtime 状态（FHD 侧：本地读图，状态必须来自 MODstore）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

_GRAPH_REL = Path("config/time_rail_workflow_graph.json")


class TimeRailStatusUnavailableError(RuntimeError):
    """MODstore 时间轨 runtime 不可达或未返回有效数据。"""


class TimeRailAppService:
    def _fhd_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def graph_path(self) -> Path:
        return self._fhd_root() / _GRAPH_REL

    def load_graph(self) -> dict[str, Any]:
        path = self.graph_path()
        if not path.is_file():
            raise FileNotFoundError(f"time_rail workflow graph missing: {path}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("time_rail workflow graph must be a JSON object")
        return doc

    def graph_payload(self) -> dict[str, Any]:
        doc = self.load_graph()
        return {
            "ok": True,
            "version": doc.get("version"),
            "schema": doc.get("schema"),
            "center_id": doc.get("center_id"),
            "phase_colors": doc.get("phase_colors") or {},
            "compact_ids": doc.get("compact_ids") or [],
            "xrail_edge_keys": doc.get("xrail_edge_keys") or [],
            "nodes": doc.get("nodes") or [],
            "edges": doc.get("edges") or [],
            "source": doc.get("source"),
            "path": str(self.graph_path()),
        }

    async def runtime_status(self, *, node_id: str | None = None) -> dict[str, Any]:
        query = f"node_id={node_id}" if node_id else ""
        try:
            from app.application.modstore_local_client import modstore_get, modstore_digest_base_url

            payload = await modstore_get(
                "/api/admin/production-line/time-rail/status",
                query=query,
                timeout=8.0,
                base_url=modstore_digest_base_url(),
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict) and isinstance(data.get("nodes"), dict):
                return data
            raise TimeRailStatusUnavailableError(
                f"MODstore time-rail status 响应无效: {payload!r}"
            )
        except TimeRailStatusUnavailableError:
            raise
        except OPERATIONAL_ERRORS as exc:
            raise TimeRailStatusUnavailableError(
                f"MODstore time-rail status 不可达: {exc}"
            ) from exc


_service: TimeRailAppService | None = None


def get_time_rail_app_service() -> TimeRailAppService:
    global _service
    if _service is None:
        _service = TimeRailAppService()
    return _service
