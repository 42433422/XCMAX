"""XCAGI LangGraph vendored-source assertions — LG-W1-T3.

Boot-time, fail-closed verification that every LangGraph runtime module resolves
to a vendored ``FHD/packages/xcagi_langgraph_*`` editable source (never a PyPI
site-packages distribution), and that each package's ``PROVENANCE.json`` pins
upstream tag ``1.2.10`` at commit ``41341457…`` under the MIT license.

No ``sys.path`` / ``PYTHONPATH`` manipulation and no network access — this runs
once per process at boot, on top of an ``uv sync``-ed venv. Any mismatch raises
``AssertionError`` so the process refuses to start on a non-vendored graph.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Final

UPSTREAM_TAG: Final[str] = "1.2.10"
UPSTREAM_COMMIT: Final[str] = "41341457342327166d72fc11952ab28fb61ec0bf"
UPSTREAM_LICENSE: Final[str] = "MIT"

# vendored module -> package directory relative to FHD/packages that must own it.
# Assertions target concrete submodules (not ``langgraph.__file__``).
REQUIRED_VENDORED_MODULES: Final[dict[str, str]] = {
    "langgraph.graph.state": "xcagi_langgraph_core",
    "langgraph.prebuilt.tool_node": "xcagi_langgraph_prebuilt",
    "langgraph.checkpoint.sqlite": "xcagi_langgraph_checkpoint_backends/checkpoint-sqlite",
    "langgraph.checkpoint.postgres": "xcagi_langgraph_checkpoint_backends/checkpoint-postgres",
    "langgraph_sdk.client": "xcagi_langgraph_sdk",
}


def _packages_root() -> Path:
    """FHD/packages (repo root of this file is FHD/app/infrastructure/workflow)."""
    return Path(__file__).resolve().parents[3] / "packages"


def _assert_module_source(module_name: str, expected_pkg: str) -> None:
    module = importlib.import_module(module_name)
    source = getattr(module, "__file__", "") or ""
    if not source:
        raise AssertionError(f"{module_name} 缺少 __file__（疑似命名空间包）")
    resolved = Path(source).resolve()
    if not resolved.is_relative_to(_packages_root()):
        raise AssertionError(f"{module_name} 未解析到 vendored packages: {resolved}")
    if expected_pkg not in resolved.as_posix():
        raise AssertionError(f"{module_name} 来自 {resolved}，不属于期望包 {expected_pkg}")


def _assert_provenance(package_dir: str) -> None:
    prov_path = _packages_root() / package_dir / "PROVENANCE.json"
    if not prov_path.exists():
        raise AssertionError(f"缺少 PROVENANCE.json: {prov_path}")
    data = json.loads(prov_path.read_text(encoding="utf-8"))
    actual_tag = data.get("upstream_tag")
    actual_sha = data.get("upstream_commit_sha")
    actual_lic = data.get("license")
    if actual_tag != UPSTREAM_TAG:
        raise AssertionError(
            f"{package_dir} PROVENANCE upstream_tag={actual_tag!r} != {UPSTREAM_TAG!r}"
        )
    if actual_sha != UPSTREAM_COMMIT:
        raise AssertionError(
            f"{package_dir} PROVENANCE commit={actual_sha!r} != {UPSTREAM_COMMIT!r}"
        )
    if actual_lic != UPSTREAM_LICENSE:
        raise AssertionError(
            f"{package_dir} PROVENANCE license={actual_lic!r} != {UPSTREAM_LICENSE!r}"
        )


def assert_vendored_sources() -> None:
    """Fail-closed: every vendored module + provenance must match expectations."""
    for module_name, pkg in REQUIRED_VENDORED_MODULES.items():
        _assert_module_source(module_name, pkg)
        _assert_provenance(pkg)
