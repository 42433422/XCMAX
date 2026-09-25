"""Read-only SQLite inventory of durable Agent bindings before host migration."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

TERMINAL = {"completed", "failed", "cancelled"}


def inventory(database: Path) -> dict:
    counts: Counter[str] = Counter()
    uri = f"file:{quote(str(database.resolve()), safe='/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_runs'"
        ).fetchone():
            return {"database": str(database), "agent_runs_present": False, "counts": {}}
        for status, payload in db.execute("SELECT status, payload_json FROM agent_runs"):
            counts["total"] += 1
            if status in TERMINAL:
                counts["terminal"] += 1
                continue
            counts["nonterminal"] += 1
            try:
                data = json.loads(payload)
                binding = (data.get("metadata", {}).get("runtime_context") or {}).get(
                    "_mod_authorization"
                )
                if not binding:
                    counts["host_unbound"] += 1
                elif not isinstance(binding, dict):
                    counts["invalid_binding"] += 1
                elif (
                    not {"account_tenant_id", "account_role", "session_row_id", "user_id", "mod_id"}
                    <= binding.keys()
                ):
                    counts["requires_reauthorization"] += 1
                else:
                    counts["snapshot_present_needs_live_session_validation"] += 1
            except (ValueError, TypeError, AttributeError):
                counts["invalid_payload"] += 1
    return {"database": str(database), "agent_runs_present": True, "counts": dict(counts)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path, nargs="+")
    args = parser.parse_args()
    print(
        json.dumps(
            {"read_only": True, "databases": [inventory(path) for path in args.database]}, indent=2
        )
    )


if __name__ == "__main__":
    main()
