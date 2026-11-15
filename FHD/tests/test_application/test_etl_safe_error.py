"""ELT 错误映射：结构落后不能伪装成「文件有问题」。"""

from __future__ import annotations

import zipfile

import pytest
from sqlalchemy.exc import OperationalError

from app.application.elt.service_support import safe_error


def _operational(message: str) -> OperationalError:
    return OperationalError("insert into elt_run_rows", {}, Exception(message))


def test_missing_column_maps_to_schema_outdated():
    code, message = safe_error(_operational("table elt_run_rows has no column named source_slice"))
    assert code == "ELT_SCHEMA_OUTDATED"
    assert "重启应用" in message


def test_missing_table_maps_to_schema_outdated():
    code, _ = safe_error(_operational("no such table: elt_run_rows"))
    assert code == "ELT_SCHEMA_OUTDATED"


def test_corrupt_zip_still_maps_to_file_corrupted():
    code, _ = safe_error(zipfile.BadZipFile("File is not a zip file"))
    assert code == "ELT_FILE_CORRUPTED"


def test_unknown_error_keeps_internal_code():
    code, message = safe_error(RuntimeError("boom"))
    assert code == "ELT_INTERNAL_ERROR"
    assert "检查文件" in message


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
