from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class _FrontendParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: set[str] = set()
        self.blackhole_canvas_data = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        element_id = attr.get("id", "")
        if element_id:
            self.ids.add(element_id)
        if tag == "script" and attr.get("src"):
            self.scripts.add(attr["src"])
        if tag == "canvas" and element_id == "blackholeCanvas":
            self.blackhole_canvas_data = attr.get("data-visual", "")


def blackhole_ui_structure(project_path: Path) -> dict[str, Any]:
    """Inspect the Retort UI by DOM ids and rendering functions, not loose keywords."""
    frontend = _frontend_root(project_path)
    index = frontend / "index.html"
    app = frontend / "app.js"
    parser = _FrontendParser()
    parser.feed(_read(index))
    app_text = _read(app)
    required_ids = {
        "blackholeCanvas",
        "deepProgress",
        "progressFill",
        "progressSteps",
        "eventList",
        "sessionState",
        "proofPanel",
    }
    required_functions = {
        "drawAbsorptionScene",
        "drawAbsorptionPlanet",
        "renderDevourSession",
        "beginAbsorption",
        "draw",
    }
    return {
        "frontend_root": str(frontend),
        "index_exists": index.is_file(),
        "app_exists": app.is_file(),
        "required_ids_present": sorted(required_ids & parser.ids),
        "missing_ids": sorted(required_ids - parser.ids),
        "canvas_visual": parser.blackhole_canvas_data,
        "has_app_script": any(script.split("?", 1)[0] == "/app.js" for script in parser.scripts),
        "has_canvas_context": 'getContext("2d")' in app_text or "getContext('2d')" in app_text,
        "required_functions_present": sorted(name for name in required_functions if f"function {name}" in app_text),
        "missing_functions": sorted(name for name in required_functions if f"function {name}" not in app_text),
        "has_animation_loop": "requestAnimationFrame(draw)" in app_text,
    }


def blackhole_ui_detected(project_path: Path) -> bool:
    structure = blackhole_ui_structure(project_path)
    return (
        bool(structure["index_exists"])
        and bool(structure["app_exists"])
        and not structure["missing_ids"]
        and structure["canvas_visual"] == "blackhole-accretion-field"
        and bool(structure["has_app_script"])
        and bool(structure["has_canvas_context"])
        and not structure["missing_functions"]
        and bool(structure["has_animation_loop"])
    )


def blackhole_ui_operation_replay(project_path: Path) -> dict[str, Any]:
    """Replay the expected operator actions from DOM ids and JS bindings."""
    structure = blackhole_ui_structure(project_path)
    frontend = _frontend_root(project_path)
    app_text = _read(frontend / "app.js")
    actions = [
        _action("choose_github_source", structure, app_text, ids=("sourceGithub", "githubUrl"), snippets=("setMode(\"github\")",)),
        _action("run_deep_review", structure, app_text, ids=("assessBtn", "deepProgress", "progressSteps"), snippets=("assessBtn", ".onclick = assess")),
        _action("start_absorption", structure, app_text, ids=("absorbBtn", "sessionState", "executionState"), snippets=("beginAbsorption", ".onclick = absorb")),
        _action("track_flow_panel", structure, app_text, ids=("dualReviewPanel", "comparisonPanel", "proofPanel", "finalReviewPanel"), snippets=("renderDevourSession", "codeGraphProofPanel")),
        _action("click_absorbed_project_light", structure, app_text, ids=("blackholeCanvas",), snippets=("handleAbsorbedProjectClick", "selectAbsorbedProject", "canvas.addEventListener(\"click\"")),
        _action("inspect_refactor_priority", structure, app_text, ids=("refactorPriorityPanel", "codeGraphFocusPanel"), snippets=("refreshEvolutionMap", "refactorPriorityPanel")),
    ]
    ready_actions = [item for item in actions if item["ready"]]
    return {
        "status": "ready" if len(ready_actions) == len(actions) and bool(structure["has_animation_loop"]) else "blocked",
        "summary": {
            "action_count": len(actions),
            "ready_action_count": len(ready_actions),
            "all_actions_bound": len(ready_actions) == len(actions),
            "absorbed_project_click_bound": any(item["name"] == "click_absorbed_project_light" and item["ready"] for item in actions),
            "deep_review_button_bound": any(item["name"] == "run_deep_review" and item["ready"] for item in actions),
            "absorption_button_bound": any(item["name"] == "start_absorption" and item["ready"] for item in actions),
            "flow_panel_bound": any(item["name"] == "track_flow_panel" and item["ready"] for item in actions),
            "animation_loop_bound": bool(structure["has_animation_loop"]),
        },
        "actions": actions,
        "evidence": {
            "model": "static_dom_and_js_binding_operator_replay",
            "frontend_root": str(frontend),
            "claim_boundary": "verifies_operator_controls_and_blackhole_project_click_bindings_without_browser_runtime",
        },
    }


def _action(name: str, structure: dict[str, Any], app_text: str, *, ids: tuple[str, ...], snippets: tuple[str, ...]) -> dict[str, Any]:
    present_ids = set(structure.get("required_ids_present") or [])
    present_ids.update(_all_ids(Path(str(structure["frontend_root"]))))
    missing_ids = [item for item in ids if item not in present_ids]
    missing_snippets = [item for item in snippets if item not in app_text]
    return {
        "name": name,
        "required_ids": list(ids),
        "missing_ids": missing_ids,
        "required_snippets": list(snippets),
        "missing_snippets": missing_snippets,
        "ready": not missing_ids and not missing_snippets,
    }


def _all_ids(frontend: Path) -> set[str]:
    parser = _FrontendParser()
    parser.feed(_read(frontend / "index.html"))
    return set(parser.ids)


def _frontend_root(project_path: Path) -> Path:
    if (project_path / "retort_engine" / "frontend").is_dir():
        return project_path / "retort_engine" / "frontend"
    return project_path / "frontend"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
