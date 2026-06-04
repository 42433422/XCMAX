"""已废弃：请使用 print_app_service。"""
import warnings
from app.infrastructure.gateways.print import printer_service
warnings.warn("print_facade 已废弃", DeprecationWarning, stacklevel=2)
__all__ = ["printer_service"]
