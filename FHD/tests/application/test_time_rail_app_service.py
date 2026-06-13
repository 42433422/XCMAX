"""TimeRailAppService — 本地图读取与 MODstore runtime degraded 路径。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.application.time_rail_app_service import (
    TimeRailAppService,
    get_time_rail_app_service,
)


def test_graph_payload_reads_local_json() -> None:
    svc = TimeRailAppService()
    payload = svc.graph_payload()
    assert payload["ok"] is True
    assert isinstance(payload.get("nodes"), list)
    assert payload.get("schema") == "time_rail_workflow_graph/v1"
    assert "time_rail_workflow_graph.json" in payload.get("path", "")


def test_load_graph_missing_raises(tmp_path, monkeypatch) -> None:
    svc = TimeRailAppService()
    monkeypatch.setattr(svc, "graph_path", lambda: tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        svc.load_graph()


@pytest.mark.asyncio
async def test_runtime_status_degraded_on_modstore_error() -> None:
    svc = TimeRailAppService()
    with patch(
        "app.application.modstore_local_client.modstore_get",
        new_callable=AsyncMock,
        side_effect=ConnectionError("modstore down"),
    ):
        data = await svc.runtime_status()
    assert data["degraded"] is True
    assert data["source"] == "fhd-degraded"
    assert "modstore down" in data["reason"]


@pytest.mark.asyncio
async def test_runtime_status_ok_when_modstore_returns_nodes() -> None:
    svc = TimeRailAppService()
    with patch(
        "app.application.modstore_local_client.modstore_get",
        new_callable=AsyncMock,
        return_value={"data": {"nodes": {"P1": {"status": "idle"}}}},
    ):
        data = await svc.runtime_status(node_id="P1")
    assert data["nodes"]["P1"]["status"] == "idle"


def test_get_time_rail_app_service_singleton() -> None:
    a = get_time_rail_app_service()
    b = get_time_rail_app_service()
    assert a is b
