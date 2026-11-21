"""Exercise the production read-only reader against native PostgreSQL JSONB rows."""

from __future__ import annotations

import json
import os
import secrets
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from modstore_server import llm_key_resolver
from modstore_server import llm_usage_readback as source
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_usage_reconciliation as recovery
from tests import test_strategic_usage_reconciliation as native

database = native.database
pytestmark = pytest.mark.skipif(
    not os.environ.get("RETORT_TEST_POSTGRES_DSN"), reason="isolated PostgreSQL required"
)


@pytest.fixture
def pg_ledger(database, monkeypatch):
    suffix = uuid4().hex
    schema, role, password = f"usage_{suffix}", f"usage_reader_{suffix}", secrets.token_hex(24)
    original_url = make_url(os.environ["RETORT_TEST_POSTGRES_DSN"])
    admin = create_engine(original_url, poolclass=NullPool)
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
            # The production reader supplies its own libpq options, including
            # statement_timeout. A private role search_path isolates fresh
            # connections without patching that transport or a shared schema.
            connection.execute(text(f'ALTER ROLE "{role}" SET search_path TO "{schema}"'))
            connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
            # Native LiteLLM 1.109.3 proxy/schema.prisma accounting event shape.
            connection.execute(
                text(
                    f'CREATE TYPE "{schema}"."AccountingEventKind" AS ENUM '
                    "('inbound_usage', 'outbound_usage', 'cost')"
                )
            )
            connection.execute(
                text(
                    f'CREATE TABLE "{schema}"."LiteLLM_AccountingEvent" ('
                    'event_id TEXT PRIMARY KEY, kind "'
                    + schema
                    + '"."AccountingEventKind" NOT NULL, source_event_id TEXT, '
                    "schema_version INTEGER NOT NULL, payload_hash TEXT NOT NULL, "
                    "occurred_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL DEFAULT now(), "
                    "payload JSONB NOT NULL)"
                )
            )
            # INSERT permission proves that the tested rejection comes from
            # the production read-only transaction, rather than missing ACLs.
            connection.execute(
                text(f'GRANT SELECT, INSERT ON "{schema}"."LiteLLM_AccountingEvent" TO "{role}"')
            )
        created = True
        url = original_url.set(
            drivername="postgresql+psycopg2", username=role, password=password
        ).render_as_string(hide_password=False)
        monkeypatch.setenv("MODSTORE_LITELLM_ACCOUNTING_DATABASE_URL", url)
        monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        monkeypatch.setattr(llm_key_resolver, "platform_api_key", lambda _: "sk-native-test-only")
        monkeypatch.setattr(
            llm_key_resolver, "platform_base_url", lambda _: "https://gateway.test/v1"
        )
        decision_id, task, held, binding = native.admit(database)
        yield SimpleNamespace(
            admin=admin,
            schema=schema,
            url=url,
            decision_id=decision_id,
            task=task,
            held=held,
            binding=binding,
        )
    finally:
        try:
            if created:
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                    connection.execute(text(f'DROP ROLE "{role}"'))
        finally:
            admin.dispose()


def persist(ledger, events):
    from litellm.accounting import InboundUsageEvent, OutboundUsageEvent
    from litellm.proxy.db.accounting_ledger import _prepare

    with ledger.admin.begin() as connection:
        for item in events:
            model = InboundUsageEvent if item["kind"] == "inbound_usage" else OutboundUsageEvent
            # Let the real upstream serializer validate and hash its envelope.
            event = model.model_validate_json(json.dumps(item["payload"]["event"]))
            accepted = _prepare(event, (), json.dumps(item["payload"]), 1, 1)
            connection.execute(
                text(
                    f'INSERT INTO "{ledger.schema}"."LiteLLM_AccountingEvent" '
                    "(event_id, kind, source_event_id, schema_version, payload_hash, occurred_at, payload) "
                    f'VALUES (:event_id, CAST(:kind AS "{ledger.schema}"."AccountingEventKind"), '
                    ":source_event_id, :schema_version, :payload_hash, :occurred_at, CAST(:payload AS JSONB))"
                ),
                {
                    "event_id": accepted.event_id,
                    "kind": accepted.kind.value,
                    "source_event_id": accepted.source_event_id,
                    "schema_version": accepted.schema_version,
                    "payload_hash": accepted.payload_hash,
                    "occurred_at": accepted.occurred_at,
                    "payload": accepted.payload,
                },
            )


