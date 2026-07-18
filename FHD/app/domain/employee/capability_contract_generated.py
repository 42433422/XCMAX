"""Generated from config/employee_capability_contract.yaml; do not edit."""

from __future__ import annotations

CAPABILITY_SOURCE_SPECS = (
    (("employee", "capabilities"), "label", "description"),
    (("employee_config_v2", "cognition", "skills"), "name", "brief"),
)
CAPABILITY_MERGE_STRATEGY = "ordered_union_first_definition_wins"
CAPABILITY_KEY_NORMALIZATION = {
    "trim": True,
    "lowercase": True,
    "spaces_to_underscore": True,
}
