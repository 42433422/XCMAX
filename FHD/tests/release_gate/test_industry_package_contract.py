"""Wave 0: industry package manifest JSON Schema contract (release_gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.contracts.industry_package_validator import (
    iter_industry_package_manifests,
    validate_industry_manifest,
)

pytestmark = pytest.mark.release_gate

ROOT = Path(__file__).resolve().parents[2]


def test_industry_package_schema_exists():
    schema = ROOT / "contracts" / "industry_package.schema.json"
    assert schema.is_file()
    assert "neutralIndustryPackage" in schema.read_text(encoding="utf-8")


def test_mod_authoring_guide_has_industry_section():
    guide = (ROOT / "docs/guides/MOD_AUTHORING_GUIDE.md").read_text(encoding="utf-8")
    assert "## 4b." in guide or "4b 行业包 manifest" in guide
    assert "industry_package.schema.json" in guide


@pytest.mark.parametrize("manifest_path", iter_industry_package_manifests())
def test_industry_manifests_validate(manifest_path: Path):
    errors = validate_industry_manifest(manifest_path)
    assert not errors, f"{manifest_path.name}: " + "; ".join(errors)


def test_at_least_two_industry_packages():
    manifests = iter_industry_package_manifests()
    ids = {p.parent.name for p in manifests}
    assert "coating-industry" in ids
    assert "attendance-industry" in ids