def test_postgres_late_native_pair_settles_original_call_once(pg_ledger, monkeypatch):
    ledger = pg_ledger
    runtime._finish(ledger.task, {"ok": True, "status": "completed"}, 1)
    events = native.upstream_events(ledger.binding)
    unrelated = deepcopy(events)
    for item in unrelated:
        item["payload"]["event"]["request_id"] = "another-original-request"
        item["payload"]["event"]["event_id"] += "-unrelated"
    persist(ledger, [*unrelated, events[0]])
    assert source.read_usage(ledger.binding) is None
    assert recovery.reconcile_pending_usage()["settled"] == 0
    saved = portfolio.portfolio_status(ledger.decision_id)["tasks"]["a"]
    assert saved["calls"][ledger.held["request_id"]]["status"] == "unknown"

    persist(ledger, events[1:])
    result = source.read_usage(ledger.binding)
    assert result["usage"]["total_tokens"] == 19
    assert result["readback"]["binding_sha256"] == portfolio.digest(ledger.binding)
    assert set(result["readback"]["event_ids"]) == {item["event_id"] for item in events}
    monkeypatch.setattr(runtime, "_execute", lambda *_: pytest.fail("replayed employee"))
    assert recovery.reconcile_pending_usage()["settled"] == 1
    saved = portfolio.portfolio_status(ledger.decision_id)["tasks"]["a"]
    assert saved["status"] == "completed" and saved["actual_tokens"] == 19
    assert recovery.reconcile_pending_usage()["settled"] == 0
    assert runtime.run_portfolio_cycle(ledger.decision_id)["processed"] == 0


@pytest.mark.parametrize("corruption", ["estimated", "other_key", "extra_attempt"])
def test_postgres_invalid_accounting_retains_unknown_liability(pg_ledger, corruption):
    ledger = pg_ledger
    events = native.upstream_events(ledger.binding)
    if corruption == "estimated":
        events[1]["payload"]["usage_source"] = "estimated"
    elif corruption == "other_key":
        for item in events:
            next(
                dimension
                for dimension in item["payload"]["event"]["dimensions"]
                if dimension["name"] == "key"
            )["value"] = "another-gateway-credential"
    else:
        extra = deepcopy(events[1])
        extra["payload"]["event"]["event_id"] = "another-provider-attempt"
        extra["payload"]["event"]["attempt_id"] = "another-provider-attempt"
        events.append(extra)
    persist(ledger, events)
    assert source.read_usage(ledger.binding) is None
    assert recovery.reconcile_pending_usage()["settled"] == 0
    call = portfolio.portfolio_status(ledger.decision_id)["tasks"]["a"]["calls"][
        ledger.held["request_id"]
    ]
    assert call["status"] == "unknown" and "actual_tokens" not in call


def test_postgres_production_transport_is_read_only_and_has_native_timeouts(pg_ledger):
    engine = source._accounting_engine(pg_ledger.url)
    try:
        assert isinstance(engine.pool, NullPool)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == pg_ledger.schema
            assert connection.scalar(text("SHOW transaction_read_only")) == "on"
            assert connection.scalar(text("SHOW statement_timeout")) == "3s"
            assert (
                connection.connection.driver_connection.get_dsn_parameters()["connect_timeout"]
                == "3"
            )
            with pytest.raises(DBAPIError) as blocked:
                connection.execute(
                    text("INSERT INTO \"LiteLLM_AccountingEvent\" (event_id) VALUES ('forbidden')")
                )
            assert blocked.value.orig.pgcode == "25006"
        with engine.connect() as connection:
            with pytest.raises(DBAPIError) as timeout:
                connection.execute(text("SELECT pg_sleep(5)"))
            assert timeout.value.orig.pgcode == "57014"
    finally:
        engine.dispose()
