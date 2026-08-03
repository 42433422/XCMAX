from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_mod.py"
SPEC = importlib.util.spec_from_file_location("build_mod", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_missing_artifact_defaults_to_mod_and_uses_xcmod(tmp_path: Path) -> None:
    source = tmp_path / "sample-mod"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"id": "sample-mod", "name": "Sample", "version": "1.0.0"}),
        encoding="utf-8",
    )
    package, meta = builder.build_xcemp(source, tmp_path / "dist")
    assert package.suffix == ".xcmod"
    assert meta["artifact"] == "mod"


def test_employee_pack_uses_xcemp(tmp_path: Path) -> None:
    source = tmp_path / "sample-employee"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "id": "sample-employee",
                "name": "Sample Employee",
                "version": "1.0.0",
                "artifact": "employee_pack",
            }
        ),
        encoding="utf-8",
    )
    package, meta = builder.build_xcemp(source, tmp_path / "dist")
    assert package.suffix == ".xcemp"
    assert meta["artifact"] == "employee_pack"


def test_package_is_reproducible_across_mtime_and_output_directory(tmp_path: Path) -> None:
    source = tmp_path / "deterministic-employee"
    (source / "nested").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "id": "deterministic-employee",
                "name": "Deterministic Employee",
                "version": "1.0.0",
                "artifact": "employee_pack",
            }
        ),
        encoding="utf-8",
    )
    (source / "nested" / "worker.py").write_text("print('ok')\n", encoding="utf-8")

    first_package, first_meta = builder.build_xcemp(source, tmp_path / "first")
    os.utime(source / "manifest.json", (2_000_000_000, 2_000_000_000))
    os.utime(source / "nested" / "worker.py", (2_000_000_001, 2_000_000_001))
    second_package, second_meta = builder.build_xcemp(source, tmp_path / "second")

    assert first_package.read_bytes() == second_package.read_bytes()
    assert first_meta["sha256"] == second_meta["sha256"]
    assert first_meta["files"] == ["manifest.json", "nested/worker.py"]
