# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.tools_workflow_registered")


from app.services.tools_workflow_registered_part01_part01 import (
    _registered_router_customers as _registered_router_customers,
)
from app.services.tools_workflow_registered_part01_part01 import (
    _registered_router_materials as _registered_router_materials,
)
from app.services.tools_workflow_registered_part01_part01 import (
    _registered_router_normal_slot_dispatch as _registered_router_normal_slot_dispatch,
)
from app.services.tools_workflow_registered_part01_part01 import (
    _registered_router_products as _registered_router_products,
)
from app.services.tools_workflow_registered_part01_part02 import (
    _registered_router_finance as _registered_router_finance,
)
from app.services.tools_workflow_registered_part01_part02 import (
    _registered_router_inventory as _registered_router_inventory,
)
from app.services.tools_workflow_registered_part01_part02 import (
    _registered_router_purchase as _registered_router_purchase,
)
from app.services.tools_workflow_registered_part01_part02 import (
    _registered_router_reports as _registered_router_reports,
)
from app.services.tools_workflow_registered_part01_part02 import (
    _registered_router_sales as _registered_router_sales,
)
