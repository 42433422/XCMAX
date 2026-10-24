"""Use real ZIP files to verify upload and normalized-package ownership."""

from __future__ import annotations

import asyncio
import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, UploadFile

from app.fastapi_routes import mod_store_routes as api
from app.services.mod_zip_normalize import normalize_package_zip_path


def _wrapped_zip() -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("demo/manifest.json", '{"id":"demo","version":"1.0.0"}')
        archive.writestr("demo/README.md", "test package")
    return content.getvalue()


@pytest.fixture
def package_adapters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Mock, Mock]:
    original_named = tempfile.NamedTemporaryFile
    original_mkstemp = tempfile.mkstemp
    monkeypatch.setattr(
        tempfile, "NamedTemporaryFile", lambda **kwargs: original_named(dir=tmp_path, **kwargs)
    )
    monkeypatch.setattr(
        tempfile, "mkstemp", lambda **kwargs: original_mkstemp(dir=tmp_path, **kwargs)
    )
    manager = Mock()
    registry = Mock()
    manager.install_mod_package.return_value = (True, "installed", None)
    registry.install_from_package.return_value = (True, "installed employee")
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    monkeypatch.setattr(
        "app.infrastructure.mods.employee_registry.get_employee_registry", lambda: registry
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.artifact_package.peek_artifact", lambda _path: "mod"
    )
    monkeypatch.setattr(api, "normalize_package_zip_path", normalize_package_zip_path)
    monkeypatch.setattr(api, "_normalize_package_zip", normalize_package_zip_path)
    return manager, registry


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "body"), [("invalid.txt", b"bad"), ("empty.zip", b"")])
async def test_rejected_upload_closes_its_stream(
    name: str, body: bytes, package_adapters: tuple[Mock, Mock], tmp_path: Path
) -> None:
    upload = UploadFile(io.BytesIO(body), filename=name)
    with pytest.raises(HTTPException) as error:
        await api.mod_store_upload(upload, activate=True)
    assert error.value.status_code == 400
    assert upload.file.closed
    assert list(tmp_path.iterdir()) == []
    for adapter in package_adapters:
        assert not adapter.mock_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("employee", [False, True])
@pytest.mark.parametrize("raises", [False, True])
async def test_upload_releases_original_and_real_normalized_zip(
    employee: bool,
    raises: bool,
    monkeypatch: pytest.MonkeyPatch,
    package_adapters: tuple[Mock, Mock],
    tmp_path: Path,
) -> None:
    manager, registry = package_adapters
    installer = registry.install_from_package if employee else manager.install_mod_package
    monkeypatch.setattr(
        "app.infrastructure.mods.artifact_package.peek_artifact",
        lambda _path: "employee_pack" if employee else "mod",
    )
    seen: list[Path] = []

    def install(path: str, **kwargs: bool) -> tuple[bool, str] | tuple[bool, str, None]:
        normalized = Path(path)
        seen.append(normalized)
        with zipfile.ZipFile(normalized) as archive:
            assert "manifest.json" in archive.namelist()
            assert "demo/manifest.json" not in archive.namelist()
        assert kwargs["verify_signature"] is True
        if not employee:
            assert kwargs["activate"] is False
        if raises:
            raise RuntimeError("installer failed")
        return (True, "installed employee") if employee else (True, "installed", None)

    installer.side_effect = install
    upload = UploadFile(io.BytesIO(_wrapped_zip()), filename="demo.xcemp")
    if raises:
        with pytest.raises(RuntimeError, match="installer failed"):
            await api.mod_store_upload(upload, activate=False)
    else:
        result = await api.mod_store_upload(upload, activate=False)
        assert result.success is True
    assert len(seen) == 1
    assert list(tmp_path.iterdir()) == []
    assert upload.file.closed


