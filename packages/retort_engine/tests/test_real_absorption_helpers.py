from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from retort_engine import real_absorption as real


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init")
    git(repo, "config", "user.email", "retort@example.com")
    git(repo, "config", "user.name", "Retort Test")
    write(repo / "README.md", "# repo\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")


def test_external_profile_detects_signals_suffix_counts_and_git_revision(tmp_path: Path) -> None:
    external = tmp_path / "external"
    init_repo(external)
    write(external / "review" / "pipeline.py", "code review pipeline reviewer reflection localization\n")
    write(external / "review" / "grouping.ts", "file group group files changed files diff hunk patch set\n")
    write(external / "eval" / "bench.md", "benchmark precision recall evaluation eval\n")
    write(external / "graph" / "codebase.py", "codebase graph dependency graph call graph symbol graph imports hotspot\n")
    write(external / "plugins" / "action.yml", "plugin cli github action codex\n")
    write(external / "providers" / "models.py", "provider model openai anthropic ollama\n")
    write(external / "security" / "rules.py", "static analysis security scan scanner taint rule engine vulnerability secret\n")
    write(external / "context" / "pack.md", "repo map repository context codebase context context pack prompt context code digest\n")
    write(external / "index" / "symbols.py", "semantic index symbol index language server definition reference xref scip lsif\n")
    git(external, "add", ".")
    git(external, "commit", "-m", "signals")

    profile = real._external_profile(external)

    assert profile["file_count"] >= 6
    assert profile["suffix_counts"][".py"] >= 2
    assert profile["git_revision"]
    assert set(profile["signals"]) >= {
        "review_pipeline",
        "file_grouping",
        "benchmarking",
        "codebase_graph",
        "plugin_surface",
        "multi_provider",
        "safety_policy",
        "static_analysis",
        "context_packaging",
        "semantic_index",
    }
    assert profile["signal_evidence"]["review_pipeline"] == ["review/pipeline.py"]
    assert profile["signal_evidence"]["file_grouping"] == ["review/grouping.ts"]
    assert profile["signal_evidence"]["benchmarking"] == ["eval/bench.md"]
    assert profile["signal_evidence"]["codebase_graph"] == ["graph/codebase.py"]
    assert profile["signal_evidence"]["plugin_surface"] == ["plugins/action.yml"]
    assert profile["signal_evidence"]["multi_provider"] == ["providers/models.py"]
    assert profile["signal_evidence"]["safety_policy"] == ["security/rules.py"]
    assert profile["signal_evidence"]["static_analysis"] == ["security/rules.py"]
    assert profile["signal_evidence"]["context_packaging"] == ["context/pack.md"]
    assert profile["signal_evidence"]["semantic_index"] == ["index/symbols.py"]


def test_external_profile_ignores_runtime_and_dependency_directories(tmp_path: Path) -> None:
    external = tmp_path / "external"
    write(external / ".retort" / "state.json", "review pipeline plugin\n")
    write(external / "node_modules" / "pkg" / "index.js", "benchmark provider\n")
    write(external / "__pycache__" / "x.py", "file group\n")
    write(external / "src" / "tool.py", "code review pipeline\n")

    profile = real._external_profile(external)

    assert profile["file_count"] == 1
    assert profile["signals"] == ["review_pipeline"]
    assert profile["signal_evidence"] == {"review_pipeline": ["src/tool.py"]}


def test_external_profile_detects_planet_frontend_visual_signals(tmp_path: Path) -> None:
    external = tmp_path / "external"
    write(
        external / "scripts" / "planet.js",
        "three.js WebGL renderer scene camera orbit controls sphereGeometry procedural planet atmosphere shader cloud noise terrain texture\n",
    )

    profile = real._external_profile(external)

    assert set(profile["signals"]) >= {"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"}
    assert profile["signal_evidence"]["planet_frontend"] == ["scripts/planet.js"]
    assert profile["signal_evidence"]["atmosphere_shader"] == ["scripts/planet.js"]
    assert profile["signal_evidence"]["procedural_surface"] == ["scripts/planet.js"]
    assert profile["signal_evidence"]["webgl_scene"] == ["scripts/planet.js"]
    assert real._should_absorb_frontend_visual(profile) is True


