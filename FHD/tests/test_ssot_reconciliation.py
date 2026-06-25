# -*- coding: utf-8 -*-
"""Reconciliation tests for the two off-registry SSOTs now registered in SSOT_INDEX.

The SSOT registry (``ssot.yaml`` / ``ssot_cli.py``) only knows about derivations it
owns. Two load-bearing SSOTs live *outside* it:

  * ``employee-roster`` — ``FHD/config/duty_roster.json`` is the truth; the frontend
    ``yuangonDutyRoster.ts`` is a generated derivation. If they drift, the duty
    matrix shown in the UI silently lies about who is on staff.
  * ``db-schema`` — the live Alembic chain under ``FHD/alembic`` is the schema
    truth; it must stay a single connected head or ``alembic upgrade head`` becomes
    non-deterministic.

The SSOT_INDEX rows for these two are advisory documentation; these tests are the
enforcement. See ``FHD/docs/SSOT_INDEX.md`` rows ``employee-roster`` / ``db-schema``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.mod_sdk.duty_roster import all_planned_duty_employee_ids

_FHD_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _FHD_ROOT.parent
_ROSTER_TS = _FHD_ROOT / "frontend" / "src" / "domain" / "yuangonDutyRoster.ts"
_ALEMBIC_GUARD = _REPO_ROOT / "scripts" / "guard_alembic_single_head.py"


def _frontend_area_ids() -> set[str]:
    """Every employee id under ``YUANGON_AREAS[*].ids`` in the derived TS file.

    We deliberately read only the ``YUANGON_AREAS`` literal (the flat "who is on
    staff" set), which mirrors what ``all_planned_duty_employee_ids()`` collects
    from the JSON ``areas`` block — not the richer ``SIX_LINE_DEPARTMENTS`` view.
    """
    text = _ROSTER_TS.read_text(encoding="utf-8")
    # Slice out just the YUANGON_AREAS object literal: it ends where the aggregate
    # ALL_PLANNED_YUANGON_PKG_IDS export begins.
    block = text.split("export const ALL_PLANNED_YUANGON_PKG_IDS", 1)[0]
    block = block.split("export const YUANGON_AREAS", 1)[1]
    ids: set[str] = set()
    for arr in re.findall(r"ids:\s*\[(.*?)\]", block, re.DOTALL):
        ids.update(re.findall(r"'([^']+)'", arr))
    return ids


def test_employee_roster_frontend_matches_backend_ssot() -> None:
    """employee-roster SSOT (duty_roster.json) == derived frontend roster ids."""
    backend = set(all_planned_duty_employee_ids())
    frontend = _frontend_area_ids()
    assert backend, "backend roster unexpectedly empty — duty_roster SSOT loader broken"
    assert frontend, "frontend YUANGON_AREAS ids unexpectedly empty — parse broke"
    assert backend == frontend, (
        "employee-roster drift between config/duty_roster.json (SSOT) and "
        "frontend/src/domain/yuangonDutyRoster.ts (derived):\n"
        f"  only in backend SSOT: {sorted(backend - frontend)}\n"
        f"  only in frontend:     {sorted(frontend - backend)}\n"
        "Regenerate the frontend derivation from the SSOT, do not hand-edit the .ts."
    )


def test_db_schema_single_alembic_head() -> None:
    """db-schema SSOT: the live Alembic chain must be a single connected head.

    Structural half of "Alembic is the schema SSOT": no DB required, mirrors the
    BLOCKING single-head job in .github/workflows/fhd-alembic-ssot.yml.
    """
    if not _ALEMBIC_GUARD.is_file():
        pytest.skip("guard_alembic_single_head.py absent in this checkout")
    proc = subprocess.run(
        [sys.executable, str(_ALEMBIC_GUARD)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "db-schema SSOT broken — Alembic chain is multi-head or has a dangling "
        "down_revision:\n" + proc.stdout + proc.stderr
    )
