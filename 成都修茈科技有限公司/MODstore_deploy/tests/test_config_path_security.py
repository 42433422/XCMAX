from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from modstore_server.api.config import (
    _configured_repo_path,
    api_export_fhd_shell_mods,
)
from modstore_server.api.dto import ExportFhdShellDTO


def test_configured_repo_path_allows_only_fhd_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fhd = tmp_path / "FHD"
    fhd.mkdir()
    monkeypatch.setattr("modstore_server.api.config.library_paths.fhd_repo_root", lambda: fhd)

    assert _configured_repo_path(str(fhd / "MODstore"), field="library_root") == str(
        fhd / "MODstore"
    )
    with pytest.raises(HTTPException, match="FHD"):
        _configured_repo_path(str(tmp_path / "outside"), field="library_root")


def test_fhd_shell_export_rejects_request_selected_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fhd = tmp_path / "FHD"
    fhd.mkdir()
    monkeypatch.setattr("modstore_server.api.config.library_paths.fhd_repo_root", lambda: fhd)

    with pytest.raises(HTTPException) as exc_info:
        api_export_fhd_shell_mods(ExportFhdShellDTO(output_path="private/output.json"))

    assert exc_info.value.status_code == 400
    assert not (fhd / "private" / "output.json").exists()


def test_fhd_shell_export_uses_declared_product_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fhd = tmp_path / "FHD"
    library = tmp_path / "library"
    fhd.mkdir()
    library.mkdir()
    captured: dict[str, Path] = {}
    monkeypatch.setattr("modstore_server.api.config.library_paths.fhd_repo_root", lambda: fhd)
    monkeypatch.setattr("modstore_server.api.config.library_paths.lib", lambda: library)

    def _write(_library: Path, output: Path, *, output_root: Path) -> int:
        captured.update(output=output, output_root=output_root)
        return 3

    monkeypatch.setattr("modstore_server.api.config.write_fhd_shell_mods_json", _write)

    response = api_export_fhd_shell_mods(ExportFhdShellDTO())

    expected = (fhd / "backend" / "shell" / "fhd_shell_mods.json").resolve()
    assert response == {"ok": True, "path": str(expected), "count": 3}
    assert captured == {"output": expected, "output_root": fhd}