def test_external_profile_detects_high_fidelity_earth_visual_signals(tmp_path: Path) -> None:
    external = tmp_path / "external"
    write(
        external / "src" / "getEarthMat.js",
        "dayTexture nightTexture cloudsTexture daymap nightmap earth-clouds specular reflection roughness sunOrientation\n",
    )
    write(
        external / "src" / "getFresnelMat.js",
        "fresnel reflectionFactor AdditiveBlending atmosphere glowMesh shader\n",
    )
    write(external / "README.md", "day + night textures, bump elevation, clouds, and Fresnel atmosphere glow\n")

    profile = real._external_profile(external)

    assert set(profile["signals"]) >= {
        "day_night_textures",
        "cloud_texture_layer",
        "fresnel_atmosphere",
        "elevation_bump_map",
        "specular_ocean",
    }
    assert "src/getEarthMat.js" in profile["signal_evidence"]["day_night_textures"]
    assert "src/getEarthMat.js" in profile["signal_evidence"]["cloud_texture_layer"]
    assert "src/getFresnelMat.js" in profile["signal_evidence"]["fresnel_atmosphere"]
    assert real._should_absorb_frontend_visual(profile) is True


def test_semantic_review_reports_external_advantages(tmp_path: Path) -> None:
    own = tmp_path / "own"
    external = tmp_path / "external"
    write(own / "retort_engine" / "core.py", "def absorb():\n    return True\n")
    write(
        external / "src" / "tool.py",
        "class Reviewer:\n    pass\n\ndef review():\n    pass\n\ndef test_marker():\n    pass\n# workflow pipeline review\n",
    )

    review = real._semantic_review(own, external)

    assert review["own"]["source_files"] == 1
    assert review["external"]["classes"] >= 1
    metrics = {gap["metric"] for gap in review["gaps"]}
    assert {"classes", "functions", "workflow_markers"} <= metrics


def test_project_files_filters_suffixes_and_skip_parts(tmp_path: Path) -> None:
    write(tmp_path / "keep.py", "def ok(): pass\n")
    write(tmp_path / "keep.md", "review\n")
    write(tmp_path / "skip.txt", "not source\n")
    write(tmp_path / ".pytest_cache" / "README.md", "cache\n")
    write(tmp_path / "dist" / "bundle.js", "review pipeline\n")
    write(tmp_path / "node_modules" / "pkg" / "index.js", "provider\n")

    files = real._project_files(tmp_path)

    rels = {path.relative_to(tmp_path).as_posix() for path in files}
    assert rels == {"keep.py", "keep.md", "skip.txt"}
    assert not any(path.startswith(".pytest_cache/") or path.startswith("dist/") or path.startswith("node_modules/") for path in rels)


def test_context_focus_from_signals_is_ordered_and_deduplicated() -> None:
    focus = real._context_focus_from_signals(
        [
            "safety_policy",
            "file_grouping",
            "review_pipeline",
            "benchmarking",
            "plugin_surface",
            "multi_provider",
        ]
    )

    assert focus == ["security", "runtime", "tests", "ci_config", "config", "docs"]


def test_review_context_bias_generation_is_executable(tmp_path: Path) -> None:
    content = real._review_context_bias_content(
        "run-1",
        "https://github.com/example/reviewer",
        tmp_path / "external",
        {
            "signals": ["review_pipeline", "file_grouping", "benchmarking"],
            "signal_evidence": {"review_pipeline": ["README.md"]},
        },
    )
    module_path = tmp_path / "review_context_bias.py"
    write(module_path, content)

    module = load_module(module_path, "generated_review_context_bias")

    assert module.review_context_bias()["source"] == "https://github.com/example/reviewer"
    assert module.file_grouping_enabled() is True
    assert module.context_signal_strength() == 60


def test_review_context_bias_test_template_uses_only_referenced_symbols() -> None:
    content = real._review_context_bias_test_content("retort_engine.review_context_bias", "https://github.com/example/reviewer")

    assert "context_rank_weight, " not in content
    assert "context_rank_weights" in content
    assert "context_signal_strength" in content


