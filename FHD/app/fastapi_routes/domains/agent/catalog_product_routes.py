"""Explicit real mixed-catalog price surface; no ERP fallback or provisioning."""

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from app.application.agent_orchestrator.catalog_product_edit import create_edit, original
from app.fastapi_routes.domains.agent.route_support import run_response, success
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal
from app.mod_sdk.catalog_product_store import read_products, verify_operation
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/etl/owned-mixed-v1/products")


def unavailable():
    return JSONResponse(
        {
            "success": False,
            "outcome": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "message": "原目录、价格或操作不可核验；未重放修改，请核对原操作",
        },
        status_code=409,
    )


@router.get("")
def list_catalog_products(
    keyword: str = Query(default="", max_length=100),
    principal: AgentPrincipal = Depends(require_agent_principal),
):
    try:
        return {"success": True, **read_products(principal, keyword=keyword)}
    except RECOVERABLE_ERRORS:
        return unavailable()


@router.get("/edits/{operation_id}")
def lookup_catalog_edit(
    operation_id: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    try:
        run, claim, status = original(principal, operation_id)
        # Revalidate current mixed scope and barrier even when only returning a run.
        read_products(principal, product_id=claim["params"]["product_id"])
        return {
            **run_response(run, principal=principal),
            "operation": {
                "state": status,
                "operation_id": operation_id,
                "run_id": run.run_id,
                "request_digest": claim["request_digest"],
            },
        }
    except RECOVERABLE_ERRORS:
        return unavailable()


@router.get("/edits/{operation_id}/verification")
def verify_catalog_edit(
    operation_id: str, principal: AgentPrincipal = Depends(require_agent_principal)
):
    try:
        return success(verify_operation(principal, operation_id))
    except RECOVERABLE_ERRORS:
        return unavailable()


@router.post("/edits/{operation_id}/reconciliation")
def reconcile_catalog_edit(
    operation_id: str,
    body: dict = Body(...),
    principal: AgentPrincipal = Depends(require_agent_principal),
):
    try:
        if body != {"confirmed": True} or body.get("confirmed") is not True:
            raise ValueError("explicit original-operation reconciliation confirmation required")
        # Same original owner and current full WRITE grants; verify existing
        # source evidence only. This never dispatches or retries a source effect.
        return success(verify_operation(principal, operation_id, release=True))
    except RECOVERABLE_ERRORS:
        return unavailable()


@router.get("/{product_id}")
def get_catalog_product(
    product_id: int, principal: AgentPrincipal = Depends(require_agent_principal)
):
    try:
        return success(read_products(principal, product_id=product_id))
    except RECOVERABLE_ERRORS:
        return unavailable()


@router.post("/{product_id}/edits")
def post_catalog_edit(
    product_id: int,
    body: dict = Body(...),
    principal: AgentPrincipal = Depends(require_agent_principal),
):
    try:
        run = create_edit(principal, product_id, body)
        return JSONResponse(run_response(run, principal=principal), status_code=202)
    except RECOVERABLE_ERRORS:
        return unavailable()
