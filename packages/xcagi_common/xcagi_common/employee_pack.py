"""Build employee archives without depending on either application runtime."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Iterable

DEFAULT_BACKEND_SUFFIXES = (".py", ".xlsx", ".xlsm", ".xls")
DEFAULT_EXTRA_FILES = ("README.md",)


def _validate_pack_id(pack_id: str) -> str:
    if (
        not isinstance(pack_id, str)
        or not pack_id.strip()
        or pack_id in {".", ".."}
        or any(char in pack_id for char in "/\\:")
        or any(ord(char) < 32 for char in pack_id)
    ):
        raise ValueError("pack_id must be a single non-empty path component")
    return pack_id


def _read_local(root: Path, relative: Path) -> bytes:
    path = root / relative
    if relative.is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError(f"employee pack file escapes its directory: {relative}")
    return path.read_bytes()


def build_employee_pack(
    root: Path,
    *,
    pack_id: str | None = None,
    backend_suffixes: Iterable[str] = DEFAULT_BACKEND_SUFFIXES,
    extra_files: Iterable[str] = DEFAULT_EXTRA_FILES,
) -> Path:
    """Write the established ``pack_id/`` archive layout with repeatable bytes.

    The caller owns its inclusion policy. Build dependencies and builder scripts
    are never shipped inside the runtime archive.
    """
    root = Path(root).resolve()
    manifest = json.loads(_read_local(root, Path("manifest.json")))
    pack_id = _validate_pack_id(pack_id if pack_id is not None else manifest.get("id"))
    if manifest.get("id") != pack_id:
        raise ValueError("pack_id must match manifest.id")
    contents = {
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
    }
    suffixes = frozenset(suffix.lower() for suffix in backend_suffixes)
    for path in sorted((root / "backend").rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            relative = path.relative_to(root)
            contents[relative.as_posix()] = _read_local(root, relative)
    for name in extra_files:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid employee pack extra file: {name}")
        if (root / relative).is_file():
            contents[relative.as_posix()] = _read_local(root, relative)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, content in contents.items():
            entry = zipfile.ZipInfo(f"{pack_id}/{relative}", (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content)
    output = root / f"{pack_id}.xcemp"
    if output.is_symlink():
        raise ValueError("employee pack output must not be a symbolic link")
    output.write_bytes(buffer.getvalue())
    return output


def render_builder_script(
    pack_id: str,
    *,
    backend_suffixes: Iterable[str] = DEFAULT_BACKEND_SUFFIXES,
    extra_files: Iterable[str] = DEFAULT_EXTRA_FILES,
) -> str:
    """Render the same thin entry point for checked-in and generated employees.

    In a checkout, find the shared source package. Exported employee directories
    use the installed ``xcagi-common`` build dependency instead.
    """
    _validate_pack_id(pack_id)
    return f'''"""Build this employee with the shared xcagi-common build dependency."""

import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    source = parent / "packages" / "xcagi_common"
    if (source / "xcagi_common" / "employee_pack.py").is_file():
        sys.path.insert(0, str(source))
        break

from xcagi_common.employee_pack import build_employee_pack


def main() -> None:
    print(
        build_employee_pack(
            Path(__file__).resolve().parent,
            pack_id={json.dumps(pack_id, ensure_ascii=False)},
            backend_suffixes={json.dumps(list(backend_suffixes))},
            extra_files={json.dumps(list(extra_files))},
        )
    )


if __name__ == "__main__":
    main()
'''