def test_review_context_bias_generation_merges_previous_absorptions(tmp_path: Path) -> None:
    previous_content = real._review_context_bias_content(
        "run-old",
        "https://github.com/example/old-reviewer",
        tmp_path / "old",
        {
            "signals": ["review_pipeline", "file_grouping", "safety_policy", "semantic_index"],
            "signal_evidence": {
                "review_pipeline": ["README.md"],
                "semantic_index": ["src/index.py"],
            },
        },
    )
    previous_path = tmp_path / "review_context_bias.py"
    write(previous_path, previous_content)

    content = real._review_context_bias_content(
        "run-new",
        "https://github.com/example/local-reviewer",
        tmp_path / "new",
        {
            "signals": ["review_pipeline", "file_grouping"],
            "signal_evidence": {"file_grouping": ["reviewer.py"]},
        },
        existing=real._existing_review_context_bias(previous_path),
    )
    write(previous_path, content)
    module = load_module(previous_path, "generated_merged_review_context_bias")
    bias = module.review_context_bias()

    assert bias["source"] == "https://github.com/example/local-reviewer"
    assert bias["sources"] == ["https://github.com/example/old-reviewer", "https://github.com/example/local-reviewer"]
    assert bias["run_ids"] == ["run-old", "run-new"]
    assert {"review_pipeline", "file_grouping", "safety_policy", "semantic_index"} <= set(bias["signals"])
    assert bias["signal_evidence"]["review_pipeline"] == ["README.md"]
    assert bias["signal_evidence"]["file_grouping"] == ["reviewer.py"]
    assert module.context_signal_strength() >= 80


def test_review_context_bias_is_only_written_for_context_signals() -> None:
    assert real._should_absorb_review_context_bias({"signals": ["benchmarking"]}) is False
    assert real._should_absorb_review_context_bias({"signals": ["plugin_surface"]}) is False
    assert real._should_absorb_review_context_bias({"signals": ["review_pipeline"]}) is True
    assert real._should_absorb_review_context_bias({"signals": ["file_grouping"]}) is True
    assert real._should_absorb_review_context_bias({"signals": ["diff_hunk_review"]}) is True
    assert real._should_absorb_review_context_bias({"signals": ["static_analysis"]}) is True
    assert real._should_absorb_review_context_bias({"signals": ["context_packaging"]}) is True
    assert real._should_absorb_review_context_bias({"signals": ["semantic_index"]}) is True


def test_capability_model_is_only_written_for_review_depth_signals() -> None:
    assert real._should_absorb_capability_model({"signals": ["planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"]}) is False
    assert real._should_absorb_capability_model({"signals": ["multi_provider", "planet_frontend"]}) is False
    assert real._should_absorb_capability_model({"signals": ["review_pipeline"]}) is True
    assert real._should_absorb_capability_model({"signals": ["benchmarking"]}) is True
    assert real._should_absorb_capability_model({"signals": ["codebase_graph"]}) is True
    assert real._should_absorb_capability_model({"signals": ["plugin_surface"]}) is True
    assert real._should_absorb_capability_model({"signals": ["static_analysis"]}) is True
    assert real._should_absorb_capability_model({"signals": ["context_packaging"]}) is True
    assert real._should_absorb_capability_model({"signals": ["semantic_index"]}) is True


def test_visual_dominant_project_does_not_overwrite_review_capability_model() -> None:
    profile = {
        "signals": [
            "review_pipeline",
            "multi_provider",
            "planet_frontend",
            "atmosphere_shader",
            "procedural_surface",
            "webgl_scene",
            "day_night_textures",
            "cloud_texture_layer",
            "fresnel_atmosphere",
            "elevation_bump_map",
            "specular_ocean",
        ],
        "signal_evidence": {
            "planet_frontend": ["src/getEarthMat.js"],
            "atmosphere_shader": ["src/getFresnelMat.js"],
            "procedural_surface": ["src/getEarthMat.js"],
            "webgl_scene": ["src/App.jsx"],
            "day_night_textures": ["src/getEarthMat.js"],
            "cloud_texture_layer": ["src/getEarthMat.js"],
            "fresnel_atmosphere": ["src/getFresnelMat.js"],
            "elevation_bump_map": ["src/getEarthMat.js"],
            "specular_ocean": ["src/getEarthMat.js"],
        },
    }

    assert real._should_absorb_frontend_visual(profile) is True
    assert real._should_absorb_review_context_bias(profile) is False
    assert real._should_absorb_capability_model(profile) is False


