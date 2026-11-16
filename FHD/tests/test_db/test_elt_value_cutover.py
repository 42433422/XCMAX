"""Forward cutover of persisted ELT identifier values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

SOURCE = Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_16_elt_value_cutover.py"
spec = __import__("importlib.util", fromlist=["spec_from_file_location"]).spec_from_file_location(
    "elt_value_cutover", SOURCE
)
migration = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(migration)


def apply(connection, fn):
    with Operations.context(MigrationContext.configure(connection)):
        fn()


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'elt-value-cutover.db'}")
    yield engine
    engine.dispose()


def _create_operational_tables(connection) -> None:
    connection.execute(
        text(
            """
            CREATE TABLE elt_runs (
                id TEXT PRIMARY KEY,
                draft_json TEXT,
                summary_json TEXT,
                receipt_json TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE elt_run_rows (
                id INTEGER PRIMARY KEY,
                after_json TEXT,
                before_json TEXT,
                source_json TEXT,
                provenance_json TEXT,
                llm_suggestion_json TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE shipment_elt_import_fingerprints (
                id INTEGER PRIMARY KEY,
                tenant_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                source_kind TEXT,
                meta_json TEXT,
                UNIQUE (tenant_key, fingerprint)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE shipment_records (
                id INTEGER PRIMARY KEY,
                raw_text TEXT,
                parsed_data TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE templates (
                id INTEGER PRIMARY KEY,
                template_name TEXT NOT NULL,
                analyzed_data TEXT,
                editable_config TEXT,
                business_rules TEXT
            )
            """
        )
    )


def test_empty_database_upgrade_is_noop(engine):
    with engine.begin() as connection:
        apply(connection, migration.upgrade)
    with engine.connect() as connection:
        tables = connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
        assert tables == []


def test_old_database_upgrade_rewrites_operational_state_only(engine):
    with engine.begin() as connection:
        _create_operational_tables(connection)
        connection.execute(
            text(
                "INSERT INTO elt_runs (id, draft_json, summary_json, receipt_json) "
                "VALUES ('run-1', :draft, :summary, :receipt)"
            ),
            {
                "draft": json.dumps(
                    {"action": "execute_delivery_etl", "kind": "shipment_delivery_etl"}
                ),
                "summary": json.dumps({"kind": "shipment_delivery_etl"}),
                "receipt": json.dumps({"source": "shipment_excel_etl"}),
            },
        )
        connection.execute(
            text(
                "INSERT INTO elt_run_rows "
                "(id, after_json, before_json, source_json, provenance_json, llm_suggestion_json) "
                "VALUES (1, :after, :before, :source, :provenance, :suggestion)"
            ),
            {
                "after": json.dumps({"_etl": {"created": [1], "source": "shipment_excel_etl"}}),
                "before": json.dumps({"kind": "shipment_delivery_etl"}),
                "source": json.dumps({"source": "shipment_excel_etl"}),
                "provenance": json.dumps({"source_kind": "general_etl"}),
                "suggestion": json.dumps({"kind": "shipment_delivery_etl"}),
            },
        )
        connection.execute(
            text(
                "INSERT INTO shipment_elt_import_fingerprints "
                "(id, tenant_key, fingerprint, source_kind, meta_json) "
                "VALUES (1, 'tenant:1', 'fp-old', 'general_etl', :meta)"
            ),
            {"meta": json.dumps({"kind": "shipment_delivery_etl"})},
        )
        connection.execute(
            text(
                "INSERT INTO shipment_records (id, raw_text, parsed_data) "
                "VALUES (1, 'source=shipment_excel_etl|external_order_number=A-1', :parsed)"
            ),
            {"parsed": json.dumps({"source": "shipment_excel_etl"})},
        )
        connection.execute(
            text(
                "INSERT INTO templates (id, template_name, analyzed_data) "
                "VALUES (1, 'outbox', :analyzed)"
            ),
            {"analyzed": json.dumps({"source": "shipment_excel_etl"})},
        )
        apply(connection, migration.upgrade)

    with engine.connect() as connection:
        run = connection.execute(
            text("SELECT draft_json, summary_json, receipt_json FROM elt_runs WHERE id='run-1'")
        ).one()
        assert json.loads(run.draft_json) == {
            "action": "execute_delivery_elt",
            "kind": "shipment_delivery_elt",
        }
        assert json.loads(run.summary_json) == {"kind": "shipment_delivery_etl"}
        assert json.loads(run.receipt_json) == {"source": "shipment_excel_etl"}

        row = connection.execute(
            text(
                "SELECT after_json, before_json, source_json, provenance_json, llm_suggestion_json "
                "FROM elt_run_rows WHERE id=1"
            )
        ).one()
        assert json.loads(row.after_json) == {
            "_elt": {"created": [1], "source": "shipment_excel_elt"}
        }
        assert json.loads(row.before_json) == {"kind": "shipment_delivery_elt"}
        assert json.loads(row.source_json) == {"source": "shipment_excel_etl"}
        assert json.loads(row.provenance_json) == {"source_kind": "general_etl"}
        assert json.loads(row.llm_suggestion_json) == {"kind": "shipment_delivery_etl"}

        fingerprint = connection.execute(
            text("SELECT source_kind, meta_json FROM shipment_elt_import_fingerprints WHERE id=1")
        ).one()
        assert fingerprint.source_kind == "general_elt"
        assert json.loads(fingerprint.meta_json) == {"kind": "shipment_delivery_elt"}

        shipment = connection.execute(
            text("SELECT raw_text, parsed_data FROM shipment_records WHERE id=1")
        ).one()
        assert shipment.raw_text == "source=shipment_excel_elt|external_order_number=A-1"
        assert json.loads(shipment.parsed_data) == {"source": "shipment_excel_elt"}

        template = connection.execute(
            text("SELECT analyzed_data FROM templates WHERE id=1")
        ).scalar_one()
        assert json.loads(template) == {"source": "shipment_excel_elt"}


def test_mixed_old_and_new_rows_and_repeat_upgrade(engine):
    with engine.begin() as connection:
        _create_operational_tables(connection)
        connection.execute(
            text(
                "INSERT INTO shipment_elt_import_fingerprints "
                "(id, tenant_key, fingerprint, source_kind) VALUES "
                "(1, 'tenant:1', 'fp-old', 'general_etl'), "
                "(2, 'tenant:1', 'fp-new', 'general_elt'), "
                "(3, 'tenant:1', 'fp-note', 'general_elt_legacy_note')"
            )
        )
        connection.execute(
            text("INSERT INTO elt_run_rows (id, after_json) VALUES (1, :old), (2, :new)"),
            {
                "old": json.dumps({"_etl": {"created": [1]}}),
                "new": json.dumps({"_elt": {"created": [2]}}),
            },
        )
        apply(connection, migration.upgrade)
        first = list(
            connection.execute(
                text("SELECT id, source_kind FROM shipment_elt_import_fingerprints ORDER BY id")
            ).all()
        )
        first_rows = list(
            connection.execute(text("SELECT id, after_json FROM elt_run_rows ORDER BY id")).all()
        )
        apply(connection, migration.upgrade)
        second = list(
            connection.execute(
                text("SELECT id, source_kind FROM shipment_elt_import_fingerprints ORDER BY id")
            ).all()
        )
        second_rows = list(
            connection.execute(text("SELECT id, after_json FROM elt_run_rows ORDER BY id")).all()
        )

    assert [tuple(row) for row in first] == [
        (1, "general_elt"),
        (2, "general_elt"),
        (3, "general_elt_legacy_note"),
    ]
    assert json.loads(first_rows[0].after_json) == {"_elt": {"created": [1]}}
    assert json.loads(first_rows[1].after_json) == {"_elt": {"created": [2]}}
    assert first == second
    assert first_rows == second_rows


def test_equal_and_disjoint_metadata_keys_merge_without_dropping_rows(engine):
    with engine.begin() as connection:
        _create_operational_tables(connection)
        connection.execute(
            text("INSERT INTO elt_run_rows (id, after_json) VALUES (1, :equal), (2, :disjoint)"),
            {
                "equal": json.dumps({"_etl": {"created": [1]}, "_elt": {"created": [1]}}),
                "disjoint": json.dumps({"_etl": {"created": [2]}, "_elt": {"updated": [3]}}),
            },
        )
        apply(connection, migration.upgrade)
        rows = {
            row.id: json.loads(row.after_json)
            for row in connection.execute(text("SELECT id, after_json FROM elt_run_rows"))
        }
    assert rows[1] == {"_elt": {"created": [1]}}
    assert rows[2] == {"_elt": {"created": [2], "updated": [3]}}


def test_conflicting_metadata_raises_and_leaves_data_unchanged(engine):
    original = json.dumps({"_etl": {"created": [1]}, "_elt": {"created": [9]}})
    with engine.begin() as connection:
        _create_operational_tables(connection)
        connection.execute(
            text("INSERT INTO elt_run_rows (id, after_json) VALUES (1, :payload)"),
            {"payload": original},
        )
    with pytest.raises(migration.EltValueCutoverConflict, match="冲突字段"):
        with engine.begin() as connection:
            apply(connection, migration.upgrade)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT after_json FROM elt_run_rows WHERE id=1")).scalar_one()
            == original
        )


def test_rewrite_helpers_keep_unrelated_strings_and_audit_snapshots():
    text_value, changed = migration.rewrite_json_text(
        json.dumps({"note": "general_etl_legacy_note", "count": 3})
    )
    assert changed is False
    assert json.loads(text_value)["note"] == "general_etl_legacy_note"
    raw, raw_changed = migration.rewrite_raw_text(
        "customer=etl-warehouse|external_order_number=A-1"
    )
    assert raw_changed is False
    assert raw == "customer=etl-warehouse|external_order_number=A-1"
