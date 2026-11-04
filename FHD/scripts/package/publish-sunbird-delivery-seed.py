#!/usr/bin/env python3
"""Retired shared-catalog customer seed publisher; fail closed before any I/O.

This legacy tool registered personnel snapshots under a fixed production customer
identity. Removing tracked fixtures does not make old local seeds or supplied ZIPs
safe. Existing private delivery APIs are unchanged; this repository helper cannot
package, copy or register customer data, including with --zip-path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

RETIRED = (
    "Legacy customer seed catalog publication is disabled. "
    "Use the authorized private delivery workflow. No package was built or registered."
)


def _build_zip(seed_root: Path, out_dir: Path, version: str) -> Path:
    raise RuntimeError(RETIRED)


def _upsert_package(
    modstore_root: Path, zip_path: Path, version: str
) -> dict[str, Any]:
    raise RuntimeError(RETIRED)


def main() -> int:
    print(RETIRED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
