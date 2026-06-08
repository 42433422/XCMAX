"""Standalone FastAPI app for the notification bounded context.

This file lets the notification domain run as its own process while still
sharing the same Python codebase. It mirrors what an extracted
microservice would expose:

* HTTP API at ``/api/notifications`` (already covered by
  :mod:`modstore_server.api.notification`).
* ``/healthz`` health check distinct from the monolith's ``/health``.
* Domain event subscribers wired on startup so the service consumes the
  same NeuroBus events as the monolith. When this is moved to a separate
  process, the subscribers will instead read from a webhook receiver or
  message broker bound to the same contracts.

Run with::

    uvicorn modstore_server.api.notification_service_app:app

Tests use this factory to assert the service does not pull in unrelated
domains (payment, employee, llm, etc.) — see
``tests/test_notification_service_app.py``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from modstore_server.api.notification import router as notification_router
from modstore_server.eventing.subscribers import install_default_subscribers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        install_default_subscribers()
    except Exception:
        logger.exception("notification service failed to install subscribers")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MODstore Notification Service",
        version="0.1.0",
        description=(
            "通知域独立服务样板。"
            " 复用 ``modstore_server.application.notification`` 用例与 ``api.notification`` 路由，"
            " 通过 NeuroBus 订阅 ``payment.paid`` / ``refund.*`` 等事件触发通知。"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )

    app.include_router(notification_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "notification"}

    return app


app = create_app()


__all__ = ["app", "create_app"]
