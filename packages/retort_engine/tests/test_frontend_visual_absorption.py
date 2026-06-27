from __future__ import annotations

import json
import re
from pathlib import Path


EXPECTED_VISUAL_SOURCE = 'https://github.com/bobbyroe/threejs-earth'


def _app_text() -> str:
    return (Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js").read_text(encoding="utf-8")


def _absorbed_profile() -> dict[str, object]:
    text = _app_text()
    match = re.search(r"const ABSORBED_PLANET_VISUAL_PROFILE = (\{.*?\n\});", text, re.S)
    assert match, "absorbed planet visual profile is missing"
    return json.loads(match.group(1))


def test_absorbed_planet_visual_profile_references_external_source() -> None:
    profile = _absorbed_profile()

    assert profile["enabled"] is True
    assert profile["source"] == EXPECTED_VISUAL_SOURCE
    assert profile["visual_family"] == "absorbed-procedural-planet"
    assert profile["license_boundary"] == "visual principles only; no external source or texture copied"
    assert set(profile["absorbed_signals"]) & {"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"}


def test_planet_renderer_uses_absorbed_visual_layers() -> None:
    text = _app_text()

    assert "planetVisualProfile()" in text
    assert "procedural_landmasses" in text
    assert "translucent_clouds" in text
    assert "terminator_shadow" in text
    assert "atmospheric_rim" in text
    assert "day_night_terminator" in text
    assert "fresnel_glow" in text
    assert "city_lights" in text
    assert "rgbaHex(palette.rim" in text
