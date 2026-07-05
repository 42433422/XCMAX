"""Wave 2 release_gate: industry scaffold script exists."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

ROOT = Path(__file__).resolve().parents[2]


def test_scaffold_industry_mod_script_exists():
    script = ROOT / "scripts/dev/scaffold-industry-mod.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "industry_package.schema.json" in text or "validate_industry_manifest" in text
    assert "mods_ssot.py sync" in text
