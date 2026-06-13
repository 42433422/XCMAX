"""DB connection pool sizing helpers for Tier C deployments."""

from __future__ import annotations

import os


def pool_config_from_env() -> dict[str, int]:
    return {
        "pool_size": int(os.environ.get("XCAGI_DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("XCAGI_DB_MAX_OVERFLOW", "10")),
    }


def estimate_total_connections(
    *,
    pods: int,
    workers_per_pod: int,
    pool_size: int,
    max_overflow: int,
) -> int:
    """Worst-case connections per process = pool_size + max_overflow."""
    per_process = pool_size + max_overflow
    return pods * workers_per_pod * per_process


def recommend_pool_for_pg(
    *,
    pods: int,
    workers_per_pod: int,
    pg_max_connections: int = 100,
    reserve: int = 20,
) -> dict[str, int]:
    """Split available PG connections across API pods."""
    budget = max(1, pg_max_connections - reserve)
    per_pod = max(1, budget // max(1, pods))
    per_worker = max(1, per_pod // max(1, workers_per_pod))
    pool_size = max(2, min(10, per_worker - 2))
    max_overflow = max(2, per_worker - pool_size)
    return {"pool_size": pool_size, "max_overflow": max_overflow}
