from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from modstore_server.api.config import _configured_repo_path


def test_configured_repo_path_allows_only_fhd_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fhd = tmp_path / "FHD"
    fhd.mkdir()
    monkeypatch.setattr(
        "modstore_server.api.config.library_paths.fhd_repo_root", lambda: fhd
    )

    assert _configured_repo_path(str(fhd / "MODstore"), field="library_root") == str(
        fhd / "MODstore"
    )
    with pytest.raises(HTTPException, match="FHD"):
        _configured_repo_path(str(tmp_path / "outside"), field="library_root")

