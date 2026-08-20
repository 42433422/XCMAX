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

logger = logging.getLogger(__name__)


def _facade() -> Any:
    return sys.modules["modstore_server.market_catalog_api"]


router = _facade().router


from modstore_server.market_catalog_browse_routes_part01 import (
    api_host_foundation_employee_pack_download as api_host_foundation_employee_pack_download,
)
from modstore_server.market_catalog_browse_routes_part01 import (
    api_market_catalog as api_market_catalog,
)
from modstore_server.market_catalog_browse_routes_part01 import (
    api_market_facets as api_market_facets,
)
from modstore_server.market_catalog_browse_routes_part01 import (
    api_office_employee_pack_bundle as api_office_employee_pack_bundle,
)
from modstore_server.market_catalog_browse_routes_part02 import (
    _enrich_catalog_creator_profile as _enrich_catalog_creator_profile,
)
from modstore_server.market_catalog_browse_routes_part02 import (
    api_market_catalog_detail as api_market_catalog_detail,
)
from modstore_server.market_catalog_browse_routes_part02 import (
    api_workflow_employee_pack_bundle as api_workflow_employee_pack_bundle,
)