def test_frontend_visual_absorption_requires_frontend_visual_evidence() -> None:
    benchmark_profile = {
        "signals": ["benchmarking", "atmosphere_shader", "procedural_surface", "webgl_scene"],
        "signal_evidence": {
            "atmosphere_shader": ["README.md", "benchmarks/swebench/README.md"],
            "procedural_surface": ["tests/test_programbench.py"],
            "webgl_scene": ["tests/test_programbench.py"],
        },
    }
    planet_profile = {
        "signals": ["planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"],
        "signal_evidence": {
            "planet_frontend": ["index.html", "scripts/main.js"],
            "atmosphere_shader": ["scripts/main.js"],
            "procedural_surface": ["scripts/terrain.js"],
            "webgl_scene": ["scripts/main.js"],
        },
    }

    assert real._should_absorb_frontend_visual(benchmark_profile) is False
    assert real._should_absorb_frontend_visual(planet_profile) is True


def test_frontend_visual_absorption_rejects_incidental_dashboard_visual_terms() -> None:
    profile = {
        "signals": ["review_pipeline", "atmosphere_shader", "procedural_surface", "elevation_bump_map"],
        "signal_evidence": {
            "atmosphere_shader": ["apps/dashboard/src/app/layout.tsx", "apps/dashboard/src/app/privacy/page.tsx"],
            "procedural_surface": ["packages/rules-engine/src/rules/reliability.ts"],
            "elevation_bump_map": ["apps/worker/src/jobs/review.ts"],
        },
    }

    assert real._should_absorb_frontend_visual(profile) is False


def test_frontend_visual_profile_rewrite_and_generated_test_are_executable(tmp_path: Path) -> None:
    app = tmp_path / "retort_engine" / "frontend" / "app.js"
    write(
        app,
        """
const ABSORBED_PLANET_VISUAL_PROFILE = {
  source: "",
  enabled: false,
  palette: {rim: "#8ff3ff"},
  layers: {atmospheric_rim: true}
};
function planetVisualProfile() { return ABSORBED_PLANET_VISUAL_PROFILE; }
function projectPlanet() {
  const profile = planetVisualProfile();
  const layers = profile.layers;
  if (layers.procedural_landmasses) {}
  if (layers.translucent_clouds) {}
  if (layers.terminator_shadow) {}
  if (layers.atmospheric_rim) {}
  return "rgbaHex(palette.rim";
}
""",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "retort_engine").mkdir(exist_ok=True)
    profile = {"signals": ["planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"]}

    real._write_frontend_visual_profile(app, "run-planet", "https://github.com/example/planet", tmp_path / "external", profile)
    test_path = tests / "test_frontend_visual_absorption.py"
    test_path.write_text(real._frontend_visual_test_content("https://github.com/example/planet"), encoding="utf-8")

    text = app.read_text(encoding="utf-8")
    payload = json.loads(text.split("const ABSORBED_PLANET_VISUAL_PROFILE = ", 1)[1].split(";\nfunction", 1)[0])
    result = real._run_command([sys.executable, "-m", "pytest", str(test_path), "-q"], tmp_path, timeout=60)

    assert payload["enabled"] is True
    assert payload["source"] == "https://github.com/example/planet"
    assert payload["visual_family"] == "absorbed-procedural-planet"
    assert set(payload["absorbed_signals"]) == {"planet_frontend", "atmosphere_shader", "procedural_surface", "webgl_scene"}
    assert payload["layers"]["procedural_landmasses"] is True
    assert payload["layers"]["translucent_clouds"] is True
    assert payload["license_boundary"] == "visual principles only; no external source or texture copied"
    assert result["ok"] is True, result["stderr_tail"] + result["stdout_tail"]


