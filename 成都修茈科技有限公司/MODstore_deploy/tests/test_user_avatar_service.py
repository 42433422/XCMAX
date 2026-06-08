import pytest
from fastapi import HTTPException

from modstore_server.user_avatar_service import (
    avatar_public_url,
    resolve_avatar_file,
    save_user_avatar,
)


def test_avatar_public_url_version():
    assert avatar_public_url(3) == "/api/auth/avatar/file?v=3"


def test_resolve_avatar_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DATA_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc:
        resolve_avatar_file("user_avatars/1/../../etc/passwd")
    assert exc.value.status_code == 400


def test_save_user_avatar_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DATA_DIR", str(tmp_path))
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    relpath, mime = save_user_avatar(42, png_header, "photo.png")
    assert relpath == "user_avatars/42/avatar.png"
    assert mime == "image/png"
    path = resolve_avatar_file(relpath)
    assert path.is_file()
    assert path.read_bytes() == png_header
