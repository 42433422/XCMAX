import json
import sqlite3

from scripts.dev.audit_agent_binding_inventory import inventory


def test_inventory_is_read_only_and_redacts_payloads(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE agent_runs (status TEXT, payload_json TEXT)")
        for status, binding in [
            ("running", {"mod_id": "private", "secret": "do-not-print"}),
            ("completed", {"mod_id": "old"}),
            ("queued", None),
        ]:
            db.execute(
                "INSERT INTO agent_runs VALUES (?, ?)",
                (
                    status,
                    json.dumps({"metadata": {"runtime_context": {"_mod_authorization": binding}}}),
                ),
            )
    before = path.read_bytes()
    report = inventory(path)
    assert report["counts"] == {
        "total": 3,
        "nonterminal": 2,
        "requires_reauthorization": 1,
        "terminal": 1,
        "host_unbound": 1,
    }
    assert "do-not-print" not in json.dumps(report)
    assert path.read_bytes() == before


def test_missing_database_is_not_created(tmp_path):
    import pytest

    path = tmp_path / "absent.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        inventory(path)
    assert not path.exists()
