#!/usr/bin/env python3
"""Apply 20260601_llm_official_prices columns when alembic CLI is unavailable on the host."""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


def db_url() -> str:
    url = (os.environ.get("MODSTORE_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("MODSTORE_DATABASE_URL or DATABASE_URL required", file=sys.stderr)
        sys.exit(1)
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg2://" + url[len("postgresql+psycopg://") :]
    elif url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def col_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).fetchone()
    return row is not None


def main() -> None:
    engine = create_engine(db_url())
    with engine.begin() as conn:
        if not col_exists(conn, "llm_billing_settings", "official_markup_multiplier"):
            conn.execute(
                text(
                    "ALTER TABLE llm_billing_settings "
                    "ADD COLUMN official_markup_multiplier NUMERIC(8, 4)"
                )
            )
            print("added llm_billing_settings.official_markup_multiplier")

        for col, typ in (
            ("official_input_price_per_1k", "NUMERIC(12, 6)"),
            ("official_output_price_per_1k", "NUMERIC(12, 6)"),
            ("official_min_charge", "NUMERIC(12, 2)"),
            ("official_source", "VARCHAR(512)"),
            ("official_synced_at", "TIMESTAMP"),
        ):
            if not col_exists(conn, "ai_model_prices", col):
                conn.execute(text(f"ALTER TABLE ai_model_prices ADD COLUMN {col} {typ}"))
                print(f"added ai_model_prices.{col}")

        if col_exists(conn, "alembic_version", "version_num"):
            ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if ver in ("20260601_llm_billing_settings", "20260526_users_deleted_at", None):
                conn.execute(
                    text("UPDATE alembic_version SET version_num = '20260601_llm_official_prices'")
                )
                ver = "20260601_llm_official_prices"
            print("alembic_version:", ver)
        else:
            print("alembic_version table missing (skipped stamp)")


if __name__ == "__main__":
    main()
