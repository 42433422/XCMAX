"""Dormant storage claims, not business authorization or execution success.

Public API: claim, record_receipt, mark_unknown. There is intentionally no finish
or reconcile API: no reviewed verifier can promote these receipts to completed.
Every existing claim remains non-replayable, including identical receipts.
Revocation after a claim can prevent receipt persistence; the retained claim stays
uncertain. Marking unknown before recording evidence rejects later nonempty receipts;
"{}" is only the existing storage marker, not proof that no effect occurred. This
API is not an end-to-end crash/revocation durability guarantee.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.db.models.agent_business_action import AgentBusinessActionRecord as Record
from app.db.models.agent_business_action import validate_ledger_storage
from app.infrastructure.auth.agent_mod_scope import _bound_actor

_RESERVED = frozenset(
    {
        "user_id",
        "userId",
        "actor_id",
        "tenant_id",
        "mod_id",
        "active_mod_id",
        "_runtime_context",
        "_actor_authorization",
        "_mod_authorization",
        "local_user_id",
        "authenticated_local_user_id",
        "business_action_id",
    }
)


class LedgerClaimError(ValueError):
    """The storage identity, ownership or immutable evidence did not match."""


@dataclass(frozen=True)
class StorageClaim:
    action_key: str
    owner: str
    fingerprint: str


def canonical_hash(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _json(value) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _reject_overrides(value) -> None:
    if isinstance(value, dict):
        if _RESERVED.intersection(value):
            raise LedgerClaimError("parameters cannot supply storage identity")
        for child in value.values():
            _reject_overrides(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_overrides(child)


def _scope(context: dict) -> dict:
    actor = _bound_actor(context)  # Rechecks real server session; no ID-only principal.
    identity = str(context.get("business_action_id") or "").strip()
    if not identity or len(identity) > 256:
        raise LedgerClaimError("stable business_action_id required")
    return {
        "tenant_id": str(context.get("tenant_id") or ""),
        "user_id": str(actor.id),
        "mod_id": str((context.get("_mod_authorization") or {}).get("mod_id") or ""),
        "business_action_id": identity,
    }


def _action_identity(spec, params, context):
    """Pure identity derivation; callers separately validate current/historical authority."""
    key = canonical_hash(
        [
            str(context.get("tenant_id") or ""),
            str((context.get("_mod_authorization") or {}).get("mod_id") or ""),
            str(context.get("business_action_id") or ""),
        ]
    )
    return key, canonical_hash(
        [
            str(context.get("user_id") or ""),
            spec.owner_mod_id,
            spec.tool_id,
            spec.action,
            spec.version,
            params,
        ]
    )


def _unknown() -> dict:
    return {
        "success": False,
        "outcome": "unknown",
        "retryable": False,
        "dispatch_authorized": False,
        "reconciliation_required": True,
        "error_code": "business_action_verification_required",
    }


class BusinessActionLedger:
    """Real host storage only; obtaining a claim never authorizes a tool effect."""

    def __init__(self, session_factory=None):
        self._runs = SQLAlchemyAgentRunRepository(
            session_factory=session_factory, auto_create=False
        )

    def claim(self, tool_id: str, action: str, params: dict, context: dict):
        if not isinstance(params, dict):
            raise LedgerClaimError("parameters must be an object")
        _reject_overrides(params)
        scope = _scope(context)
        spec = get_tool_action_spec(tool_id, action)
        if (
            spec is None
            or spec.read_only
            or not spec.version
            or spec.owner_mod_id
            or spec.availability != "shared"
            or spec.tool_id in {"employee", "execute_erp_capability"}
        ):
            # Existing host specs only. Owned/dynamic actions need reviewed owner
            # admission; reads never need a durable write claim.
            raise LedgerClaimError("action has no supported host storage claim contract")
        key = canonical_hash([scope["tenant_id"], scope["mod_id"], scope["business_action_id"]])
        fingerprint = canonical_hash(
            [scope["user_id"], spec.owner_mod_id, spec.tool_id, spec.action, spec.version, params]
        )
        claim = StorageClaim(key, uuid.uuid4().hex, fingerprint)
        now = utc_now_iso()
        try:
            with self._runs.transaction() as db:
                validate_ledger_storage(db)
                if spec.tool_id == "catalog_products_v1":
                    from app.application.agent_orchestrator.catalog_product_edit import (
                        fresh_claim_guard,
                    )

                    if not fresh_claim_guard(db, params, context):
                        return None, _unknown()
                db.add(
                    Record(
                        action_key=key,
                        fingerprint=fingerprint,
                        owner=claim.owner,
                        tool_id=spec.tool_id,
                        action=spec.action,
                        **scope,
                        run_id=str(context.get("run_id") or ""),
                        state="claimed",
                        receipt_json="{}",
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
        except IntegrityError:
            with self._runs.transaction(read_only=True) as db:
                validate_ledger_storage(db)
                record = db.get(Record, key)
                if record is None:
                    raise
                if record.fingerprint != fingerprint or any(
                    getattr(record, k) != v for k, v in scope.items()
                ):
                    raise LedgerClaimError("business action identity conflicts") from None
                return None, _unknown()
        return claim, None

    @staticmethod
    def _query(db, claim: StorageClaim, scope: dict):
        return db.query(Record).filter_by(
            action_key=claim.action_key, owner=claim.owner, fingerprint=claim.fingerprint, **scope
        )

    def record_receipt(self, claim: StorageClaim, receipt: dict, context: dict) -> dict:
        if not isinstance(receipt, dict):
            raise LedgerClaimError("receipt must be an object")
        encoded = _json(receipt)
        scope = _scope(context)
        with self._runs.transaction() as db:
            validate_ledger_storage(db)
            query = self._query(db, claim, scope)
            changed = query.filter_by(state="claimed", receipt_json="{}").update(
                {
                    "receipt_json": encoded,
                    "state": "verification_required",
                    "updated_at": utc_now_iso(),
                },
                synchronize_session=False,
            )
            if changed != 1:
                row = query.one_or_none()
                if row is None or row.state not in {"verification_required", "unknown"}:
                    raise LedgerClaimError("claim ownership or state changed")
                if _json(json.loads(row.receipt_json)) != encoded:
                    raise LedgerClaimError("a different receipt cannot replace immutable evidence")
        return _unknown()

    def mark_unknown(self, claim: StorageClaim, context: dict) -> dict:
        scope = _scope(context)
        with self._runs.transaction() as db:
            validate_ledger_storage(db)
            changed = (
                self._query(db, claim, scope)
                .filter(Record.state.in_(["claimed", "verification_required", "unknown"]))
                .update(
                    {"state": "unknown", "updated_at": utc_now_iso()}, synchronize_session=False
                )
            )
            if changed != 1:
                raise LedgerClaimError("claim ownership or state changed")
        return _unknown()