@pytest.mark.asyncio
async def test_cancelled_upload_closes_stream_and_removes_partial_archive(
    monkeypatch: pytest.MonkeyPatch, package_adapters: tuple[Mock, Mock], tmp_path: Path
) -> None:
    upload = UploadFile(io.BytesIO(b""), filename="demo.zip")
    monkeypatch.setattr(upload, "read", AsyncMock(side_effect=[b"partial", asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await api.mod_store_upload(upload, activate=True)
    assert upload.file.closed
    assert list(tmp_path.iterdir()) == []
    package_adapters[0].install_mod_package.assert_not_called()


@pytest.mark.asyncio
async def test_temporary_file_failure_still_closes_the_upload(
    monkeypatch: pytest.MonkeyPatch, package_adapters: tuple[Mock, Mock], tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", Mock(side_effect=OSError("disk full")))
    upload = UploadFile(io.BytesIO(_wrapped_zip()), filename="demo.zip")
    with pytest.raises(OSError, match="disk full"):
        await api.mod_store_upload(upload, activate=True)
    assert upload.file.closed and list(tmp_path.iterdir()) == []
    package_adapters[0].install_mod_package.assert_not_called()


@pytest.mark.asyncio
async def test_injected_upload_limit_cleans_input_without_reading_facade_state(
    monkeypatch: pytest.MonkeyPatch, package_adapters: tuple[Mock, Mock], tmp_path: Path
) -> None:
    from app.fastapi_routes.mod_store.packages import PackageInstaller

    manager, registry = package_adapters
    installer = PackageInstaller(
        get_json=AsyncMock(),
        download=AsyncMock(),
        normalize_catalog=lambda path: path,
        normalize_upload=lambda path: path,
        artifact=lambda _path: "mod",
        mods=lambda: manager,
        employees=lambda: registry,
        foundation=AsyncMock(),
        logger=api.logger,
        max_upload_bytes=4,
    )
    monkeypatch.setattr(api, "_packages", Mock(side_effect=AssertionError("facade access")))
    upload = UploadFile(io.BytesIO(b"12345"), filename="demo.zip")
    with pytest.raises(HTTPException) as error:
        await installer.upload(upload, activate=True)
    assert error.value.status_code == 413
    assert upload.file.closed and list(tmp_path.iterdir()) == []
    manager.install_mod_package.assert_not_called()


def test_normalizer_removes_its_unreturned_archive_when_reading_fails(
    monkeypatch: pytest.MonkeyPatch, package_adapters: tuple[Mock, Mock], tmp_path: Path
) -> None:
    source = tmp_path / "source.zip"
    original = _wrapped_zip()
    source.write_bytes(original)
    monkeypatch.setattr(zipfile.ZipFile, "read", Mock(side_effect=zipfile.BadZipFile("bad CRC")))
    with pytest.raises(zipfile.BadZipFile, match="bad CRC"):
        normalize_package_zip_path(str(source))
    assert list(tmp_path.iterdir()) == [source]
    assert source.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("digest_ok", [True, False])
async def test_catalog_checks_original_digest_and_cleans_both_archives(
    digest_ok: bool,
    monkeypatch: pytest.MonkeyPatch,
    package_adapters: tuple[Mock, Mock],
    tmp_path: Path,
) -> None:
    body = _wrapped_zip()

    async def download(_path: str, target: Path, **_kwargs: object) -> None:
        target.write_bytes(body)

    monkeypatch.setattr(api, "catalog_download_to", download)
    monkeypatch.setattr(
        "app.mod_sdk.host_foundation.is_host_foundation_employee_pack", lambda _value: False
    )
    monkeypatch.setattr(
        "app.mod_sdk.host_foundation.is_aux_employee_pack_mod_id", lambda _value: False
    )
    digest = hashlib.sha256(body).hexdigest() if digest_ok else "0" * 64
    if digest_ok:
        result = await api._install_from_catalog("demo", "1.0.0", expected_sha256=digest)
        assert result.success is True
        package_adapters[0].install_mod_package.assert_called_once()
    else:
        with pytest.raises(HTTPException) as error:
            await api._install_from_catalog("demo", "1.0.0", expected_sha256=digest)
        assert error.value.status_code == 502
        package_adapters[0].install_mod_package.assert_not_called()
    assert list(tmp_path.iterdir()) == []
