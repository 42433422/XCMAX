"""
System API Routes - FastAPI Implementation

Provides endpoints for:
- GET /api/system/industries - List all available industries
- GET /api/system/industry - Get current industry profile
- POST /api/system/industry - Set current industry
- GET /api/system/industry/{industry_id} - Get specific industry profile

行业数据优先级（2026-04 调整）：
    已加载 Mod 的 manifest.industry 声明 > resources/config/industry_config.yaml

Mod 在 manifest.json 顶层声明 ``"industry": {"id": "...", "name": "...", ...}``
即把该行业注入可用集合；YAML 仅作为无 Mod 环境的开发/回退配置。详见
resources/config/industry_config.py::_mod_industries_dict 与
app/infrastructure/mods/manifest.py::ModMetadata.industry。
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


class IndustryResponse(BaseModel):
    id: str
    name: str
    code: str
    description: str = ""
    config: Dict[str, Any] = {}


class IndustriesListData(BaseModel):
    industries: list
    current: str


class IndustryData(BaseModel):
    industry: Dict[str, Any]


class SetIndustryRequest(BaseModel):
    industry_id: str


def _build_industry_response(industry_id: str, profile: Any) -> Dict[str, Any]:
    """Build industry response dict from profile object"""
    return {
        "id": industry_id,
        "name": profile.name,
        "code": industry_id,
        "description": profile.name,
        "config": {
            "units": profile.units,
            "quantity_fields": profile.quantity_fields,
            "product_fields": profile.product_fields,
            "order_types": profile.order_types,
            "print_config": profile.print_config,
        }
    }


@router.get("/industries")
async def get_industries():
    """Get list of all available industries"""
    try:
        from resources.config.industry_config import (
            get_available_industries,
            get_current_industry,
            get_industry_profile,
        )

        industries = get_available_industries()
        current = get_current_industry()

        result_industries = []
        for ind in industries:
            profile = get_industry_profile(ind["id"])
            result_industries.append(_build_industry_response(ind["id"], profile))

        return {
            "success": True,
            "data": {
                "industries": result_industries,
                "current": current,
            }
        }
    except Exception as e:
        logger.error(f"Failed to get industries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry")
async def get_current_industry_endpoint():
    """Get current industry profile"""
    try:
        from resources.config.industry_config import (
            get_current_industry,
            get_industry_profile,
        )

        current_id = get_current_industry()
        profile = get_industry_profile(current_id)

        return {
            "success": True,
            "data": _build_industry_response(current_id, profile)
        }
    except Exception as e:
        logger.error(f"Failed to get current industry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/industry")
async def set_industry_endpoint(request: SetIndustryRequest):
    """Set current industry"""
    try:
        from resources.config.industry_config import (
            set_current_industry,
            get_industry_profile,
        )

        success = set_current_industry(request.industry_id)
        if not success:
            raise HTTPException(status_code=400, detail=f"Unknown industry: {request.industry_id}")

        profile = get_industry_profile(request.industry_id)

        return {
            "success": True,
            "data": _build_industry_response(request.industry_id, profile)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set industry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry/{industry_id}")
async def get_industry_detail(industry_id: str):
    """Get specific industry profile"""
    try:
        from resources.config.industry_config import (
            get_available_industries,
            get_industry_profile,
        )

        available = get_available_industries()
        industry_ids = [ind["id"] for ind in available]

        if industry_id not in industry_ids:
            raise HTTPException(status_code=404, detail=f"Industry not found: {industry_id}")

        profile = get_industry_profile(industry_id)

        return {
            "success": True,
            "data": _build_industry_response(industry_id, profile)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get industry {industry_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))