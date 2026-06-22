"""Table-driven constants for tool spec derivation.

These tables replace scattered magic values previously hard-coded in
``tool_spec.py`` (``_cost_units``, ``_special_permission``,
``_aiopen_tool_risk`` and the dataclass defaults). Behaviour is kept
exactly equivalent to the original branch logic.
"""

from __future__ import annotations

# --- dataclass / build defaults -------------------------------------------
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_RETRY: dict[str, int] = {"max_attempts": 0}

# --- cost units -----------------------------------------------------------
DEFAULT_LOW_RISK_COST = 1
DEFAULT_COST = 2
# (tool_id, action) -> fixed cost, takes precedence over risk-based cost.
TOOL_ACTION_COST_OVERRIDES: dict[tuple[str, str], int] = {
    ("aiopen", "chat"): 2,
    ("employee", "execute"): 5,
    ("business_db", "write"): 2,
}

# --- permissions ----------------------------------------------------------
# tool_ids that derive permission as ``f"{tool_id}.{action}"`` (bare prefix)
# instead of the generic ``f"tool.{tool_id}.{action}"`` fallback.
PERMISSION_BARE_PREFIX_TOOLS: frozenset[str] = frozenset({"aiopen", "business_db", "employee"})
# dataset_rag: read-style actions -> dataset.read, everything else dataset.write
DATASET_RAG_READ_ACTIONS: frozenset[str] = frozenset({"query", "diff_versions"})
DATASET_RAG_READ_PERMISSION = "dataset.read"
DATASET_RAG_WRITE_PERMISSION = "dataset.write"
# tool_id -> fixed permission string (action-independent).
PERMISSION_OVERRIDES: dict[str, str] = {
    "memory_v2": "memory_v2.write",
}

# --- aiopen risk ----------------------------------------------------------
# actions that are low-risk and idempotent; everything else is medium/non-idempotent.
AIOPEN_LOW_RISK_ACTIONS: frozenset[str] = frozenset({"api_catalog", "ui_sessions", "ui_snapshot"})
AIOPEN_DEFAULT_RISK = "medium"
AIOPEN_LOW_RISK = "low"
