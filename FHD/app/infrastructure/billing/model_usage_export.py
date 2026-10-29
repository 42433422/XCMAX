"""Export a stopped incremental ledger for compatibility/rollback."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True, help="Legacy MODEL_USAGE_LEDGER_PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--handoff",
        action="store_true",
        help="Retire SQLite after export for a stopped-runtime rollback",
    )
    args = parser.parse_args(argv)
    os.environ["MODEL_USAGE_LEDGER_PATH"] = str(args.ledger)
    from app.infrastructure.billing.model_usage import export_model_usage_ledger

    export_model_usage_ledger(args.output, retire_database=args.handoff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
