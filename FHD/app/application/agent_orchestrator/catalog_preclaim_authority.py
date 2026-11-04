"""Signed preclaim authority: immutable identity and envelope validation only.

Persistence, source ownership and receipt readback remain with the orchestrator.
"""

import hmac

from app.application.agent_orchestrator.business_action_ledger import (
    _action_identity,
    canonical_hash,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.mod_sdk.catalog_product_store import TOOL

PRECLAIM_RECEIPT = "catalog_preclaim_finalization_v1"
PRECLAIM_STATES = {"resolving_no_effect", "finalized_no_effect"}


def signed_payload(envelope, signer):
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"payload", "proof"}
        or not isinstance(envelope["payload"], dict)
        or not isinstance(envelope["proof"], str)
        or not hmac.compare_digest(envelope["proof"], signer(envelope["payload"]))
    ):
        raise ValueError("original finalization signature differs")
    return envelope["payload"]


def fence_identity(claim, run, context):
    key, fingerprint = _action_identity(
        get_tool_action_spec(TOOL, claim["params"]["action"]),
        claim["params"],
        context,
    )
    token = (run.metadata.get("_tool_approval_grants") or {}).get(run.steps[0].step_id)
    if not token:
        raise ValueError("preclaim finalization requires original consumed approval")
    return {
        "receipt_kind": PRECLAIM_RECEIPT,
        "operation_key": claim["operation_key"],
        "operation_digest": claim["operation_digest"],
        "request_digest": claim["request_digest"],
        "binding": claim["binding"],
        "owner": claim["owner"],
        "run_id": claim["run_id"],
        "business_action_id": context["business_action_id"],
        "action_key": key,
        "fingerprint": fingerprint,
        "approval_digest": canonical_hash(token),
        "decision": "finalize_without_dispatch",
    }


def validate_fence(intent, expected):
    if (
        set(intent) != set(expected) | {"resolution_id", "revision"}
        or any(intent.get(key) != value for key, value in expected.items())
        or not isinstance(intent["resolution_id"], str)
        or len(intent["resolution_id"]) != 32
        or any(char not in "0123456789abcdef" for char in intent["resolution_id"])
        or not isinstance(intent["revision"], str)
        or len(intent["revision"]) != 64
        or any(char not in "0123456789abcdef" for char in intent["revision"])
    ):
        raise ValueError("original preclaim finalization identity differs")
    return intent
