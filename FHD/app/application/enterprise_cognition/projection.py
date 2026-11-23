"""Permission-scoped materialized reads with authoritative expiry and event invalidation."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.models.enterprise_cognition import (
    EnterpriseEventCursor,
    EnterpriseStateProjection,
)
from app.domain.enterprise_cognition.catalog import definition_for
from app.domain.enterprise_cognition.world_observation import (
    historical_observation,
    public_snapshot,
    record_observation,
)
from app.http.request_context import (
    reset_current_http_request,
    set_current_http_request,
)
from app.infrastructure.auth.enterprise_scope import SourceScope
from app.infrastructure.enterprise_cognition_sources import AuthorityReader
from app.infrastructure.tenant_scope import owned_tenant_scope
from app.request_active_mod_ctx import (
    get_request_active_mod_id,
    normalize_active_mod_id,
    reset_request_active_mod_id,
    set_request_active_mod_id,
)

logger = logging.getLogger(__name__)


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat()


def _conditions(model, scope, entity_type, entity_id):
    return (
        model.tenant_id == scope.tenant_id,
        model.mod_id == scope.mod_id,
        model.entity_type == entity_type,
        model.entity_id == entity_id,
    )


class ProjectionService:
    def __init__(self, session_factory=None, reader=None, clock=None):
        if session_factory is None:
            from app.db import HostSessionLocal

            # Derived state belongs to the host; customer Mod stores are read-only
            # authorities and never need these projection or cursor tables.
            session_factory = HostSessionLocal
        self.session_factory = session_factory
        self.reader = reader or AuthorityReader()
        self.clock = clock or time.time

    def _cursor(self, db, scope, entity_type, entity_id):
        statement = (
            select(EnterpriseEventCursor)
            .where(*_conditions(EnterpriseEventCursor, scope, entity_type, entity_id))
            .with_for_update()
        )
        cursor = db.scalar(statement)
        if cursor is None:
            try:
                with db.begin_nested():
                    cursor = EnterpriseEventCursor(
                        tenant_id=scope.tenant_id,
                        mod_id=scope.mod_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        generation=0,
                        event_id="",
                        event_at=0,
                        source="",
                    )
                    db.add(cursor)
                    db.flush()
            except IntegrityError:
                cursor = db.scalar(statement)
                if cursor is None:
                    raise
        return cursor

    def get(
        self,
        entity_type: str,
        entity_id: str,
        *,
        tenant_id,
        actor_id: str,
        force_refresh: bool = False,
        mod_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        definition = definition_for(entity_type)
        if isinstance(tenant_id, bool):
            raise PermissionError("enterprise_identity_required")
        scope = SourceScope(
            int(tenant_id),
            str(actor_id),
            get_request_active_mod_id() if mod_id is None else mod_id,
        )
        scope.validate()
        entity_id = str(entity_id).strip()
        if not entity_id or len(entity_id) > 160:
            raise ValueError("enterprise_entity_id_required")
        if definition.id_field == "id":
            if not entity_id.isascii() or not entity_id.isdigit() or int(entity_id) <= 0:
                raise ValueError("enterprise_entity_id_invalid")
            entity_id = str(int(entity_id))
        base = {
            "tenant_id": str(scope.tenant_id),
            "actor_id": scope.actor_id,
            "mod_id": scope.mod_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source": definition.source,
            "read_only": True,
        }
        try:
            # Always revalidate live RBAC, even when a cached projection is fresh.
            self.reader.authorize(scope, definition)
            with owned_tenant_scope(scope.tenant_id), self.session_factory() as db:
                if not self.reader.visible(db, definition, scope, entity_id):
                    return self._unknown(base, "source_not_visible_or_missing")
                cursor = self._cursor(db, scope, entity_type, entity_id) if as_of is None else None
                row = db.scalar(
                    select(EnterpriseStateProjection)
                    .where(
                        *_conditions(EnterpriseStateProjection, scope, entity_type, entity_id),
                        EnterpriseStateProjection.actor_id == scope.actor_id,
                    )
                    .with_for_update()
                )
                if as_of is not None:
                    if row is None:
                        return self._unknown(base, "no_observation_at_cutoff")
                    try:
                        return {**base, **historical_observation(row.snapshot_json, as_of, base)}
                    except (ValueError, KeyError, TypeError):
                        return self._unknown(base, "observation_history_unavailable")
                assert cursor is not None
                started = self.clock()
                if (
                    not force_refresh
                    and row is not None
                    and row.expires_at > started
                    and row.observed_at <= started
                    and row.generation == cursor.generation
                ):
                    try:
                        cached = json.loads(row.snapshot_json)
                        if isinstance(cached, dict) and all(
                            cached.get(key) == value for key, value in base.items()
                        ):
                            return {**public_snapshot(cached), "retrieved_from": "projection"}
                    except ValueError:
                        logger.warning("enterprise derived snapshot invalid; querying authority")
                authority = self.reader.read(db, definition, scope, entity_id)
                if authority is None:
                    return self._unknown(base, "source_not_visible_or_missing")
                observed = self.clock()
                canonical = json.dumps(
                    authority,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                digest = hashlib.sha256(canonical.encode()).hexdigest()
                expires = observed + definition.ttl_seconds
                result = {
                    **base,
                    **authority,
                    "freshness": "fresh",
                    "source_version": "sha256:" + digest,
                    "version_kind": "content_sha256",
                    "observed_at": _iso(observed),
                    "expires_at": _iso(expires),
                    "retrieved_from": "authority",
                    "last_event_id": cursor.event_id or None,
                    "evidence": [
                        {
                            "source": definition.source,
                            "table": definition.source,
                            "row_id": entity_id,
                            "tenant_id": str(scope.tenant_id),
                            "actor_id": scope.actor_id,
                            "mod_id": scope.mod_id,
                            "observed_at": _iso(observed),
                            "content_sha256": digest,
                            "version_kind": "content_sha256",
                        }
                    ],
                }
                try:
                    stored, conflict = record_observation(
                        row.snapshot_json if row is not None else None, result
                    )
                except (ValueError, KeyError, TypeError):
                    return self._unknown(base, "observation_history_unavailable")
                if row is None:
                    row = EnterpriseStateProjection(
                        tenant_id=scope.tenant_id,
                        actor_id=scope.actor_id,
                        mod_id=scope.mod_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                    )
                    db.add(row)
                row.snapshot_json = json.dumps(stored, ensure_ascii=False, allow_nan=False)
                row.observed_at = observed
                row.expires_at = 0 if conflict else expires
                row.generation = cursor.generation
                db.commit()
                if conflict:
                    return self._unknown(base, "conflicting_observation_order")
                return public_snapshot(result)
        except SQLAlchemyError:
            logger.warning("enterprise projection authority or storage unavailable", exc_info=True)
            return self._unknown(base, "authority_or_projection_unavailable")

    @staticmethod
    def _unknown(base: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            **base,
            "freshness": "unknown",
            "knowledge_kind": "unknown",
            "state": {},
            "source_version": None,
            "source_last_changed": None,
            "observed_at": None,
            "expires_at": None,
            "evidence": [],
            "reason_code": reason,
        }

    def list_refs(
        self,
        entity_type: str,
        *,
        tenant_id,
        actor_id: str,
        mod_id: str | None = None,
        limit: int = 20,
    ) -> dict:
        definition = definition_for(entity_type)
        if isinstance(tenant_id, bool):
            raise PermissionError("enterprise_identity_required")
        scope = SourceScope(
            int(tenant_id),
            str(actor_id),
            get_request_active_mod_id() if mod_id is None else mod_id,
        )
        scope.validate()
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("enterprise_limit_out_of_range")
        try:
            self.reader.authorize(scope, definition)
            with owned_tenant_scope(scope.tenant_id), self.session_factory() as db:
                return {
                    **self.reader.list_refs(db, definition, scope, limit),
                    "freshness": "fresh",
                    "observed_at": _iso(self.clock()),
                }
        except SQLAlchemyError:
            logger.warning("enterprise reference query unavailable", exc_info=True)
            return {
                "refs": [],
                "freshness": "unknown",
                "has_more": None,
                "source": definition.source,
                "reason_code": "authority_unavailable",
            }

    def invalidate(
        self,
        *,
        tenant_id: int,
        mod_id: str,
        entity_type: str,
        entity_id: str,
        event_id: str,
        event_at: float,
        source: str,
    ) -> bool:
        """Internal subscriber: only expire projections; event values never become facts."""
        definition_for(entity_type)
        if (
            type(tenant_id) is not int
            or tenant_id <= 0
            or not entity_id
            or len(entity_id) > 160
            or not event_id
            or len(event_id) > 96
        ):
            return False
        if not 0 < event_at <= self.clock() + 300:
            return False
        scope = SourceScope(tenant_id, "0", mod_id)
        with self.session_factory() as db:
            cursor = self._cursor(db, scope, entity_type, entity_id)
            if cursor.event_id == event_id or cursor.event_at > event_at:
                return False
            cursor.generation += 1
            cursor.event_id = event_id
            cursor.event_at = event_at
            cursor.source = source[:160]
            db.execute(
                update(EnterpriseStateProjection)
                .where(*_conditions(EnterpriseStateProjection, scope, entity_type, entity_id))
                .values(expires_at=0)
            )
            db.commit()
            return True


def get_projection_service() -> ProjectionService:
    return ProjectionService()


@lru_cache(maxsize=1)
def subscription_catalog() -> tuple[dict, ...]:
    path = Path(__file__).resolve().parents[3] / "config" / "neuro_bus_events.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(document["enterprise_subscriptions"]["subscriptions"])


def consume_entity_event(event, *, service=None) -> bool:
    """Invalidate scoped projections; event payloads cannot dispatch business actions."""
    entry = next(
        (item for item in subscription_catalog() if item["event_type"] == event.event_type),
        None,
    )
    if entry is None:
        return False
    payload = event.payload
    if not isinstance(payload, dict):
        return False
    tenant = payload.get("tenant_id")
    if isinstance(tenant, bool) or not str(tenant or "").isdigit() or int(str(tenant)) <= 0:
        return False
    # A missing Mod identity must never invalidate a host projection by default.
    if "mod_id" not in payload:
        return False
    mod_id = payload["mod_id"]
    if not isinstance(mod_id, str) or normalize_active_mod_id(mod_id) != mod_id:
        return False
    entity_type = str(entry.get("entity_type") or payload.get("entity_type") or "")
    try:
        definition = definition_for(entity_type)
    except (ValueError, TypeError):
        return False
    source = payload.get("source_table")
    if entry.get("require_source") and source != definition.source:
        return False
    entity_id = str(payload.get(entry["id_field"]) or "")
    token = set_request_active_mod_id(mod_id)
    request_token = set_current_http_request(None)
    try:
        return (service or get_projection_service()).invalidate(
            tenant_id=int(str(tenant)),
            mod_id=mod_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_id=str(event.metadata.event_id),
            event_at=float(event.metadata.timestamp),
            source=definition.source,
        )
    finally:
        reset_current_http_request(request_token)
        reset_request_active_mod_id(token)


def register_enterprise_subscriptions(bus) -> int:
    if getattr(bus, "_enterprise_projection_subscriptions", None) is not None:
        return len(bus._enterprise_projection_subscriptions)
    handles = [
        bus.subscribe(item["event_type"], consume_entity_event, is_async=False)
        for item in subscription_catalog()
    ]
    bus._enterprise_projection_subscriptions = handles
    from app.infrastructure.enterprise_cognition_events import install_source_observer

    install_source_observer()
    return len(handles)
