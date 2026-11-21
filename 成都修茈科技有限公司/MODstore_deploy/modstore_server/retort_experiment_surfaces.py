"""The two prompt surfaces with real, authenticated product consumers."""

from __future__ import annotations

import re

WORKFLOW_NL_RESOURCE = "workflow_nl_generator"
WORKFLOW_NL_MEASUREMENT = "workflow_generation_static_validation"


def surface_identity(lifecycle):
    """Bind approvals and concurrency to a registered consumer, not an arbitrary label."""
    surface = lifecycle.get("surface")
    if surface == "employee_prompt":
        resource = lifecycle.get("employee_id")
        if isinstance(resource, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resource):
            return surface, resource
    elif (
        surface == "workflow_nl_prompt"
        and lifecycle.get("resource_id") == WORKFLOW_NL_RESOURCE
        and not lifecycle.get("employee_id")
        and lifecycle.get("measurement_scope") == WORKFLOW_NL_MEASUREMENT
    ):
        # This shared generator serves many owners. The runtime separately binds
        # each observation to that authenticated owner's actual workflow ID.
        return surface, WORKFLOW_NL_RESOURCE
    raise ValueError("invalid_feedback_experiment_lifecycle")


def surface_lock_name(lifecycle):
    surface, resource = surface_identity(lifecycle)
    # Preserve the existing employee lock identity across mixed-version workers.
    suffix = resource if surface == "employee_prompt" else f"{surface}:{resource}"
    return "xcagi:experiment:" + suffix
