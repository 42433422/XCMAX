"""Track ownership of one upload until its successful preview or import response."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

SPREADSHEET_SUFFIXES = frozenset({".xls", ".xlsm", ".xlsx"})
OCR_SUFFIXES = SPREADSHEET_SUFFIXES | {".bmp", ".jpeg", ".jpg", ".pdf", ".png", ".tif", ".tiff"}


@dataclass
class StagedInput:
    path: str
    uploaded: bool = False
    retained: bool = False


class UploadStager:
    def __init__(
        self, path_factory: Callable[[str, str, set[str]], str], logger: logging.Logger
    ) -> None:
        self._path_factory = path_factory
        self._logger = logger

    @asynccontextmanager
    async def open(
        self,
        file: UploadFile | None,
        file_path: str,
        *,
        prefix: str,
        suffixes: frozenset[str] = SPREADSHEET_SUFFIXES,
    ) -> AsyncIterator[StagedInput]:
        staged = StagedInput(str(file_path or "").strip())
        closed = False
        try:
            if file is not None and (file.filename or "").strip():
                staged.path = self._path_factory(prefix, str(file.filename), set(suffixes))
                # Exclusive creation keeps a collision from replacing another request's input.
                with open(staged.path, "xb") as target:
                    staged.uploaded = True
                    while chunk := await file.read(1024 * 1024):
                        target.write(chunk)
            if file is not None:
                try:
                    await file.close()
                finally:
                    closed = True
            yield staged
        finally:
            try:
                if file is not None and not closed:
                    await file.close()
            finally:
                # Caller-supplied paths and pre-existing collision targets are never ours.
                if staged.uploaded and not staged.retained:
                    try:
                        Path(staged.path).unlink(missing_ok=True)
                    except OSError:
                        self._logger.warning("Failed to clean rejected ETL upload: %s", staged.path)
