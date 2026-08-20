# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _load_registry_aligned_employee_manifest(
    pack_dir: _facade().Path, pack_id: str
) -> _facade().Dict[str, _facade().Any]:
    mf = pack_dir / "manifest.json"
    raw = _facade().json.loads(mf.read_text(encoding="utf-8"))
    aligned, errs = _facade().normalize_editor_manifest_for_registry(raw, pack_id)
    if errs:
        from modman.artifact_constants import normalize_artifact

        if normalize_artifact(aligned) != "employee_pack":
            raise ValueError("manifest 规范化失败: " + "; ".join(errs))
    return aligned
