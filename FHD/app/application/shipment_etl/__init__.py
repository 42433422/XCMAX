"""Deprecated path: use ``app.application.shipment_elt``."""

from app.compat.elt_import_aliases import alias_module

alias_module(
    __name__,
    "app.application.shipment_elt",
    (
        "assistance",
        "batching",
        "catalog",
        "directory_listing",
        "fingerprints",
        "importing",
        "layout",
        "metadata",
        "notes",
        "persistence",
        "protocols",
        "sheets",
        "workbook",
        "writing",
    ),
)
