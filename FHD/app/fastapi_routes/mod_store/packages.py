"""Own downloaded/uploaded archives and dispatch one verified artifact installation."""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from app.application.mod_store.http_port_contracts import (
    CatalogDownload,
    EmployeePackWriter,
    FoundationInstall,
    JsonGet,
    ModPackageWriter,
)
from app.infrastructure.mods.artifact_constants import ARTIFACT_EMPLOYEE_PACK

from .projection import safe_text
from .schemas import ModStoreInstallResult


@dataclass
class PackageFiles:
    source: str
    normalized: str


class PackageInstaller:
    def __init__(
        self,
        *,
        get_json: JsonGet,
        download: CatalogDownload,
        normalize_catalog: Callable[[str], str],
        normalize_upload: Callable[[str], str],
        artifact: Callable[[str], str],
        mods: Callable[[], ModPackageWriter],
        employees: Callable[[], EmployeePackWriter],
        foundation: FoundationInstall,
        logger: logging.Logger,
        max_upload_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self._get_json = get_json
        self._download = download
        self._normalize_catalog = normalize_catalog
        self._normalize_upload = normalize_upload
        self._artifact = artifact
        self._mods = mods
        self._employees = employees
        self._foundation = foundation
        self._logger = logger
        self._max_upload_bytes = max_upload_bytes

    @contextmanager
    def _temporary_package(self, prefix: str) -> Iterator[PackageFiles]:
        temporary = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".zip", delete=False)
        files = PackageFiles(temporary.name, temporary.name)
        try:
            temporary.close()
            yield files
        finally:
            for path in {files.source, files.normalized}:
                try:
                    if path and os.path.exists(path):
                        os.unlink(path)
                except OSError:
                    self._logger.warning("无法删除临时 Mod 包: %s", path)

    def _install(
        self, path: str, *, verify_signature: bool, activate: bool
    ) -> ModStoreInstallResult:
        if self._artifact(path) == ARTIFACT_EMPLOYEE_PACK:
            ok, message = self._employees().install_from_package(
                path, verify_signature=verify_signature
            )
            return ModStoreInstallResult(success=bool(ok), message=message, data=None)
        ok, message, metadata = self._mods().install_mod_package(
            path, verify_signature=verify_signature, activate=activate
        )
        data = (
            dataclasses.asdict(metadata)
            if metadata and dataclasses.is_dataclass(metadata)
            else None
        )
        return ModStoreInstallResult(success=bool(ok), message=message, data=data)

    async def from_catalog(
        self,
        pkg_id: str,
        version: str,
        activate: bool = True,
        *,
        authorization: str = "",
        download_path: str = "",
        expected_sha256: str = "",
        verify_signature: bool = True,
    ) -> ModStoreInstallResult:
        from app.mod_sdk.host_foundation import (
            install_aux_employee_pack_from_repo_seed,
            is_aux_employee_pack_mod_id,
            is_host_foundation_employee_pack,
        )

        if is_host_foundation_employee_pack(pkg_id):
            return await self._foundation(edition=None)
        if is_aux_employee_pack_mod_id(pkg_id):
            ok, message = install_aux_employee_pack_from_repo_seed(pkg_id, activate=activate)
            if ok:
                return ModStoreInstallResult(success=True, message=message, data={"id": pkg_id})
            self._logger.info("aux employee seed install failed; trying catalog")
        if not pkg_id:
            raise HTTPException(status_code=400, detail="缺少 pkg_id")
        headers = {"Authorization": authorization} if authorization else None
        if not version and not download_path:
            versions = await self._get_json(
                f"/packages/by-id/{quote(pkg_id, safe='')}/versions", headers=headers
            )
            rows = versions.get("versions") or []
            if isinstance(rows, list) and rows:
                first = rows[0]
                version = (
                    safe_text(first.get("version")) if isinstance(first, dict) else safe_text(first)
                )
        if not version and not download_path:
            raise HTTPException(status_code=400, detail="缺少 version")
        with self._temporary_package("xcagi-mod-") as files:
            path = (
                download_path
                or f"/packages/{quote(pkg_id, safe='')}/{quote(version, safe='')}/download"
            )
            await self._download(path, Path(files.source), headers=headers)
            expected = str(expected_sha256 or "").strip().lower()
            if expected:
                actual = hashlib.sha256(Path(files.source).read_bytes()).hexdigest()
                if actual != expected:
                    raise HTTPException(
                        status_code=502,
                        detail=f"远端 Mod 包摘要不一致：expected={expected} actual={actual}",
                    )
            files.normalized = self._normalize_catalog(files.source)
            return self._install(
                files.normalized, verify_signature=verify_signature, activate=activate
            )

    async def upload(self, file: UploadFile, activate: bool) -> ModStoreInstallResult:
        closed = False
        try:
            if not (file.filename or "").lower().endswith((".xcemp", ".zip")):
                raise HTTPException(status_code=400, detail="仅支持 .xcemp 或 .zip 格式的 Mod 包")
            with self._temporary_package("xcagi-upload-") as files:
                total_size = 0
                with open(files.source, "wb") as target:
                    while chunk := await file.read(65536):
                        total_size += len(chunk)
                        if total_size > self._max_upload_bytes:
                            raise HTTPException(
                                status_code=413,
                                detail=f"文件过大（>{self._max_upload_bytes // (1024 * 1024)}MB）",
                            )
                        target.write(chunk)
                if total_size == 0:
                    raise HTTPException(status_code=400, detail="上传文件为空")
                try:
                    await file.close()
                finally:
                    closed = True
                files.normalized = self._normalize_upload(files.source)
                return self._install(files.normalized, verify_signature=True, activate=activate)
        finally:
            if not closed:
                await file.close()
