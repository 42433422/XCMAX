# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_ai_scaffold")


def _sub_template(text: str, mod_id: str, mod_name: str) -> str:
    return text.replace("__MOD_ID__", mod_id).replace("__MOD_NAME__", mod_name)


def build_scaffold_zip(
    mod_id: str,
    mod_name: str,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    extra_files: _facade().Optional[_facade().Dict[str, str]] = None,
) -> bytes:
    td = _facade().template_dir()
    files: _facade().Dict[str, str] = {
        "manifest.json": _facade().json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    }
    for rel in (
        "backend/__init__.py",
        "backend/blueprints.py",
        "frontend/routes.js",
        "frontend/views/HomeView.vue",
    ):
        p = td / rel
        if not p.is_file():
            raise FileNotFoundError(f"缺少模板: {p}")
        files[rel] = _facade()._sub_template(p.read_text(encoding="utf-8"), mod_id, mod_name)
    if extra_files:
        for arc, body in extra_files.items():
            files[str(arc).replace("\\", "/").lstrip("/")] = str(body)
    buf = _facade().io.BytesIO()
    with _facade().zipfile.ZipFile(buf, "w", _facade().zipfile.ZIP_DEFLATED) as zf:
        for arc, body in files.items():
            zf.writestr(f"{mod_id}/{arc}", body)
    return buf.getvalue()
