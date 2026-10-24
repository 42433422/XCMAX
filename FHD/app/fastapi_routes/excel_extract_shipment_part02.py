"""兼容入口：canonical 位于 domains.excel.excel_extract_shipment_part02。"""
from __future__ import annotations

import sys

from app.fastapi_routes.domains.excel import excel_extract_shipment_part02 as _canonical

sys.modules[__name__] = _canonical
