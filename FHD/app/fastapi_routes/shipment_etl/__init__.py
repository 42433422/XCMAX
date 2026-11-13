"""Deprecated path: use ``app.fastapi_routes.shipment_elt``."""

from app.compat.elt_import_aliases import alias_module

alias_module(
    __name__,
    "app.fastapi_routes.shipment_elt",
    ("history", "imports", "ocr", "responses", "templates", "uploads"),
)
