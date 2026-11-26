"""Original attendance routes isolate policy and bound workbook storage."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from openpyxl import Workbook

BACKEND = Path(__file__).parents[2] / "mods/attendance-industry/backend"


@pytest.fixture
def route_modules(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(BACKEND))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "attendance_conversion_routes", BACKEND / "attendance_routes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import attendance_storage

    return module, attendance_storage


def _workbook() -> bytes:
    workbook = Workbook()
    workbook.active["A1"] = "synthetic"
    data = BytesIO()
    workbook.save(data)
    workbook.close()
    return data.getvalue()


def test_policy_and_conversion_remain_bound_to_the_current_account(
    route_modules, monkeypatch, tmp_path
):
    routes, _ = route_modules
    import attendance_engine.convert as converter

    from resources.config.approval_config import get_approval_config

    host_policy = dict(get_approval_config().attendance_policy)
    captured = []

    def convert(source, destination, **options):
        captured.append(options["attendance_policy"])
        assert Path(source).is_file()
        Path(destination).write_bytes(_workbook())
        return {"success": True, "rows_in": 1, "rows_stats": 1}

    monkeypatch.setattr(converter, "convert_attendance_file", convert)
    (tmp_path / "template.xlsx").write_bytes(_workbook())
    owner = {"id": "tenant:1|user:1"}
    app = FastAPI()
    app.dependency_overrides[routes.require_attendance_conversion] = lambda: None
    app.dependency_overrides[routes.owner_for_request] = lambda: owner["id"]
    router = APIRouter()
    routes.register(
        router,
        logger=logging.getLogger(__name__),
        get_database_path=lambda: tmp_path / "db",
        DEFAULT_TEMPLATE_RELPATH="template.xlsx",
        _normalize_relpath=lambda value, **_: value,
        _resolve_personnel_roster=lambda *_: [],
    )
    app.include_router(router)
    with TestClient(app) as client:
        assert (
            client.post(
                "/attendance/policy",
                json={"attendance_policy": {"weekday_segments": ["09:00-11:00"]}},
            ).status_code
            == 200
        )
        owner["id"] = "tenant:2|user:2"
        assert client.get("/attendance/policy").json()["attendance_policy"]["weekday_segments"] == [
            "08:00-12:00",
            "13:30-17:30",
        ]
        for current in ["tenant:1|user:1", "tenant:2|user:2"]:
            owner["id"] = current
            response = client.post(
                "/attendance/convert-upload",
                data={"use_personnel_roster": "0"},
                files={"file": ("test.xlsx", _workbook())},
            )
            assert response.status_code == 200, response.text
    assert [item["weekday_segments"] for item in captured] == [
        ["09:00-11:00"],
        ["08:00-12:00", "13:30-17:30"],
    ]
    assert get_approval_config().attendance_policy == host_policy
    assert not list(tmp_path.rglob("attendance-upload-*"))


def test_parallel_conversion_policy_is_context_local(route_modules):
    from attendance_engine.rules import ACTIVE_POLICY, set_attendance_policy

    barrier = Barrier(2)

    def read_policy(value):
        token = set_attendance_policy({"weekday_segments": [value]})
        try:
            barrier.wait(timeout=5)
            return ACTIVE_POLICY.get()["weekday_segments"]
        finally:
            ACTIVE_POLICY.reset(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(read_policy, ["08:00-10:00", "09:00-11:00"])) == [
            ["08:00-10:00"],
            ["09:00-11:00"],
        ]


@pytest.mark.parametrize("case", ["oversize", "expanded", "ratio", "corrupt"])
def test_rejected_uploads_are_removed_before_parsing(route_modules, monkeypatch, tmp_path, case):
    _, storage = route_modules
    body = _workbook()
    if case == "oversize":
        monkeypatch.setattr(storage, "MAX_UPLOAD_BYTES", 8)
    elif case == "expanded":
        monkeypatch.setattr(storage, "MAX_EXPANDED_BYTES", 8)
    elif case == "ratio":
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", b"a" * 200_000)
        body = buffer.getvalue()
    else:
        body = b"not a workbook"
    upload = UploadFile(BytesIO(body), filename="test.xlsx")
    with pytest.raises(HTTPException) as error:
        asyncio.run(storage.save_upload(upload, "tenant:1|user:1", ".xlsx"))
    assert error.value.status_code == (400 if case == "corrupt" else 413)
    assert upload.file.closed
    assert not list(tmp_path.rglob("attendance-upload-*"))


def test_cleanup_only_expires_generated_files_for_the_same_owner(route_modules, tmp_path):
    _, storage = route_modules
    from app.mod_sdk.attendance_artifacts import allocate_file

    expired = allocate_file("tenant:1|user:1", "output")
    active = allocate_file("tenant:1|user:1", "output")
    other = allocate_file("tenant:2|user:2", "output")
    unrelated = expired.parent / "customer.xlsx"
    for path in [expired, active, other, unrelated]:
        path.write_bytes(b"preserved")
    old = time.time() - storage.ARTIFACT_TTL_SECONDS - 1
    for path in [expired, other, unrelated]:
        os.utime(path, (old, old))
    path = asyncio.run(
        storage.save_upload(
            UploadFile(BytesIO(_workbook()), filename="test.xlsx"), "tenant:1|user:1", ".xlsx"
        )
    )
    assert path.is_file() and not expired.exists()
    assert all(item.exists() for item in [active, other, unrelated])
