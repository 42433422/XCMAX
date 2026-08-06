"""Auditable outcome for a scheduled self-maintenance loop with no safe source delta."""

LOOP_RUN_ID = "fc677d2b-1946-4bab-8779-d9d106381392"
LOOP_KIND = "scheduled_self_maintenance"
BRIDGE = "para_main_device"
UPDATED_AT = "2026-08-02T20:43:19+00:00"
NO_ACTION_REASON = (
    "Rejected PR #931 could not be updated because its old-base branch conflicted with main; "
    "its executable-change blocker consolidation and focused regression coverage are already "
    "present on main through PR #943 and later fail-closed Retort scope enforcement, while the "
    "current loop reports no remaining evidence gap. Reapplying the rejected diff would only "
    "duplicate superseded production logic."
)
