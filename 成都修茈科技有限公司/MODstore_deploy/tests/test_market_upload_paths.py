from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server.api import market_routes


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("package.zip", ".zip"),
        ("PACKAGE.XCMOD", ".xcmod"),
        ("../../caller-selected.xcemp", ".xcemp"),
        ("package.exe", None),
        ("package.zip.exe", None),
    ],
)
def test_catalog_suffix_is_allowlisted(raw_name: str, expected: str | None) -> None:
    assert market_routes._catalog_suffix(raw_name) == expected


def test_new_catalog_file_uses_server_generated_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market_routes, "_catalog_files_dir", lambda: tmp_path)

    destination, stored_name = market_routes._new_catalog_file(".zip")

    assert destination == tmp_path / stored_name
    assert destination.parent == tmp_path
    assert destination.suffix == ".zip"
    assert "caller-selected" not in stored_name


def test_new_catalog_file_rejects_unsupported_suffix() -> None:
    with pytest.raises(ValueError, match="unsupported catalog suffix"):
        market_routes._new_catalog_file("../../outside.exe")


def test_existing_upload_session_matches_trusted_directory_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "server-session"
    session.mkdir()
    monkeypatch.setattr(market_routes, "_upload_chunks_dir", lambda: tmp_path)

    assert market_routes._existing_upload_session("server-session") == session
    assert market_routes._existing_upload_session("../server-session") is None


def test_existing_upload_session_rejects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "session-link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(market_routes, "_upload_chunks_dir", lambda: tmp_path)

    assert market_routes._existing_upload_session("session-link") is None
