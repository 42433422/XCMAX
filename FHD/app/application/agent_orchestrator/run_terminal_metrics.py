"""Count committed terminal run transitions, never memory-hook attempts."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.infrastructure.observability.metrics import observe_run_terminal

_TERMINAL = {"completed", "failed", "cancelled", "rejected"}
_PENDING = "agent_run_terminal_metrics"


def record_terminal_transition(run, previous, session=None):
    # Comparing the locked persisted status deduplicates repeat saves and CAS
    # retries, while allowing a genuinely restarted run to terminate again.
    if run.status not in _TERMINAL or (previous and previous.status == run.status):
        return
    if session is None:
        observe_run_terminal(status=run.status)
    else:
        session.info.setdefault(_PENDING, []).append(run.status)


@event.listens_for(Session, "after_commit")
def _after_commit(session):
    if not session.in_nested_transaction():
        for status in session.info.pop(_PENDING, []):
            observe_run_terminal(status=status)


@event.listens_for(Session, "after_rollback")
def _after_rollback(session):
    session.info.pop(_PENDING, None)
