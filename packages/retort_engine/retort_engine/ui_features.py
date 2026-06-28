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
        "opsDashboard",
        "opsLlm",
        "opsGates",
        "opsProof",
        "opsRatio",
        "opsBranch",
    }
    required_functions = {
        "drawAbsorptionScene",
        "drawAbsorptionPlanet",
        "renderDevourSession",
        "beginAbsorption",
        "renderOpsDashboard",
        "draw",
    }
    return {
        "frontend_root": str(frontend),
        "index_exists": index.is_file(),
        "app_exists": app.is_file(),
        "required_ids_present": sorted(required_ids & parser.ids),
        "missing_ids": sorted(required_ids - parser.ids),
        "canvas_visual": parser.blackhole_canvas_data,
        "has_app_script": "/app.js" in parser.scripts,
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


def _frontend_root(project_path: Path) -> Path:
    if (project_path / "retort_engine" / "frontend").is_dir():
        return project_path / "retort_engine" / "frontend"
    return project_path / "frontend"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
