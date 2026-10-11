"""Durable reservation shared by document generation and next-number routes."""

import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text

from app.db import get_runtime_engine
from app.utils.path_io.path_utils import get_shipment_output_dir


def _historical_sequence(value: str, period: str) -> int:
    match = re.search(r"(\d{2})-(\d{2})-(\d+)[A-Z]", value)
    if not match:
        match = re.search(r"(\d{2})-(\d{2})00(\d+)[A-Z]", value)
    return int(match[3]) if match and f"{match[1]}-{match[2]}" == period else 0


def reserve_order_number(
    suffix: str = "A", *, now: datetime | None = None, output_dir: str | None = None
) -> dict:
    """Commit a reservation before returning it; allocation errors must propagate."""
    suffix = str(suffix or "").strip().upper()
    if not re.fullmatch(r"[A-Z]", suffix):
        suffix = "A"
    period = (now or datetime.now()).strftime("%y-%m")
    engine = get_runtime_engine()
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS shipment_number_sequences "
                "(period VARCHAR(5) PRIMARY KEY, sequence INTEGER NOT NULL)"
            )
        )
        # Import existing durable numbers, never count product rows. File names
        # also cover documents whose legacy order persistence was unavailable.
        seed = max(
            (
                _historical_sequence(p.stem, period)
                for p in Path(output_dir or get_shipment_output_dir()).glob("*.xlsx")
            ),
            default=0,
        )
        schema = inspect(conn)
        for table in ("orders", "shipment_orders", "sales_orders"):
            if schema.has_table(table) and "order_number" in {
                c["name"] for c in schema.get_columns(table)
            }:
                seed = max(
                    seed,
                    max(
                        (
                            _historical_sequence(str(row[0]), period)
                            for row in conn.execute(text(f"SELECT order_number FROM {table}"))
                        ),
                        default=0,
                    ),
                )
        sequence = conn.execute(
            text(
                "INSERT INTO shipment_number_sequences (period, sequence) VALUES (:period, :seed) "
                "ON CONFLICT (period) DO UPDATE SET sequence = "
                "CASE WHEN shipment_number_sequences.sequence < :floor THEN :seed "
                "ELSE shipment_number_sequences.sequence + 1 END RETURNING sequence"
            ),
            {"period": period, "seed": seed + 1, "floor": seed},
        ).scalar_one()
    return {
        "order_number": f"{period}-{sequence:05d}{suffix}",
        "sequence": sequence,
        "year_month": period,
    }
