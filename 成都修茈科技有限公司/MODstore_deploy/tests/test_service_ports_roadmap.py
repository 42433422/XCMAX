"""Pin the cross-service port roadmap.

The plan splits the FastAPI monolith in this order:

1. Notification (already migrated to a dedicated bounded context)
2. Knowledge / RAG
3. LLM gateway
4. OpenAPI connectors
5. Employee + Workflow
6. Payment residual

Each future microservice has a corresponding ``services/<name>.py`` port
that calls the in-process implementation today and will swap to an HTTP
adapter tomorrow. This test pins:

* All five ports exist with their public symbols.
* Each port module is *cheap* to import — no SQLAlchemy / FastAPI / httpx
  pulled into the import side-effect graph. That is essential because
  every domain re-imports ``modstore_server.services`` and we don't want
  one slow domain to drag the whole startup with it.
* Setting and getting the default client is symmetric and process-wide.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PORT_MODULES = (
    "modstore_server.services.notification",
    "modstore_server.services.knowledge",
    "modstore_server.services.llm",
    "modstore_server.services.openapi_connector",
    "modstore_server.services.employee",
    "modstore_server.services.workflow",
)


@pytest.mark.parametrize("module_name", PORT_MODULES)
def test_each_port_module_imports_cleanly(module_name):
    module = importlib.import_module(module_name)
    assert hasattr(module, "__all__"), f"{module_name} should expose __all__"


@pytest.mark.parametrize("module_name", PORT_MODULES)
def test_port_module_defines_get_and_set_default(module_name):
    module = importlib.import_module(module_name)
    suffix = module_name.rsplit(".", 1)[-1]
    aliases = {
        "openapi_connector": "connector",
    }
    accessor_name = aliases.get(suffix, suffix)
    assert hasattr(
        module, f"get_default_{accessor_name}_client"
    ), f"{module_name} should expose get_default_{accessor_name}_client"
    assert hasattr(
        module, f"set_default_{accessor_name}_client"
    ), f"{module_name} should expose set_default_{accessor_name}_client"


def test_services_package_does_not_import_heavy_modules_at_load():
    """Importing :mod:`modstore_server.services` must not eagerly pull in
    SQLAlchemy models, FastAPI routers or business modules. The check is
    indirect: we make sure none of the domain implementation modules are
    in ``sys.modules`` solely because of importing the services package.
    """

    # Drop any cached imports that may already have been added by other tests.
    for mod in list(sys.modules):
        if mod.startswith("modstore_server.services"):
            del sys.modules[mod]
    for forbidden in (
        "modstore_server.payment_api",
        "modstore_server.refund_api",
        "modstore_server.employee_api",
        "modstore_server.market_api",
        "modstore_server.knowledge_v2_api",
        "modstore_server.openapi_connector_api",
    ):
        sys.modules.pop(forbidden, None)

    importlib.import_module("modstore_server.services")

    for forbidden in (
        "modstore_server.payment_api",
        "modstore_server.refund_api",
        "modstore_server.market_api",
        "modstore_server.knowledge_v2_api",
        "modstore_server.openapi_connector_api",
    ):
        assert forbidden not in sys.modules, (
            f"importing modstore_server.services must not eagerly load "
            f"{forbidden}; that would re-couple every domain."
        )


def test_port_modules_avoid_direct_orm_or_http_imports_at_top_level():
    forbidden = ("import sqlalchemy", "import fastapi", "import httpx")
    services_dir = Path(__file__).resolve().parents[1] / "modstore_server" / "services"
    offenders: list[str] = []
    for path in services_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Only check top-level statements before the first ``def``/``class``.
        head = text.split("\nclass ", 1)[0].split("\ndef ", 1)[0]
        for token in forbidden:
            if token in head:
                offenders.append(f"{path.name} top-level imports {token}")
    assert offenders == []


def test_set_and_get_default_client_round_trips_for_notification():
    from modstore_server import services

    sentinel = object()
    services.set_default_notification_client(sentinel)  # type: ignore[arg-type]
    try:
        assert services.get_default_notification_client() is sentinel
    finally:
        services.set_default_notification_client(None)
