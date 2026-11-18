"""S3 对象导入：URI 校验、大小限制、桶白名单与路由暂存清理。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.infrastructure.document_parsing.object_store import (
    FetchedObject,
    fetch_object,
    parse_s3_uri,
)


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, data: bytes = b"hello", error: Exception | None = None) -> None:
        self.body = _Body(data)
        self.error = error
        self.calls: list[dict] = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"Body": self.body}


def test_parse_s3_uri_valid_and_invalid() -> None:
    assert parse_s3_uri("s3://bucket/a/b.pdf") == ("bucket", "a/b.pdf")
    with pytest.raises(ValueError, match="s3://"):
        parse_s3_uri("https://bucket/a")
    with pytest.raises(ValueError, match="桶名和对象键"):
        parse_s3_uri("s3://bucket")
    with pytest.raises(ValueError, match="非法字符"):
        parse_s3_uri("s3://bucket/a\\b")


def test_fetch_object_reads_and_closes_body() -> None:
    client = _Client(b"payload")
    obj = fetch_object("s3://kb/docs/a.pdf", client=client)
    assert obj == FetchedObject(bucket="kb", key="docs/a.pdf", filename="a.pdf", data=b"payload")
    assert client.body.closed is True


def test_fetch_object_rejects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_MAX_OBJECT_BYTES", "4")
    with pytest.raises(ValueError, match="大小限制"):
        fetch_object("s3://kb/a.pdf", client=_Client(b"123456"))


def test_fetch_object_rejects_bucket_outside_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_S3_ALLOWED_BUCKETS", "allowed,other")
    with pytest.raises(ValueError, match="桶不在允许列表"):
        fetch_object("s3://forbidden/a.pdf", client=_Client())


def test_fetch_object_normalizes_client_error() -> None:
    with pytest.raises(ValueError, match="对象存储读取失败"):
        fetch_object("s3://kb/a.pdf", client=_Client(error=RuntimeError("NoSuchKey")))


def _route_client(dispatch_response: JSONResponse | Exception, calls: list[dict]) -> TestClient:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    def _dispatch(**kwargs):
        calls.append(kwargs)
        if isinstance(dispatch_response, Exception):
            raise dispatch_response
        return dispatch_response

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.ingestion)
    return TestClient(app, raise_server_exceptions=False)


def test_s3_ingest_stages_file_and_keeps_it_when_accepted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.document_parsing.object_store.fetch_object",
        lambda uri: FetchedObject(bucket="kb", key="a.pdf", filename="a.pdf", data=b"%PDF-1.4"),
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", lambda: str(tmp_path))
    calls: list[dict] = []
    client = _route_client(JSONResponse({"success": True}), calls)

    response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})

    assert response.status_code == 200
    params = calls[0]["params"]
    staged = Path(params["file_path"])
    assert staged.exists() and staged.suffix == ".pdf"
    assert params["source"] == "a.pdf"
    assert params["document_id"] == "s3://kb/a.pdf"


def test_s3_ingest_removes_staged_file_when_ingest_rejects(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.document_parsing.object_store.fetch_object",
        lambda uri: FetchedObject(bucket="kb", key="a.pdf", filename="a.pdf", data=b"x"),
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", lambda: str(tmp_path))
    calls: list[dict] = []
    client = _route_client(
        JSONResponse({"success": False, "error_code": "dataset_ingest_failed"}, status_code=200),
        calls,
    )

    response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})

    assert response.status_code == 200
    assert not Path(calls[0]["params"]["file_path"]).exists()


def test_s3_ingest_rejects_unsupported_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", lambda: str(tmp_path))
    calls: list[dict] = []
    client = _route_client(JSONResponse({"success": True}), calls)

    response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/run.exe"})

    assert response.status_code == 400
    assert "不支持的对象类型" in response.json()["detail"]
    assert calls == []


def test_s3_uri_cannot_be_combined_with_other_sources() -> None:
    calls: list[dict] = []
    client = _route_client(JSONResponse({"success": True}), calls)

    response = client.post(
        "/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf", "text": "inline"}
    )

    assert response.status_code == 422
    assert calls == []


@pytest.fixture
def staged_objects(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.document_parsing.object_store.fetch_object",
        lambda _uri: FetchedObject(bucket="kb", key="a.pdf", filename="a.pdf", data=b"private"),
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", lambda: str(tmp_path))
    return tmp_path


def test_s3_staging_rejects_symlink_escape(staged_objects, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    target = staged_objects / "knowledge"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    calls = []
    with _route_client(JSONResponse({"success": True}), calls) as client:
        response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})
    assert response.status_code == 400 and "目录无效" in response.json()["detail"]
    assert not list(outside.iterdir()) and calls == []


def test_s3_staging_ignores_dataset_named_paths(staged_objects, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    legacy_dataset_path = staged_objects / "knowledge" / "kb"
    legacy_dataset_path.parent.mkdir(parents=True)
    legacy_dataset_path.symlink_to(outside, target_is_directory=True)
    calls = []
    with _route_client(JSONResponse({"success": True}), calls) as client:
        response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})

    assert response.status_code == 200
    staged = Path(calls[0]["params"]["file_path"])
    assert staged.parent == staged_objects / "knowledge"
    assert staged.read_bytes() == b"private"
    assert not list(outside.iterdir())


@pytest.mark.parametrize("dataset_id", ["..", "../outside", "/absolute", "\\..\\escape"])
def test_s3_dataset_names_cannot_escape_upload_root(staged_objects, dataset_id):
    from fastapi import Request

    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes
    from app.fastapi_routes.knowledge.schemas import DatasetDocumentIngestRequest

    saved = []

    def dispatch(**kwargs):
        assert kwargs["params"]["dataset_id"] == dataset_id
        saved.append(Path(kwargs["params"]["file_path"]))
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: dispatch, uploads=lambda _get: None)
    response = routes.ingest_dataset_document(
        dataset_id,
        DatasetDocumentIngestRequest(s3_uri="s3://kb/a.pdf"),
        Request({"type": "http", "headers": []}),
    )
    assert response.status_code == 200
    assert saved[0].parent == staged_objects / "knowledge"
    assert saved[0].read_bytes() == b"private"


@pytest.mark.parametrize("key", ["folder/report.PDF", "folder/../../report.pdf"])
def test_s3_staging_uses_generated_names_and_canonical_extension(staged_objects, key):
    calls = []
    with _route_client(JSONResponse({"success": True}), calls) as client:
        for dataset_id in ("first", "second"):
            response = client.post(
                f"/datasets/{dataset_id}/documents", json={"s3_uri": f"s3://kb/{key}"}
            )
            assert response.status_code == 200

    paths = [Path(call["params"]["file_path"]) for call in calls]
    assert paths[0] != paths[1]
    for path in paths:
        assert path.parent == staged_objects / "knowledge"
        assert path.suffix == ".pdf"
        assert path.name != "report.pdf"
        assert path.read_bytes() == b"private"


def test_s3_dispatch_failure_cleans_only_owned_file(staged_objects):
    existing = staged_objects / "knowledge" / "kb" / "existing.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"previous accepted input")
    calls = []
    with _route_client(RuntimeError("dispatch failed"), calls) as client:
        response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})
    assert response.status_code == 500
    assert not Path(calls[0]["params"]["file_path"]).exists()
    assert existing.read_bytes() == b"previous accepted input"


def test_s3_pending_ingestion_keeps_owned_file(staged_objects):
    calls = []
    with _route_client(
        JSONResponse({"success": False, "agent_status": "waiting_user"}), calls
    ) as client:
        response = client.post("/datasets/kb/documents", json={"s3_uri": "s3://kb/a.pdf"})
    assert response.status_code == 200
    assert Path(calls[0]["params"]["file_path"]).read_bytes() == b"private"
