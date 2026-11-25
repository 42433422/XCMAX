#!/usr/bin/env python3
"""Fail-closed PostgreSQL historical upgrade and representative ERP data check.

Runs only against the named disposable CI database. This checks real PostgreSQL
and Alembic; it does not certify a customer database dump or all business rows.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "2026_06_22_baseline"
DATABASE_NAME = "xcagi_migration_test"


def _test_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    parsed = sa.engine.make_url(url)
    if (
        os.environ.get("XCMAX_MIGRATION_TEST_ONLY") != "1"
        or parsed.get_backend_name() != "postgresql"
        or parsed.database != DATABASE_NAME
        or parsed.host not in {"127.0.0.1", "localhost"}
    ):
        raise RuntimeError("refusing_non_disposable_postgresql_migration_test")
    return url


def _config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


def _sentinel_digest(engine: sa.Engine) -> tuple[str, dict[str, int]]:
    queries = {
        "users": "SELECT id, username, password, tenant_id FROM users "
        "WHERE username = 'migration-history-proof'",
        "preferences": "SELECT id, user_id, preference_key, preference_value "
        "FROM user_preferences WHERE preference_key = 'migration-history-proof'",
        "customers": "SELECT id, tenant_id, customer_name, credit_limit, "
        "credit_used FROM customers WHERE customer_name = 'migration-history-proof'",
        "financial_transactions": "SELECT id, tenant_id, transaction_type, amount, "
        "currency, status FROM financial_transactions WHERE id = 42107",
        "sales_orders": "SELECT id, tenant_id, order_no, state, payment_state, "
        "total_amount, paid_amount FROM sales_orders "
        "WHERE order_no = 'migration-history-proof'",
        "journal_entries": "SELECT id, tenant_id, entry_no, status, debit_total, "
        "credit_total FROM journal_entries "
        "WHERE entry_no = 'migration-history-proof'",
    }
    with engine.connect() as db:
        rows = {
            name: [dict(row) for row in db.execute(sa.text(query)).mappings()]
            for name, query in queries.items()
        }
    counts = {name: len(entries) for name, entries in rows.items()}
    if any(count != 1 for count in counts.values()):
        raise AssertionError(f"missing_erp_upgrade_sentinel counts={counts}")
    encoded = json.dumps(rows, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest(), counts


def main() -> None:
    url = _test_database_url()
    config = _config()
    engine = sa.create_engine(url)
    try:
        # Do not drop/truncate a database that already contains tables.
        if sa.inspect(engine).get_table_names():
            raise RuntimeError("migration_test_database_must_be_empty")
        command.upgrade(config, BASELINE)

        # A real committed historical row in each representative domain is
        # carried through every subsequent Alembic revision to current head.
        from decimal import Decimal

        from app.db.models.accounting import JournalEntry
        from app.db.models.customer import Customer
        from app.db.models.finance import FinancialTransaction
        from app.db.models.ai import UserPreference
        from app.db.models.sales import SalesOrder
        from app.db.models.user import User

        with Session(engine) as db:
            db.add_all(
                [
                    User(
                        username="migration-history-proof",
                        password="!" + os.urandom(32).hex(),
                        tenant_id=421,
                    ),
                    UserPreference(
                        user_id="tenant:421",
                        preference_key="migration-history-proof",
                        preference_value='{"kept":true,"balance":"1.20"}',
                    ),
                    Customer(
                        id=42106,
                        tenant_id=421,
                        customer_name="migration-history-proof",
                        credit_limit=Decimal("300.00"),
                        credit_used=Decimal("40.00"),
                    ),
                    FinancialTransaction(
                        id=42107,
                        tenant_id=421,
                        transaction_type="income",
                        amount=Decimal("12.40"),
                        currency="CNY",
                    ),
                    SalesOrder(
                        tenant_id=421,
                        order_no="migration-history-proof",
                        state="quote",
                        invoice_status="not_invoiced",
                        payment_state="unpaid",
                    ),
                    JournalEntry(
                        tenant_id=421,
                        entry_no="migration-history-proof",
                        status="draft",
                    ),
                ]
            )
            db.commit()
        original_digest, counts = _sentinel_digest(engine)
        # Exercise historical checkpoints, not merely an empty-db upgrade.
        checkpoints = (
            "2026_11_19_native_checkpoints",
            "2026_11_21_enterprise_cognition",
            "head",
        )
        for checkpoint in checkpoints:
            command.upgrade(config, checkpoint)
            digest, row_counts = _sentinel_digest(engine)
            if digest != original_digest or counts != row_counts:
                raise AssertionError(
                    f"postgresql_migration_data_changed revision={checkpoint} "
                    f"before={original_digest} after={digest} "
                    f"counts={counts}/{row_counts}"
                )
        after_digest, after_counts = _sentinel_digest(engine)
        # A no-op head upgrade must not rewrite persisted business history.
        command.upgrade(config, "head")
        if _sentinel_digest(engine) != (after_digest, after_counts):
            raise AssertionError("postgresql_idempotent_upgrade_modified_data")
        with engine.connect() as db:
            revisions = set(
                db.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
            )
        expected = set(ScriptDirectory.from_config(config).get_heads())
        if revisions != expected:
            raise AssertionError(
                f"postgresql_migration_revision_mismatch found={revisions} expected={expected}"
            )
        command.check(config)
        # Negative control: this live PostgreSQL job must detect a deliberate
        # drift rather than always reporting schema parity success.
        from alembic.util.exc import AutogenerateDiffsDetected

        with engine.begin() as db:
            db.execute(
                sa.text(
                    "ALTER TABLE user_preferences ADD COLUMN "
                    "xcmax_schema_drift_probe TEXT"
                )
            )
        try:
            command.check(config)
        except AutogenerateDiffsDetected:
            drift_detected = True
        else:
            drift_detected = False
        finally:
            with engine.begin() as db:
                db.execute(sa.text("ALTER TABLE user_preferences DROP COLUMN xcmax_schema_drift_probe"))
        if not drift_detected:
            raise AssertionError("postgresql_schema_drift_negative_control_failed")
        command.check(config)
        print(
            f"[pg-history-upgrade] PASS baseline={BASELINE} heads={sorted(expected)} "
            f"sha256={after_digest} domain_rows={counts} "
            f"checkpoints={checkpoints} drift_negative_control=detected"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
