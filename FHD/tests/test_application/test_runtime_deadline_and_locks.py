"""Lock lifetime under concurrent callers; Codex deadline coverage lives at its runtime boundary."""

import time
from concurrent.futures import ThreadPoolExecutor

from app.application.agent_orchestrator import run_control


def test_operation_locks_reclaim_only_after_all_waiters_and_nested_owners_exit():
    active, peak = 0, 0

    def work(_):
        nonlocal active, peak
        with run_control.run_operation_lock("same"):
            with run_control.run_operation_lock("same"):
                active += 1
                peak = max(peak, active)
                time.sleep(0.001)
                active -= 1

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(32)))
    for index in range(1000):
        with run_control.run_operation_lock(str(index)):
            pass
    assert peak == 1 and not run_control._OPERATION_LOCKS
