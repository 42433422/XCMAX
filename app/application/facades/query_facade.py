"""已废弃：请使用 query_app_service。"""
import warnings
from app.infrastructure.gateways import query as _gw
warnings.warn("query_facade 已废弃", DeprecationWarning, stacklevel=2)
find_product = _gw.find_product
find_purchase_unit = _gw.find_purchase_unit
get_product_names = _gw.get_product_names
get_purchase_units = _gw.get_purchase_units
query_service = _gw.query_service
__all__ = list(_gw.__all__)
