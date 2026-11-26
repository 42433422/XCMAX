#!/usr/bin/env python3
"""Read-only PostgreSQL evidence for the *real* customer batch-delete preflight.

This is not a customer-business reconciliation or a substitute for B31 originals.
The existing application path is called with a real tenant-scoped SQLAlchemy
session. A read-only transaction and a before-execute write guard are both
mandatory. Missing 1k/10k tenant data, associations, plans, or measurements
fail closed rather than silently substituting SQLite or generated rows.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, exc, text
from sqlalchemy.orm import Session

FHD = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FHD))

from app.application.customer_deletion import delete_customers
from app.infrastructure.tenant_scope import tenant_scope

SIZES = (1000, 10000)
WRITE_STARTS = ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "ALTER", "DROP", "CREATE")


class EvidenceBlocked(RuntimeError):
    """A required independent test precondition or piece of evidence is missing."""


def _read_only(connection):
    connection.exec_driver_sql(
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    )
    connection.exec_driver_sql("SET LOCAL statement_timeout = '15000ms'")


def _samples(engine, tenant_id):
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            _read_only(conn)
            rows = conn.execute(
                text(
                    "SELECT id FROM purchase_units WHERE tenant_id = :tenant_id "
                    "ORDER BY id LIMIT 10000"
                ),
                {"tenant_id": tenant_id},
            ).scalars().all()
            if len(rows) < max(SIZES):
                raise EvidenceBlocked(
                    "fewer than 10000 existing customers for this authorized tenant"
                )
            samples = {}
            for size in SIZES:
                ids = rows[:size]
                # The real delete preflight must reject before attempting a write.
                # Both association paths mirror customer_deletion.delete_customers.
                linked = conn.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM purchase_units pu WHERE pu.tenant_id = :tenant_id "
                        "AND pu.id = ANY(:ids) AND ("
                        "EXISTS (SELECT 1 FROM products p WHERE p.tenant_id = pu.tenant_id "
                        "AND p.unit = pu.unit_name) OR "
                        "EXISTS (SELECT 1 FROM shipment_records s "
                        "WHERE s.tenant_id = pu.tenant_id AND "
                        "(s.unit_id = pu.id OR "
                        "(s.unit_id IS NULL AND s.purchase_unit = pu.unit_name)))"
                        "))"
                    ),
                    {"tenant_id": tenant_id, "ids": ids},
                ).scalar_one()
                if not linked:
                    raise EvidenceBlocked(
                        f"no associated customer in {size}-record sample; "
                        "unsafe to call deletion preflight"
                    )
                samples[size] = ids
            return samples
        finally:
            transaction.rollback()


def _summarize_plan(raw):
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise EvidenceBlocked("PostgreSQL did not return a JSON explain plan")
    root = raw[0].get("Plan")
    if not isinstance(root, dict):
        raise EvidenceBlocked("PostgreSQL JSON explain plan is incomplete")
    indexes = []

    def walk(node):
        if node.get("Index Name"):
            indexes.append(node["Index Name"])
        for child in node.get("Plans", []):
            walk(child)

    walk(root)
    return {
        "node": root.get("Node Type"),
        "estimated_cost": root.get("Total Cost"),
        "estimated_rows": root.get("Plan Rows"),
        "indexes": sorted(set(indexes)),
    }


def _probe(engine, tenant_id, ids):
    observed = []
    plans = {}
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            _read_only(conn)

            def observe(_conn, _cursor, statement, params, _context, _many):
                start = statement.lstrip().upper()
                if start.startswith(WRITE_STARTS):
                    raise EvidenceBlocked("application attempted a write during read-only preflight")
                observed.append((statement, params))

            event.listen(conn, "before_cursor_execute", observe)
            try:
                start = time.perf_counter_ns()
                with tenant_scope(tenant_id), Session(bind=conn, autoflush=False) as session:
                    result = delete_customers(session, ids, force=False)
                duration_ms = (time.perf_counter_ns() - start) / 1_000_000
            finally:
                event.remove(conn, "before_cursor_execute", observe)

            if result.get("success") is not False or not result.get("has_associations"):
                raise EvidenceBlocked("preflight did not reject a linked-customer batch")
            if not result.get("affected_units") or result.get("deleted_count") != 0:
                raise EvidenceBlocked("preflight receipt lacks denied associations")
            explained_sql = set()
            for sql, params in observed:
                normalized = sql.lstrip().upper()
                if not normalized.startswith("SELECT"):
                    continue
                if "pg_catalog" in sql or "information_schema" in sql:
                    continue
                if not any(table in sql.lower() for table in (
                    "purchase_units", "products", "shipment_records"
                )):
                    continue
                # Never serialize SQL or parameters: both can contain client names.
                label = (
                    "customers" if "purchase_units" in sql.lower()
                    else "products" if "products" in sql.lower()
                    else "shipments"
                )
                if sql in explained_sql:
                    continue
                explained_sql.add(sql)
                # Both shipment GROUP BY variants must have their own plan.
                plan_key = f"query_{len(plans) + 1}_{label}"
                try:
                    raw = conn.exec_driver_sql(
                        "EXPLAIN (FORMAT JSON) " + sql, params
                    ).scalar_one()
                    plans[plan_key] = _summarize_plan(raw)
                except (exc.SQLAlchemyError, json.JSONDecodeError, EvidenceBlocked) as error:
                    raise EvidenceBlocked(
                        f"PostgreSQL EXPLAIN failed for {label}: {type(error).__name__}"
                    ) from None
            if len(plans) < 4:
                raise EvidenceBlocked("customer + product + two shipment query plans required")
            return {
                "elapsed_ms": round(duration_ms, 3),
                "sql_total": len(observed),
                "sql_selects": sum(
                    s.lstrip().upper().startswith("SELECT") for s, _ in observed
                ),
                "denied_association_count": len(result["affected_units"]),
                "plans": plans,
            }
        finally:
            transaction.rollback()


def _p95(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _verify_checkout_head(expected):
    """Bind the report to the actual checked-out Git commit, not an arbitrary CLI label."""
    try:
        probe = subprocess.run(
            ["git", "-C", str(FHD.parent), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EvidenceBlocked("actual Git checkout SHA unavailable") from None
    if probe.returncode != 0 or probe.stdout.strip() != expected:
        raise EvidenceBlocked("actual checkout HEAD does not match --head-sha")


def run(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.head_sha):
        raise EvidenceBlocked("--head-sha requires a real 40-digit Git commit SHA")
    if args.tenant_id <= 0 or args.runs < 2 or args.max_sql < 1 or args.max_p95_ms <= 0:
        raise EvidenceBlocked("invalid tenant/runs/budget; use positive explicit limits")
    dsn = os.environ.get(args.dsn_env, "")
    if not dsn:
        raise EvidenceBlocked("PostgreSQL DSN environment variable is missing")
    engine = create_engine(dsn, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise EvidenceBlocked("not a PostgreSQL engine: SQLite is not evidence")
    try:
        _verify_checkout_head(args.head_sha)
        with engine.connect() as conn:
            server_version = str(conn.exec_driver_sql("SHOW server_version").scalar_one())
        samples = _samples(engine, args.tenant_id)
        groups = []
        for size in SIZES:
            runs = [_probe(engine, args.tenant_id, samples[size]) for _ in range(args.runs)]
            p95 = round(_p95([run["elapsed_ms"] for run in runs]), 3)
            max_sql = max(run["sql_total"] for run in runs)
            missing_plans = any(not run["plans"] for run in runs)
            groups.append({
                "size": size,
                "runs": len(runs),
                "p95_ms": p95,
                "max_sql_total": max_sql,
                "max_sql_selects": max(run["sql_selects"] for run in runs),
                "min_denied_associations": min(
                    run["denied_association_count"] for run in runs
                ),
                "latency_samples_ms": [run["elapsed_ms"] for run in runs],
                "sql_count_samples": [run["sql_total"] for run in runs],
                "explain": runs[-1]["plans"],
                "status": "PASS" if (
                    p95 <= args.max_p95_ms
                    and max_sql <= args.max_sql
                    and not missing_plans
                ) else "FAIL",
            })
        return {
            "status": "PASS" if all(g["status"] == "PASS" for g in groups) else "FAIL",
            "scope": "real Postgres read-only customer batch-delete preflight; NOT business reconciliation",
            "head_sha": args.head_sha,
            "utc": datetime.now(UTC).isoformat(),
            "postgres_version": server_version,
            "budgets": {
                "max_sql_per_preflight": args.max_sql,
                "max_p95_ms": args.max_p95_ms,
            },
            "groups": groups,
        }
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-env", default="XCAGI_PG_BUDGET_DSN")
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--max-sql", type=int, required=True)
    parser.add_argument("--max-p95-ms", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = run(args)
    except (EvidenceBlocked, exc.SQLAlchemyError, ModuleNotFoundError, OSError) as error:
        # Do not leak DB URLs, customer names or raw exception strings.
        evidence = {
            "status": "BLOCKED",
            "reason_type": type(error).__name__,
            "reason": str(error) if isinstance(error, EvidenceBlocked) else "probe exception",
            "scope": "real PostgreSQL only; no synthetic fallback",
            "head_sha": args.head_sha,
            "utc": datetime.now(UTC).isoformat(),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"PostgreSQL customer query evidence: {evidence['status']}")
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