def test_frontend_visual_profile_enables_high_fidelity_earth_layers(tmp_path: Path) -> None:
    app = tmp_path / "retort_engine" / "frontend" / "app.js"
    write(
        app,
        """
const ABSORBED_PLANET_VISUAL_PROFILE = {
  source: "",
  enabled: false,
  palette: {rim: "#8ff3ff"},
  layers: {atmospheric_rim: true}
};
function planetVisualProfile() { return ABSORBED_PLANET_VISUAL_PROFILE; }
function projectPlanet() {
  const layers = planetVisualProfile().layers;
  if (layers.day_night_terminator) {}
  if (layers.cloud_shadow_layer) {}
  if (layers.fresnel_glow) {}
  if (layers.ocean_specular) {}
  if (layers.city_lights) {}
  return "day_night_terminator fresnel_glow city_lights";
}
""",
    )
    profile = {"signals": ["planet_frontend", "day_night_textures", "cloud_texture_layer", "fresnel_atmosphere", "elevation_bump_map", "specular_ocean"]}

    real._write_frontend_visual_profile(app, "run-earth", "https://github.com/example/earth", tmp_path / "external", profile)

    payload = json.loads(app.read_text(encoding="utf-8").split("const ABSORBED_PLANET_VISUAL_PROFILE = ", 1)[1].split(";\nfunction", 1)[0])
    assert set(payload["absorbed_signals"]) >= {"day_night_textures", "cloud_texture_layer", "fresnel_atmosphere", "elevation_bump_map", "specular_ocean"}
    assert payload["layers"]["day_night_terminator"] is True
    assert payload["layers"]["cloud_shadow_layer"] is True
    assert payload["layers"]["fresnel_glow"] is True
    assert payload["layers"]["terrain_relief"] is True
    assert payload["layers"]["ocean_specular"] is True
    assert payload["layers"]["city_lights"] is True
    assert payload["palette"]["city"] == "#ffd36a"


def test_visual_absorption_preserves_core_capability_model(tmp_path: Path) -> None:
    project = tmp_path / "own"
    external = tmp_path / "external"
    write(
        project / "retort_engine" / "frontend" / "app.js",
        """
const ABSORBED_PLANET_VISUAL_PROFILE = {
  source: "",
  enabled: false,
  palette: {rim: "#8ff3ff"},
  layers: {atmospheric_rim: true}
};
function planetVisualProfile() { return ABSORBED_PLANET_VISUAL_PROFILE; }
function projectPlanet() {
  const profile = planetVisualProfile();
  const layers = profile.layers;
  const palette = profile.palette;
  if (layers.procedural_landmasses) {}
  if (layers.translucent_clouds) {}
  if (layers.terminator_shadow) {}
  if (layers.atmospheric_rim) {}
  return "rgbaHex(palette.rim";
}
""",
    )
    write(project / "retort_engine" / "__init__.py", "")
    write(external / "scripts" / "planet.js", "three.js WebGL scene procedural planet atmosphere shader cloud terrain noise\n")

    result = real.apply_real_absorption(
        {
            "own_project": str(project),
            "external_path": str(external),
            "source": "https://github.com/example/procedural-planets",
            "tasks": [{"task_id": "retort-absorb-planet-visual", "title": "Planet visual", "dimension": "product_operability", "priority": "P1"}],
            "python": sys.executable,
        }
    )

    changed = {Path(path).relative_to(project).as_posix() for path in result["changed_files"]}
    assert result["status"] == "applied"
    assert result["gates_passed"] is True
    assert result["capability_model_preserved"] is True
    assert result["capability_module_path"] == ""
    assert "retort_engine/frontend/app.js" in changed
    assert "tests/test_frontend_visual_absorption.py" in changed
    assert "retort_engine/absorbed_capabilities.py" not in changed
    assert "tests/test_absorbed_capabilities.py" not in changed
    assert not (project / "retort_engine" / "absorbed_capabilities.py").exists()
    assert not (project / "tests" / "test_absorbed_capabilities.py").exists()


