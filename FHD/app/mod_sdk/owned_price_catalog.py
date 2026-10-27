"""Explicit fresh tenant/Mod SQL price catalog; never reroute or adopt ERP data."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from enum import Enum
from pathlib import Path

from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.ddl import sort_tables

from app.db.models.customer import Customer
from app.db.models.etl import EtlTemplate, EtlTemplateVersion, EtlUpload
from app.db.models.owned_source import EtlPriceDimension, ProductPriceHistory
from app.db.models.product import Product, UomCategory, UomUnit
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SalesOrder, SalesOrderItem
from app.db.models.shipment import ShipmentRecord
from app.db.models.workflow import WorkflowPlan
from app.desktop_runtime import database_generation_registry as generations
from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_dataset_access_context
from app.mod_sdk.owner_workspace import owner_workspace

# Full existing ERP model definitions, including tables queried by rollback's
# logical-reference guards and their complete FK closure. No placeholder tables.
CATALOG_MODELS = (
    Product,
    ProductPriceHistory,
    EtlPriceDimension,
    PurchaseUnit,
    UomCategory,
    UomUnit,
    EtlUpload,
    WorkflowPlan,
    ShipmentRecord,
    SalesOrder,
    SalesOrderItem,
    Customer,
)


class CatalogPurpose(Enum):
    """Server-selected capability, never parsed from request/runtime context."""

    ETL = "etl"
    READ = "read"


def catalog_path(tenant_id: str, mod_id: str, *, mixed=False) -> Path:
    if not isinstance(tenant_id, str) or not re.fullmatch(r"[1-9][0-9]*", tenant_id):
        raise ValueError("positive canonical tenant identity required")
    return owner_workspace(mod_id, owner_id="tenant:" + tenant_id).file_path(
        "mixed-catalog.sqlite3" if mixed else "price-catalog.sqlite3"
    )


def _context(principal, *, provisioning=False, mixed=False, purpose=CatalogPurpose.ETL):
    from app.fastapi_routes.domains.agent.route_support import authenticated_runtime_context
    from app.infrastructure.auth.agent_principal import AgentPrincipal

    if not isinstance(principal, AgentPrincipal) or not isinstance(purpose, CatalogPurpose):
        raise ValueError("authenticated owner required")
    required = {"etl.execute", "product.edit"}
    if mixed:
        required |= {"dataset.read", "dataset.write", "etl.template.manage"}
    if purpose is CatalogPurpose.READ:
        if provisioning:
            raise ValueError("read purpose cannot provision a catalog")
        required = {"product.view", "dataset.read"}
    context = authenticated_runtime_context({}, principal)
    actor = _bound_actor(context)
    access = agent_dataset_access_context(context)
    if (
        str(actor.tenant_id) != principal.tenant_id
        or not context.get("mod_id")
        or not required <= access.permissions
        or (provisioning and actor.role != "admin")
    ):
        raise ValueError("current tenant catalog authorization required")
    return context


def _schema(*, mixed=False):
    ddl = dialect()
    result = {}
    models = CATALOG_MODELS + ((EtlTemplate, EtlTemplateVersion) if mixed else ())
    for table in sort_tables([model.__table__ for model in models]):
        result[("table", table.name)] = str(CreateTable(table).compile(dialect=ddl))
        for index in sorted(table.indexes, key=lambda item: item.name):
            result[("index", index.name)] = str(CreateIndex(index).compile(dialect=ddl))
    return result


def validate_price_catalog(conn: sqlite3.Connection, *, mixed=False):
    """Validate full real schema on the caller's actual effect connection."""
    actual = {
        (kind, name): sql.strip()
        for kind, name, sql in conn.execute(
            "SELECT type,name,sql FROM main.sqlite_master WHERE sql IS NOT NULL "
            "AND substr(name,1,7) != 'sqlite_' AND NOT "
            "(type='table' AND name IN ('etl_owned_source','etl_database_generation'))"
        )
    }
    if (
        actual != {key: sql.strip() for key, sql in _schema(mixed=mixed).items()}
        or conn.execute("PRAGMA foreign_key_check").fetchone()
        or conn.execute(
            "SELECT 1 FROM temp.sqlite_master WHERE type IN ('table','view','trigger') LIMIT 1"
        ).fetchone()
    ):
        raise generations.GenerationObservationError("owned price catalog schema changed")


def provision_owned_price_catalog(
    principal, *, confirmed=False, mixed=False
) -> generations.OwnedSource:
    """Create an empty, separate catalog only by explicit authenticated admin intent."""
    context = _context(principal, provisioning=True, mixed=mixed)
    if confirmed is not True:
        raise ValueError("explicit fresh catalog provisioning confirmation required")
    generations.require_owned_source_profile()
    target = catalog_path(context["tenant_id"], context["mod_id"], mixed=mixed)
    target.parent.mkdir(parents=True, exist_ok=True)

    def initialize(conn):
        validate_price_catalog(conn, mixed=True) if mixed else validate_price_catalog(conn)
        if mixed:
            from app.application.dataset_rag.owned_store import initialize_mixed_store

            initialize_mixed_store(conn, target)

    return generations.enroll_owned_source(
        target,
        context,
        [(sql, ()) for sql in _schema(mixed=mixed).values()],
        validate_schema=initialize,
    )


def validate_catalog_scope(
    principal,
    target: Path,
    source: generations.OwnedSource,
    *,
    mixed=False,
    purpose=CatalogPurpose.ETL,
):
    """Recheck scope within the caller's real target lock; never recursively acquire it."""
    generations._owned_lock(target, None)
    context = _context(principal, mixed=mixed, purpose=purpose)
    if (
        target != catalog_path(context["tenant_id"], context["mod_id"], mixed=mixed)
        or (source.tenant_id, source.mod_id) != (context["tenant_id"], context["mod_id"])
        or generations.read_owned_source(target) != source
    ):
        raise generations.GenerationObservationError("original price catalog scope changed")


def resolve_owned_price_catalog(
    principal, *, mixed=False, purpose=CatalogPurpose.ETL, lock_timeout=0
) -> tuple[Path, generations.OwnedSource]:
    """No query-time creation, adoption, caller path, or fallback to shared ERP."""
    context = _context(principal, mixed=mixed, purpose=purpose)
    target = catalog_path(context["tenant_id"], context["mod_id"], mixed=mixed)
    with generations.target_database_lock(target, lock_timeout=lock_timeout):
        source = generations.read_owned_source(target)
        if (source.tenant_id, source.mod_id) != (context["tenant_id"], context["mod_id"]):
            raise generations.GenerationObservationError("price catalog ownership changed")
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as conn:
            generations.validate_owned_source(conn, target, source)
            validate_price_catalog(conn, mixed=mixed)
    return target, source
