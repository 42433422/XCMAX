#!/usr/bin/env python3
"""Retired customer-specific seed builder. Never reuse local customer snapshots."""

from __future__ import annotations

import sys
from pathlib import Path

RETIRED = (
    "Customer-specific repository seed generation is retired. "
    "Use the authorized private delivery workflow; public-source synthetic fixtures "
    "must not be installed as a customer roster. No files were read or written."
)


def build_sunbird_seed(
    *, seed_root: Path | None = None, template_src: Path | None = None
) -> dict:
    raise RuntimeError(RETIRED)


def main() -> int:
    print(RETIRED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