def test_module_content_round_trips_absorbed_external_patterns(tmp_path: Path) -> None:
    content = real._module_content(
        "run-2",
        "https://github.com/example/reviewer",
        tmp_path / "external",
        [{"task_id": "t1", "title": "Deepen review", "dimension": "comparative_analysis_depth", "priority": "P0", "why": "depth"}],
        {"signals": ["review_pipeline"], "signal_evidence": {"review_pipeline": ["README.md"]}},
    )
    module_path = tmp_path / "absorbed_external_patterns.py"
    write(module_path, content)

    module = load_module(module_path, "generated_absorbed_external_patterns")
    payload = module.absorbed_external_patterns()

    assert payload["run_id"] == "run-2"
    assert payload["source"] == "https://github.com/example/reviewer"
    assert payload["tasks"][0]["task_id"] == "t1"
    assert payload["external_profile"]["signals"] == ["review_pipeline"]


def test_capability_module_content_exposes_depth_gate_and_mapping(tmp_path: Path) -> None:
    review_report = {
        "review_pipeline": {
            "component_gaps": [{"component": "review_pipeline"}, {"component": "diff_hunk_review"}],
            "prioritized_absorptions": [{"component": "review_pipeline", "priority": "P0"}],
            "depth_absorption_workflow": {
                "focus_mode": "similar_function_depth_only",
                "focused_components": [
                    {"component": "review_pipeline", "priority": "P0", "similarity_score": 90, "depth_gap": 10},
                    {"component": "diff_hunk_review", "priority": "P1", "similarity_score": 70, "depth_gap": 3},
                ],
                "rejected_breadth_components": [{"component": "plugin_surface", "reason": "breadth_only_for_current_phase"}],
                "deferred_breadth_components": [{"component": "plugin_surface", "status": "closed_until_similarity_saturation"}],
                "marketplace_candidates": [],
                "marketplace_candidates_enabled": False,
                "employee_tasks": [{"task_id": "retort-depth-review-pipeline", "acceptance": "ok", "evidence_required": ["source diff"]}],
                "quality_gate": {"passed": True},
            },
            "benchmark": {"minimum_expected_behavior_tests": 3},
        }
    }
    content = real._capability_module_content(
        "run-3",
        "https://github.com/example/reviewer",
        tmp_path / "external",
        [{"task_id": "t1", "title": "Deepen review", "dimension": "comparative_analysis_depth", "priority": "P0", "why": "depth"}],
        {
            "signals": ["review_pipeline", "diff_hunk_review", "file_grouping"],
            "signal_evidence": {"review_pipeline": ["README.md"], "diff_hunk_review": ["review.py"]},
        },
        review_report,
    )
    module_path = tmp_path / "absorbed_capabilities.py"
    write(module_path, content)

    module = load_module(module_path, "generated_absorbed_capabilities")
    plan = module.absorbed_capability_plan()
    depth = module.depth_absorption_plan()
    gate = module.absorption_quality_gate(
        ["retort_engine/pr_review.py", "tests/test_pr_review.py"],
        [{"ok": True, "command": ["pytest", "tests/test_pr_review.py"], "stdout_tail": "6 passed"}],
        minimum_behavior_tests=3,
    )

    assert plan["source"] == "https://github.com/example/reviewer"
    assert plan["minimum_behavior_tests"] == 3
    assert depth["focus_mode"] == "similar_function_depth_only"
    assert [item["component"] for item in depth["ranked_focus_components"]][:1] == ["review_pipeline"]
    assert module.marketplace_candidate_queue() == []
    assert module.deferred_breadth_queue()[0]["component"] == "plugin_surface"
    assert module.depth_first_task_queue()[0]["task_id"] == "retort-depth-review-pipeline"
    assert module.ranked_capabilities()[0]["signal"] in {"review_pipeline", "diff_hunk_review", "file_grouping"}
    assert module.review_strategy_for_file("src/review.py")["strategy"] == "diff_hunk_review"
    assert module.multi_project_reproduction_index(["a", "b", "a"])["ready_for_product_score"] is False
    assert gate["passed"] is True


def test_capability_test_content_targets_generated_module_source() -> None:
    content = real._capability_test_content("retort_engine.absorbed_capabilities", "https://github.com/example/reviewer")

    assert "EXPECTED_ABSORPTION_SOURCE = 'https://github.com/example/reviewer'" in content
    assert "test_absorbed_capability_plan_has_ranked_behavior_signals" in content
    assert "test_absorption_quality_gate_passes_with_behavior_depth" in content


