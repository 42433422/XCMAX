"""Package a :class:`CodeSkill` into a MODstore-compatible ``.xcmod`` zip.

The packager produces the layout that ``modstore_server`` accepts via
``POST /api/admin/catalog`` and that ``modman`` accepts via ``ingest_mod``:

::

    <pkg_id>-<version>.xcmod
    ├── manifest.json
    ├── README.md
    ├── backend/
    │   ├── __init__.py
    │   ├── mod_init.py        # blueprint init: registers the FastAPI router
    │   ├── blueprints.py      # exposes ``run`` as POST /<pkg_id>/run
    │   └── skill.py           # verbatim copy of the skill's active source
    ├── frontend/
    │   └── routes.json        # placeholder so the manifest validator passes
    └── meta/
        ├── skill.json         # full :class:`CodeSkill` dataclass dump
        └── tests.json         # built-in test cases for downstream verification

The artifact uses the manifest schema documented in
``MODstore_deploy/templates/skeleton/manifest.json``. The minimal fields
the catalog API needs (``pkg_id``, ``version``, ``name``, ``description``,
``price``, ``artifact``, ``industry``) are filled from the
:class:`SkillPackageOptions`.

The packager is **pure Python** with no network or MODstore dependency,
so it's trivial to test in isolation: feed it a :class:`CodeSkill` →
get back a :class:`PackagedArtifact` pointing at a temp file you can
inspect, upload, or feed to ``modman ingest``.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..._internals import CodeSkill

_PKG_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[a-zA-Z0-9._+-]+$")


class PackagingError(RuntimeError):
    """Raised when the skill cannot be packaged into a valid mod."""


@dataclass(slots=True)
class SkillPackageOptions:
    """Tunables for :class:`SkillPackager`.

    ``pkg_id`` defaults to ``vc-<skill_id>`` so packages always start with
    a stable lowercase namespace. ``version`` defaults to the skill's
    active version (``v<n>``) so re-packaging the same skill twice never
    overwrites a previous upload.
    """

    pkg_id: str = ""
    version: str = ""
    name: str = ""
    description: str = ""
    author: str = "vibe-coding"
    industry: str = "通用"
    artifact: str = "mod"  # or "employee_pack"
    primary: bool = False
    extra_manifest: dict[str, Any] = field(default_factory=dict)
    include_test_cases: bool = True
    include_readme: bool = True


@dataclass(slots=True)
class PackagedArtifact:
    """Describes the resulting ``.xcmod`` zip on disk."""

    pkg_id: str
    version: str
    name: str
    artifact: str
    archive_path: Path
    manifest: dict[str, Any]
    skill_id: str = ""
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pkg_id": self.pkg_id,
            "version": self.version,
            "name": self.name,
            "artifact": self.artifact,
            "archive_path": str(self.archive_path),
            "manifest": self.manifest,
            "skill_id": self.skill_id,
            "sha256": self.sha256,
        }


class SkillPackager:
    """Bundle a :class:`CodeSkill` (and optional siblings) into a ``.xcmod`` zip."""

    def __init__(self, *, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else None

    def package_skill(
        self,
        skill: CodeSkill,
        options: SkillPackageOptions | None = None,
        *,
        siblings: Iterable[CodeSkill] | None = None,
    ) -> PackagedArtifact:
        """Materialise ``skill`` plus any ``siblings`` into a ``.xcmod`` zip.

        ``siblings`` lets a workflow ship multiple skills in one mod —
        useful when ``VibeCoder.workflow()`` produced a graph and you
        want every node available behind the same blueprint.
        """
        opts = self._normalise_options(skill, options)
        siblings_list = list(siblings or [])
        out_dir = self._resolve_output_dir()
        with tempfile.TemporaryDirectory() as staging_root:
            staging = Path(staging_root) / opts.pkg_id
            staging.mkdir(parents=True, exist_ok=True)
            manifest = self._write_manifest(staging, skill, opts, siblings_list)
            self._write_backend(staging, skill, siblings_list, opts)
            self._write_frontend(staging, opts)
            self._write_meta(staging, skill, siblings_list, opts)
            if opts.include_readme:
                self._write_readme(staging, skill, opts)
            archive_path = out_dir / f"{opts.pkg_id}-{opts.version}.xcmod"
            sha256 = _zip_directory(staging, archive_path)
        return PackagedArtifact(
            pkg_id=opts.pkg_id,
            version=opts.version,
            name=opts.name,
            artifact=opts.artifact,
            archive_path=archive_path,
            manifest=manifest,
            skill_id=skill.skill_id,
            sha256=sha256,
        )

    # ------------------------------------------------------------------ helpers

    def _resolve_output_dir(self) -> Path:
        target = self.output_dir or Path(tempfile.gettempdir()) / "vibe_coding_packages"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _normalise_options(
        self,
        skill: CodeSkill,
        options: SkillPackageOptions | None,
    ) -> SkillPackageOptions:
        opts = options or SkillPackageOptions()
        if not opts.pkg_id:
            opts.pkg_id = _slugify(f"vc-{skill.skill_id}")
        if not _PKG_ID_RE.match(opts.pkg_id):
            raise PackagingError(
                f"pkg_id {opts.pkg_id!r} must match {_PKG_ID_RE.pattern}"
            )
        if not opts.version:
            opts.version = f"1.0.{skill.active_version or 0}"
        if not _VERSION_RE.match(opts.version):
            raise PackagingError(
                f"version {opts.version!r} must match {_VERSION_RE.pattern}"
            )
        if not opts.name:
            opts.name = getattr(skill, "name", "") or skill.skill_id
        if not opts.description:
            opts.description = (
                _first_docstring(skill.get_active_version().source_code)
                or f"Skill {skill.skill_id} generated by vibe-coding"
            )
        return opts

    def _write_manifest(
        self,
        staging: Path,
        skill: CodeSkill,
        opts: SkillPackageOptions,
        siblings: list[CodeSkill],
    ) -> dict[str, Any]:
        manifest: dict[str, Any] = {
            "id": opts.pkg_id,
            "name": opts.name,
            "version": opts.version,
            "author": opts.author,
            "description": opts.description,
            "primary": opts.primary,
            "artifact": opts.artifact,
            "industry": {"id": opts.industry, "name": opts.industry, "scenario": ""},
            "dependencies": {"xcagi": ">=1.0.0"},
            "backend": {
                "entry": "blueprints",
                "init": "mod_init",
            },
            "frontend": {
                "routes": "frontend/routes.json",
                "menu": [],
                "menu_overrides": [],
            },
            "hooks": {},
            "comms": {
                "exports": [
                    {
                        "id": skill.skill_id,
                        "function_name": skill.get_active_version().function_name,
                    },
                    *[
                        {"id": s.skill_id, "function_name": s.get_active_version().function_name}
                        for s in siblings
                    ],
                ]
            },
            "vibe_coding": {
                "skill_id": skill.skill_id,
                "active_version": skill.active_version,
                "siblings": [s.skill_id for s in siblings],
            },
        }
        if opts.artifact == "employee_pack":
            manifest["employee"] = {"id": opts.pkg_id}
            manifest["scope"] = "global"
        if opts.extra_manifest:
            for key, value in opts.extra_manifest.items():
                manifest[key] = value
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    def _write_backend(
        self,
        staging: Path,
        skill: CodeSkill,
        siblings: list[CodeSkill],
        opts: SkillPackageOptions,
    ) -> None:
        backend = staging / "backend"
        backend.mkdir(parents=True, exist_ok=True)
        (backend / "__init__.py").write_text("", encoding="utf-8")

        # The skill's source code goes verbatim into ``skill.py``.
        active = skill.get_active_version()
        (backend / "skill.py").write_text(active.source_code, encoding="utf-8")

        for sib in siblings:
            sib_path = backend / f"skill_{_slugify(sib.skill_id)}.py"
            sib_path.write_text(sib.get_active_version().source_code, encoding="utf-8")

        # mod_init: register the FastAPI router with the host application.
        init_src = (
            "from __future__ import annotations\n\n"
            "from .blueprints import build_router\n\n\n"
            "def mod_init(app, **kwargs):\n"
            '    """Hook called by XCAGI / MODstore to mount the mod."""\n'
            "    router = build_router()\n"
            "    if hasattr(app, 'include_router'):\n"
            "        app.include_router(router)\n"
            "    return {'mounted': True}\n"
        )
        (backend / "mod_init.py").write_text(init_src, encoding="utf-8")

        # blueprints.py: wraps each skill's function as a POST endpoint.
        endpoints = [
            (skill.skill_id, active.function_name),
            *[(s.skill_id, s.get_active_version().function_name) for s in siblings],
        ]
        bp_src = _render_blueprint(opts.pkg_id, endpoints)
        (backend / "blueprints.py").write_text(bp_src, encoding="utf-8")

    def _write_frontend(self, staging: Path, opts: SkillPackageOptions) -> None:
        frontend = staging / "frontend"
        frontend.mkdir(parents=True, exist_ok=True)
        # ``routes.json`` is a placeholder. MODstore's manifest validator
        # only requires this path to exist; concrete routes are filled in
        # by the host that consumes the mod.
        routes = {
            "version": 1,
            "routes": [],
            "_note": "Generated by vibe-coding SkillPackager",
        }
        (frontend / "routes.json").write_text(
            json.dumps(routes, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_meta(
        self,
        staging: Path,
        skill: CodeSkill,
        siblings: list[CodeSkill],
        opts: SkillPackageOptions,
    ) -> None:
        meta = staging / "meta"
        meta.mkdir(parents=True, exist_ok=True)
        skill_dump = {
            "skill_id": skill.skill_id,
            "active_version": skill.active_version,
            "versions": [v.to_dict() for v in skill.versions],
        }
        (meta / "skill.json").write_text(
            json.dumps(skill_dump, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if siblings:
            (meta / "siblings.json").write_text(
                json.dumps(
                    [
                        {
                            "skill_id": s.skill_id,
                            "active_version": s.active_version,
                            "versions": [v.to_dict() for v in s.versions],
                        }
                        for s in siblings
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if opts.include_test_cases:
            cases = [tc.to_dict() for tc in skill.get_active_version().test_cases]
            (meta / "tests.json").write_text(
                json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def _write_readme(
        self,
        staging: Path,
        skill: CodeSkill,
        opts: SkillPackageOptions,
    ) -> None:
        sig = skill.get_active_version().signature
        params = ", ".join(sig.params) or "(no params)"
        text = (
            f"# {opts.name}\n\n"
            f"{opts.description}\n\n"
            f"## Usage\n\n"
            f"```python\n"
            f"from {opts.pkg_id}.backend.skill import {skill.get_active_version().function_name}\n"
            f"{skill.get_active_version().function_name}({params})\n"
            f"```\n\n"
            f"## Generated by\n\n"
            f"vibe-coding {opts.pkg_id}@{opts.version}, "
            f"skill_id={skill.skill_id}, "
            f"active_version={skill.active_version}.\n"
        )
        (staging / "README.md").write_text(text, encoding="utf-8")


# ----------------------------------------------------------------- pure helpers


def _render_blueprint(pkg_id: str, endpoints: list[tuple[str, str]]) -> str:
    """Render a tiny FastAPI router that exposes each skill function.

    Each endpoint accepts a JSON body, calls the underlying function and
    returns its return value. We deliberately avoid importing FastAPI at
    package time so the host can run the validator pre-mount.
    """
    routes_src: list[str] = []
    for skill_id, fn_name in endpoints:
        slug = _slugify(skill_id)
        routes_src.append(
            f"    @router.post('/{slug}/run', name='{slug}_run')\n"
            f"    async def _run_{slug}(payload: dict | None = None):\n"
            f"        from .skill import {fn_name} as _fn\n"
            f"        if payload is None:\n"
            f"            payload = {{}}\n"
            f"        result = _fn(**payload)\n"
            f"        return {{'ok': True, 'result': result}}\n"
        )
    body = "\n".join(routes_src)
    return (
        "from __future__ import annotations\n\n"
        "from typing import Any\n\n\n"
        "def build_router():\n"
        '    """Construct and return a FastAPI APIRouter for this mod."""\n'
        "    from fastapi import APIRouter\n\n"
        f"    router = APIRouter(prefix='/{pkg_id}', tags=['{pkg_id}'])\n\n"
        f"{body}\n"
        "    return router\n"
    )


def _slugify(value: str) -> str:
    """Lowercase + replace non-(alnum/dot/underscore/hyphen) with ``-``.

    Matches ``manifest.id`` validator. Empty inputs yield ``"vc"`` so we
    never produce a leading hyphen.
    """
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned or "vc"


def _first_docstring(source: str) -> str:
    """Pull the first triple-quoted docstring out of ``source`` if any."""
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            doc = ast.get_docstring(node)
            if doc:
                return doc.split("\n")[0].strip()
    return ""


def _zip_directory(staging: Path, archive: Path) -> str:
    """Zip ``staging`` into ``archive`` and return the SHA-256 hex digest.

    The archive is written atomically: we write to a ``*.partial`` sibling
    first then rename — so a crash mid-write never leaves a half-finished
    upload candidate behind.
    """
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(archive.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_dir():
                continue
            arc = path.relative_to(staging.parent).as_posix()
            zf.write(path, arc)
    if archive.exists():
        archive.unlink()
    shutil.move(str(partial), str(archive))
    import hashlib

    h = hashlib.sha256()
    with archive.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "PackagedArtifact",
    "PackagingError",
    "SkillPackageOptions",
    "SkillPackager",
]


