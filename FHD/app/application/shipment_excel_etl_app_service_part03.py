# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.shipment_excel_etl_app_service")


from app.application.shipment_excel_etl_app_service_part03_part01 import (
    parse_delivery_notes as parse_delivery_notes,
)
from app.application.shipment_excel_etl_app_service_part03_part01 import (
    preview_shipment_excel_etl as preview_shipment_excel_etl,
)
from app.application.shipment_excel_etl_app_service_part03_part02 import (
    _notes_to_product_records as _notes_to_product_records,
)
from app.application.shipment_excel_etl_app_service_part03_part02 import (
    execute_shipment_excel_etl as execute_shipment_excel_etl,
)
