"""Webhook target configuration routes for the ETL center."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.application.etl.service import get_etl_service
from app.db.session import get_db_dependency
from app.fastapi_routes.etl import (
    _error_boundary,
    _feature_gate,
    _read,
    _target_manage,
    _user_id,
)
from app.schemas.etl_schema import EtlTargetConfigRequest

router = APIRouter(
    prefix="/api/etl",
    tags=["etl"],
    dependencies=[Depends(_feature_gate), Depends(_error_boundary)],
)


@router.get("/targets")
def list_targets(
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_read),
):
    return {
        "success": True,
        "data": get_etl_service().list_target_configs(db, owner_user_id=_user_id(user)),
    }


@router.post("/targets", status_code=201)
def create_target(
    body: EtlTargetConfigRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_target_manage),
):
    return {
        "success": True,
        "data": get_etl_service().create_target_config(
            db,
            owner_user_id=_user_id(user),
            name=body.name,
            endpoint_url=body.endpoint_url,
            headers=body.headers,
            secret=body.secret,
        ),
    }


@router.put("/targets/{config_id}")
def update_target(
    config_id: str,
    body: EtlTargetConfigRequest,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_target_manage),
):
    return {
        "success": True,
        "data": get_etl_service().update_target_config(
            db,
            config_id=config_id,
            owner_user_id=_user_id(user),
            name=body.name,
            endpoint_url=body.endpoint_url,
            headers=body.headers,
            secret=body.secret,
        ),
    }


@router.delete("/targets/{config_id}", status_code=204)
def delete_target(
    config_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_target_manage),
):
    get_etl_service().delete_target_config(db, config_id=config_id, owner_user_id=_user_id(user))
    return JSONResponse(status_code=204, content=None)


@router.post("/targets/{config_id}/test")
def test_target(
    config_id: str,
    db: Session = Depends(get_db_dependency),
    user: Any = Depends(_target_manage),
):
    return {
        "success": True,
        "data": get_etl_service().target_config_for_test(
            db, config_id=config_id, owner_user_id=_user_id(user)
        ),
    }
