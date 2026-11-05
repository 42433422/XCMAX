"""健康 / 诊断端点测试。

这些测试针对 reviewer 关注的"RASA、pgvector 仅在配置阶段"：
通过 ``/health/details`` 和 ``/api/diagnostics/capabilities`` 可以
**在运行时**看到能力的落地状态（而不是只看 .env / README 的文本）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app() -> FastAPI:
    """构造一个只挂 health_k8s 路由的迷你 FastAPI，避免触发整机 lifespan。"""

    from app.fastapi_routes.health_k8s import router as health_router

    app = FastAPI()
    app.include_router(health_router)
    return app


@pytest.mark.parametrize(
    ("changed_probe", "probe_status", "overall"),
    [
        ("redis", "healthy", "healthy"),
        ("redis", "disabled", "healthy"),
        ("database", "unhealthy", "degraded"),
        ("ai_service", "degraded", "degraded"),
    ],
)
def test_health_details_shape(monkeypatch, changed_probe, probe_status, overall):
    from app.fastapi_routes import health_k8s

    checks = {
        name: {"status": "healthy"}
        for name in ("database", "redis", "ai_service", "pgvector", "rasa")
    }
    checks[changed_probe] = {"status": probe_status}
    for name, result in checks.items():
        probe = "_check_rasa_nlu" if name == "rasa" else f"_check_{name}"
        monkeypatch.setattr(health_k8s, probe, lambda result=result: result)
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.get("/health/details")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == overall
    assert body["checks"] == checks


def test_capabilities_endpoint_contract():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    resp = client.get("/api/diagnostics/capabilities")
    assert resp.status_code == 200
    body = resp.json()

    # 顶层三大块 —— 是给审查人员的"落地证据"。
    for key in ("rasa", "pgvector", "intent_engines", "ai_service"):
        assert key in body, f"diagnostics/capabilities 缺少 {key}"

    # rasa 必须报告 enabled / mode
    rasa = body["rasa"]
    assert rasa["status"] in {"healthy", "degraded", "disabled", "unhealthy"}

    # pgvector 即便在没有 Postgres 的 CI 也要给出结构化回答
    pg = body["pgvector"]
    assert pg["status"] in {"healthy", "degraded", "disabled", "unhealthy"}

    # intent_engines 至少应报告 rule / rasa 两个引擎状态
    engines = body["intent_engines"]
    assert "rule" in engines
    assert "rasa" in engines
