"""Domain-isolation guardrails.

The plan eventually splits the FastAPI monolith into multiple processes
(notification first, then knowledge, LLM, OpenAPI connectors, employees,
workflow). Once those services live in separate runtimes, the only legal
cross-module wiring is via:

* HTTP clients
* Domain events (NeuroBus + outbox)

The tests below pin a small but high-leverage subset of those rules to the
current monolith so refactors do not accidentally re-introduce the
``directly call into another domain`` shortcut. They are deliberately
narrower than ``test_neuro_ddd_boundaries`` because the legacy ``*_api``
modules are still allowed to live next to each other while we move them
under proper packages.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modstore_server"


def _read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def test_payment_api_does_not_import_notification_service_directly():
    """Payment domain must publish events, not call notification side-effects.

    The notification subscriber lives in ``eventing/subscribers.py`` and
    listens for ``payment.paid`` / ``refund.*``. Bypassing it from
    ``payment_api`` defeats the decoupling and prevents a future
    notification microservice from owning user-facing copy.
    """

    text = _read("payment_api.py")
    if not text:
        return
    assert "from modstore_server.notification_service" not in text, (
        "payment_api must not import notification_service directly; publish "
        "domain events and let eventing.subscribers handle the notification."
    )


def test_refund_api_does_not_import_notification_service_directly():
    text = _read("refund_api.py")
    if not text:
        return
    assert "from modstore_server.notification_service" not in text, (
        "refund_api must publish domain events; refund notifications belong "
        "in eventing.subscribers."
    )


def test_eventing_subscribers_owns_notification_imports():
    """Subscribers module should be the single import site for the
    cross-cutting notification helper inside the eventing package.
    """

    text = _read("eventing/subscribers.py")
    assert "from modstore_server.notification_service" in text


def test_eventing_package_does_not_import_business_apis():
    """Reverse direction is illegal: the eventing layer must stay below the
    application layer. No ``from modstore_server.payment_api import ...``
    inside ``eventing/``.
    """

    forbidden_prefixes = (
        "from modstore_server.payment_api",
        "from modstore_server.refund_api",
        "from modstore_server.market_api",
        "from modstore_server.workflow_api",
        "from modstore_server.employee_api",
    )
    eventing = ROOT / "eventing"
    offenders: list[str] = []
    for path in eventing.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden_prefixes:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} imports {token}")
    assert offenders == []


def test_new_domain_port_modules_stay_below_application_layer():
    """DDD domain/*/ports.py must not reach up into FastAPI routers."""

    for rel in (
        "domain/analytics/ports.py",
        "domain/auth/ports.py",
        "domain/catalog/ports.py",
        "domain/employee/ports.py",
        "domain/knowledge/ports.py",
        "domain/llm/ports.py",
        "domain/market/ports.py",
        "domain/payment_gateway/ports.py",
        "domain/refund/ports.py",
        "domain/wallet/ports.py",
        "domain/workflow/ports.py",
    ):
        text = _read(rel)
        if not text:
            continue
        assert "from modstore_server.market_api" not in text
        assert "from fastapi" not in text


def test_outbox_does_not_couple_to_specific_domain_models():
    """The outbox table is a generic envelope. Pulling in payment / employee
    SQLAlchemy models inside ``db_outbox.py`` would re-couple it to the
    monolith and block per-service deployment.
    """

    text = _read("eventing/db_outbox.py")
    forbidden = (
        "from modstore_server.models import PaymentOrder",
        "from modstore_server.models import Employee",
        "from modstore_server.models import Notification",
    )
    for needle in forbidden:
        assert (
            needle not in text
        ), f"db_outbox.py should not import domain-specific models; saw {needle}"
