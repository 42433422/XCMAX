"""Deprecated path: use ``app.db.models.shipment_elt_fingerprint``."""

from app.compat.elt_import_aliases import alias_module

alias_module(__name__, "app.db.models.shipment_elt_fingerprint")
