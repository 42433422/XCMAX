"""兼容 re-export：SSOT 在 domains/xcmax_admin/routes.py。"""
from app.fastapi_routes._domain_shim import lazy_domain_shim

_ns = lazy_domain_shim("app.fastapi_routes.domains.xcmax_admin.routes")
__getattr__ = _ns["__getattr__"]
__dir__ = _ns["__dir__"]
