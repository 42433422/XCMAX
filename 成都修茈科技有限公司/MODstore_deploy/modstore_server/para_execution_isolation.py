"""One supported repair profile; native sandbox admission remains in the worker."""

import os

HEADER_ONLY_PLATFORM_PROFILE = "srt-0.0.83-header-only-platform-v1"


def feedback_execution_kind(effects):
    if "customer_feedback" in effects:
        return "customer_feedback_repair"
    if "training_candidate" in effects:
        return "training_candidate_repair"
    return None


def feedback_executor_configured() -> bool:
    return (
        os.environ.get("DEVFLEET_FORCE_OPENCODE") == "1"
        and os.environ.get("MODSTORE_PARA_PLATFORM_POOL") == "1"
    )


def feedback_allocation_isolated(allocation) -> bool:
    return bool(
        feedback_executor_configured()
        and isinstance(allocation, dict)
        and allocation.get("status") == "admitted"
        and allocation.get("execution_isolation") == HEADER_ONLY_PLATFORM_PROFILE
        and not allocation.get("agent_plan_first")
    )
