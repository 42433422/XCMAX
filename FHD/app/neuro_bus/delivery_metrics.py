"""Low-cardinality production delivery metrics for NeuroBus."""

from app.utils.operational_errors import RECOVERABLE_ERRORS


def record_delivery_metric(enabled: bool, outcome: str) -> None:
    """Record a bounded NeuroBus delivery outcome without affecting dispatch."""
    if not enabled:
        return
    try:
        from app.utils.metrics import (
            record_neurobus_dead_lettered,
            record_neurobus_lost,
            record_neurobus_published,
        )

        if outcome == "published":
            record_neurobus_published()
        elif outcome == "dead_lettered":
            record_neurobus_dead_lettered()
        elif outcome == "lost":
            record_neurobus_lost()
    except RECOVERABLE_ERRORS:
        pass
