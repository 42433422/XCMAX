"""Build boundary: private source is independently compiled and never host-bundled."""

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
validate = runpy.run_path(str(ROOT / "scripts/package/bundled_mod_policy.py"))[
    "validated_staged_mods"
]


def test_host_requires_explicit_staging_and_rejects_private_manifest(tmp_path):
    with pytest.raises(ValueError, match="STAGED_MODS_DIR"):
        validate("")
    private = tmp_path / "sunbird-attendance-custom"
    private.mkdir()
    actual = json.loads((ROOT / "mods/sunbird-attendance-custom/manifest.json").read_text())
    (private / "manifest.json").write_text(json.dumps(actual))
    with pytest.raises(ValueError, match="private Mod cannot be bundled"):
        validate(str(tmp_path))


def test_standard_host_accepts_global_staged_manifest(tmp_path):
    public = tmp_path / "public-ui"
    public.mkdir()
    (public / "manifest.json").write_text(json.dumps({"id": "public-ui", "scope": "global"}))
    assert validate(str(tmp_path)) == tmp_path.resolve()


@pytest.mark.parametrize("sku", ["personal", "enterprise"])
def test_standard_sku_does_not_list_private_sunbird(sku):
    profile = json.loads((ROOT / f"config/host_profiles/{sku}.json").read_text())
    ids = profile.get("package_stage_ids") or profile.get("sku_bundled_mod_ids")
    assert "sunbird-attendance-custom" not in ids
    assert "taiyangniao-pro" not in ids


def test_build_spec_has_no_raw_marketplace_fallback():
    source = (ROOT / "scripts/package/xcagi_backend.spec").read_text()
    assert "validated_staged_mods" in source
    assert 'add_data("mods")' not in source
