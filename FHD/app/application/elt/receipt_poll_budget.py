"""Process-local admission for optional receipt polling, never execution admission.

At most eight callers (two per tenant) wait proactively in each server process.
Denied callers retain their accepted receipt and use normal read reconciliation.
This does not bound worker threads during knowledge ingestion or across processes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)
GLOBAL_LIMIT = 8
TENANT_LIMIT = 2
_LOCK = threading.Lock()
_active = 0
_tenants: dict[int, int] = {}


@contextmanager
def admit(tenant_id: int) -> Iterator[bool]:
    """Never queue behind another tenant; release even for cancellation/BaseException."""
    global _active
    with _LOCK:
        accepted = _active < GLOBAL_LIMIT and _tenants.get(tenant_id, 0) < TENANT_LIMIT
        if accepted:
            _active += 1
            _tenants[tenant_id] = _tenants.get(tenant_id, 0) + 1
    if not accepted:
        logger.debug("ELT receipt polling deferred: process or tenant budget exhausted")
    try:
        yield accepted
    finally:
        if accepted:
            with _LOCK:
                _active -= 1
                remaining = _tenants[tenant_id] - 1
                if remaining:
                    _tenants[tenant_id] = remaining
                else:
                    del _tenants[tenant_id]
