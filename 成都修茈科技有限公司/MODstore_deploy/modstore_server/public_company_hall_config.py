"""Shared constants for the public company-hall projection."""

from __future__ import annotations

DEPARTMENT_ORDER = (
    "ops_acquisition",
    "ops_partner",
    "prod_web",
    "prod_mod",
    "prod_software",
    "shared_retention",
)

DEPARTMENT_COLORS = {
    "ops_acquisition": "#22d3ee",
    "ops_partner": "#4ade80",
    "prod_web": "#fb923c",
    "prod_mod": "#a78bfa",
    "prod_software": "#facc15",
    "shared_retention": "#79c0ff",
}

LINE_TO_DEPT = {
    "P-W": "prod_web",
    "P-S": "prod_software",
    "P-App": "prod_software",
    "P-M": "prod_mod",
    "S-R": "shared_retention",
    "O-A": "ops_acquisition",
    "O-B": "ops_partner",
}

WORKING_STATUSES = frozenset({"open", "dispatched", "in_progress"})
DONE_STATUSES = frozenset({"merged", "closed"})
