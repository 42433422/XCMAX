from __future__ import annotations

import json
from typing import Any


REVIEW_CONTEXT_BIAS: dict[str, Any] = json.loads('{\n  "context_focus": [\n    "runtime",\n    "tests",\n    "ci_config",\n    "config",\n    "docs"\n  ],\n  "enabled": true,\n  "external_path": "/Users/a4243342/Desktop/XCMAX/.claude/worktrees/pedantic-leakey-5611d9/packages/retort_engine/.retort/cache/github/bobbyroe/threejs-earth",\n  "reason": "absorbed external file grouping and review pipeline signals",\n  "run_id": "20260627192206-0723009b1b",\n  "signal_evidence": {\n    "atmosphere_shader": [\n      "index.js",\n      "README.md",\n      "src/getStarfield.js",\n      "src/getEarthMat.js",\n      "src/getFresnelMat.js"\n    ],\n    "cloud_texture_layer": [\n      "README.md",\n      "src/getEarthMat.js"\n    ],\n    "day_night_textures": [\n      "README.md",\n      "src/getEarthMat.js"\n    ],\n    "elevation_bump_map": [\n      "README.md"\n    ],\n    "fresnel_atmosphere": [\n      "index.js",\n      "README.md",\n      "src/getFresnelMat.js"\n    ],\n    "multi_provider": [\n      "src/getEarthMat.js",\n      "src/getFresnelMat.js"\n    ],\n    "planet_frontend": [\n      "index.js",\n      "README.md"\n    ],\n    "procedural_surface": [\n      "index.js",\n      "README.md",\n      "src/getStarfield.js",\n      "src/getLayer.js",\n      "src/getEarthMat.js"\n    ],\n    "review_pipeline": [\n      "src/getEarthMat.js",\n      "src/getFresnelMat.js"\n    ],\n    "specular_ocean": [\n      "README.md",\n      "src/getEarthMat.js",\n      "src/getFresnelMat.js"\n    ],\n    "webgl_scene": [\n      "index.js",\n      "README.md",\n      "src/getEarthMat.js",\n      "src/getFresnelMat.js"\n    ]\n  },\n  "signals": [\n    "review_pipeline",\n    "multi_provider",\n    "planet_frontend",\n    "atmosphere_shader",\n    "procedural_surface",\n    "webgl_scene",\n    "day_night_textures",\n    "cloud_texture_layer",\n    "fresnel_atmosphere",\n    "elevation_bump_map",\n    "specular_ocean"\n  ],\n  "source": "https://github.com/bobbyroe/threejs-earth"\n}')


def review_context_bias() -> dict[str, Any]:
    """Return the absorbed context grouping profile used by PR review."""
    return dict(REVIEW_CONTEXT_BIAS)


def file_grouping_enabled() -> bool:
    """Tell PR review whether absorbed external evidence supports context grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return bool(REVIEW_CONTEXT_BIAS.get("enabled")) and bool(signals & {"file_grouping", "review_pipeline", "diff_hunk_review"})


def context_signal_strength() -> int:
    """Score how much absorbed evidence should influence review grouping."""
    signals = set(REVIEW_CONTEXT_BIAS.get("signals") or [])
    return min(100, 20 * len(signals & {"file_grouping", "review_pipeline", "diff_hunk_review", "benchmarking", "safety_policy"}))