def test_capability_import_name_handles_package_and_root_modules(tmp_path: Path) -> None:
    package = tmp_path / "retort_engine"
    package.mkdir()
    write(package / "__init__.py", "")
    assert real._capability_import_name(tmp_path, package / "absorbed_capabilities.py") == "retort_engine.absorbed_capabilities"
    assert real._capability_import_name(tmp_path, tmp_path / "tests" / "test_absorbed_capabilities.py") == "test_absorbed_capabilities"
    assert real._capability_import_name(tmp_path, tmp_path / "absorbed_capabilities.py") == "absorbed_capabilities"


def test_snapshot_changed_files_and_synthetic_diff(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    write(first, "VALUE = 1\n")
    before = real._snapshot([first, second])
    write(first, "VALUE = 2\n")
    write(second, "VALUE = 3\n")

    changed = real._changed_files(before, [first, second])
    diff_text = real._synthetic_file_diff(tmp_path, second)

    assert changed == [str(first), str(second)]
    assert "diff --git a/second.py b/second.py" in diff_text
    assert "+VALUE = 3" in diff_text


def test_execution_result_and_run_id_are_stable_shape(tmp_path: Path) -> None:
    started = real.time.monotonic()
    result = real._execution_result(
        "applied",
        tmp_path,
        "https://github.com/example/reviewer",
        started,
        [str(tmp_path / "feature.py")],
        [{"ok": True, "command": ["pytest"], "stdout_tail": "1 passed"}],
        ["feature.py | 1 +"],
        "done",
    )
    run_id = real._run_id("https://github.com/example/reviewer")

    assert result["status"] == "applied"
    assert result["gates_passed"] is True
    assert result["commands"] == [["pytest"]]
    assert result["git_diff_summary"] == ["feature.py | 1 +"]
    assert run_id.endswith("-" + real.hashlib.sha1(b"https://github.com/example/reviewer").hexdigest()[:10])


def test_run_command_captures_success_failure_and_tail(tmp_path: Path) -> None:
    success = real._run_command([sys.executable, "-c", "print('ok')"], tmp_path, timeout=30)
    failure = real._run_command([sys.executable, "-c", "import sys; print('bad'); sys.exit(7)"], tmp_path, timeout=30)

    assert success["ok"] is True
    assert success["exit_code"] == 0
    assert "ok" in success["stdout_tail"]
    assert failure["ok"] is False
    assert failure["exit_code"] == 7
    assert "bad" in failure["stdout_tail"]


def test_write_execution_queue_records_appends_json_lines(tmp_path: Path) -> None:
    queue = tmp_path / "queue.jsonl"
    count = real._write_execution_queue_records(
        str(queue),
        "run-4",
        "https://github.com/example/reviewer",
        [{"task_id": "t1"}, {"task_id": "t2"}],
    )

    rows = [json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines()]
    assert count == 2
    assert [row["task"]["task_id"] for row in rows] == ["t1", "t2"]
    assert all(row["status"] == "executing" for row in rows)
    assert all(row["run_id"] == "run-4" for row in rows)


def test_git_diff_summary_falls_back_to_line_counts_for_unstaged_new_file(tmp_path: Path) -> None:
    init_repo(tmp_path)
    new_file = tmp_path / "feature.py"
    write(new_file, "VALUE = 1\nVALUE = 2\n")

    summary = real._git_diff_summary(tmp_path, [str(new_file)])

    assert summary == ["feature.py | 2 lines"]


def test_record_execution_writes_replayable_json(tmp_path: Path) -> None:
    result = {
        "run_id": "run-5",
        "status": "applied",
        "changed_files": ["feature.py"],
        "code_graph_proof": {
            "run_id": "run-5",
            "per_run_required": True,
            "summary": {"graph_status": "ready", "changed_file_count": 1},
            "evidence": {"style": "deterministic_post_absorption_code_graph", "scope": "per_real_absorption_run"},
        },
    }

    real._record_execution(tmp_path, result)

    path = tmp_path / ".retort" / "real_absorption_runs" / "run-5.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))
    assert recorded["run_id"] == "run-5"
    assert recorded["code_graph_proof"]["run_id"] == "run-5"
    assert recorded["code_graph_proof"]["per_run_required"] is True
    assert recorded["run_record_path"] == str(path)
