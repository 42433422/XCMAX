"""Public market browsing, facets, bundles, details, and creator enrichment."""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query

from modstore_server.market_shared import (
    LICENSE_SCOPE_LABELS,
    MATERIAL_CATEGORY_LABELS,
    _catalog_item_payload,
    _get_current_user,
    _normalize_license_scope,
    _normalize_material_category,
    _optional_current_user,
)
from modstore_server.models import (
    CatalogItem,
    User,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.market_catalog_browse_routes_merged import (
    api_host_foundation_employee_pack_download as api_host_foundation_employee_pack_download,
    api_market_catalog as api_market_catalog,
    api_market_facets as api_market_facets,
    api_office_employee_pack_bundle as api_office_employee_pack_bundle,
    _enrich_catalog_creator_profile as _enrich_catalog_creator_profile,
    api_market_catalog_detail as api_market_catalog_detail,
    api_workflow_employee_pack_bundle as api_workflow_employee_pack_bundle,
)

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.market_catalog_api"]


router = _facade().router


