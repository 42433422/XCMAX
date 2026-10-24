"""Knowledge upload ownership and tenant retrieval boundaries."""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import Request, UploadFile
from fastapi.responses import JSONResponse

from app.fastapi_routes import knowledge_v1 as api
from app.infrastructure.rag.hybrid_retriever import HybridRetriever, RetrievedChunk
from app.infrastructure.rag.semantic_chunker import SemanticChunker


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/upload", "headers": []})


@pytest.fixture
def upload_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", lambda: tmp_path)
    monkeypatch.setattr(
        api, "_run_dataset_rag_agent", lambda **_kwargs: JSONResponse({"success": True})
    )
    return tmp_path


async def _upload(file: UploadFile, *, dataset: str = "docs", **fields: str) -> JSONResponse:
    params = {
        "source": "",
        "tenant_id": "",
        "version": "",
        "version_label": "",
        "chunk_strategy": "semantic",
    }
    params.update(fields)
    return await api.upload_dataset_document(dataset, _request(), file=file, **params)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "fields"),
    [
        ("unsupported.exe", {}),
        ("document.txt", {"source": "x" * 301}),
        ("document.txt", {"tenant_id": "x" * 161}),
        ("document.txt", {"version": "x" * 81}),
        ("document.txt", {"version_label": "x" * 121}),
    ],
)
async def test_rejected_upload_closes_input_without_saving(
    upload_store: Path, name: str, fields: dict[str, str]
) -> None:
    file = UploadFile(filename=name, file=io.BytesIO(b"private document"))
    response = await _upload(file, **fields)
    assert response.status_code == 400
    assert file.file.closed
    assert not list(upload_store.rglob("*.txt"))


@pytest.mark.asyncio
async def test_cancelled_upload_removes_partial_file(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    calls = 0

    async def interrupted_read(_size: int) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            return b"partial private content"
        raise asyncio.CancelledError

    monkeypatch.setattr(file, "read", interrupted_read)
    with pytest.raises(asyncio.CancelledError):
        await _upload(file)
    assert file.file.closed
    assert not list(upload_store.rglob("*.txt"))


@pytest.mark.asyncio
async def test_upload_dispatch_error_releases_saved_file(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(**_kwargs: Any) -> JSONResponse:
        raise RuntimeError("agent unavailable")

    monkeypatch.setattr(api, "_run_dataset_rag_agent", unavailable)
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    with pytest.raises(RuntimeError, match="agent unavailable"):
        await _upload(file)
    assert file.file.closed
    assert not list(upload_store.rglob("*.txt"))


@pytest.mark.asyncio
async def test_upload_directory_error_still_closes_input(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.mkdir

    def unavailable(path: Path, *args: Any, **kwargs: Any) -> None:
        if "knowledge" in path.parts:
            raise PermissionError("upload directory unavailable")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", unavailable)
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    with pytest.raises(PermissionError, match="upload directory unavailable"):
        await _upload(file)
    assert file.file.closed


@pytest.mark.asyncio
async def test_failed_agent_result_releases_file_even_with_http_200(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        api,
        "_run_dataset_rag_agent",
        lambda **_kwargs: JSONResponse({"success": False, "message": "invalid document"}),
    )
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    response = await _upload(file)
    assert response.status_code == 200
    assert file.file.closed
    assert not list(upload_store.rglob("*.txt"))


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "waiting_user", "running"])
async def test_successful_or_pending_agent_keeps_uploaded_input(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    observed: list[Path] = []

    def accept(**kwargs: Any) -> JSONResponse:
        saved = Path(kwargs["params"]["file_path"])
        assert saved.read_bytes() == b"private document"
        observed.append(saved)
        return JSONResponse(
            {"success": state == "completed", "agent_status": state},
            status_code=202 if state == "waiting_user" else 200,
        )

    monkeypatch.setattr(api, "_run_dataset_rag_agent", accept)
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    response = await _upload(file)
    assert response.status_code == (202 if state == "waiting_user" else 200)
    assert file.file.closed
    assert len(observed) == 1 and observed[0].is_file()


@pytest.mark.asyncio
async def test_oversized_upload_is_removed(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_DATASET_UPLOAD_MAX_BYTES", 8)
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    assert (await _upload(file)).status_code == 400
    assert file.file.closed
    assert not list(upload_store.rglob("*.txt"))


@pytest.mark.asyncio
async def test_upload_dataset_segment_cannot_escape_knowledge_directory(upload_store: Path) -> None:
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"private document"))
    assert (await _upload(file, dataset="..")).status_code == 200
    saved = list(upload_store.rglob("*.txt"))
    assert len(saved) == 1
    assert saved[0].resolve().is_relative_to((upload_store / "knowledge").resolve())


@pytest.mark.parametrize("returned_tenant", ["tenant-b", None])
def test_index_rejects_unscoped_or_foreign_results_even_when_text_matches(
    monkeypatch: pytest.MonkeyPatch, returned_tenant: str | None
) -> None:
    retriever = Mock()
    retriever.retrieve.return_value = [
        RetrievedChunk(
            text="shared text",
            score=1.0,
            source="private source",
            metadata={"tenant_id": returned_tenant},
        )
    ]
    monkeypatch.setattr(api, "get_default_embedder", lambda: None)
    monkeypatch.setattr(api, "SemanticChunker", SemanticChunker)
    monkeypatch.setattr(api, "HybridRetriever", lambda **_kwargs: retriever)
    monkeypatch.setattr(api, "RetrievedChunk", RetrievedChunk)
    index = api._KnowledgeIndex()
    index.ingest("shared text", "own source", "fixed", 500, 50, tenant_id="tenant-a")
    assert index.query("shared", 5, tenant_id="tenant-a") == []


def test_real_index_rebuilds_for_each_tenant_without_losing_identical_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "get_default_embedder", lambda: None)
    monkeypatch.setattr(api, "SemanticChunker", SemanticChunker)
    monkeypatch.setattr(api, "HybridRetriever", HybridRetriever)
    monkeypatch.setattr(api, "RetrievedChunk", RetrievedChunk)
    index = api._KnowledgeIndex()
    for tenant in ("tenant-a", "tenant-b"):
        index.ingest("shared text", tenant, "fixed", 500, 50, tenant_id=tenant)
    for tenant in ("tenant-a", "tenant-b", "tenant-a"):
        chunks = index.query("shared", 5, tenant_id=tenant)
        assert len(chunks) == 1
        assert chunks[0].metadata and chunks[0].metadata["tenant_id"] == tenant


@pytest.mark.asyncio
async def test_upload_collision_never_overwrites_or_removes_an_existing_input(
    upload_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = upload_store / "knowledge" / "docs" / "existing.txt"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"accepted document from another request")
    monkeypatch.setattr(
        "app.fastapi_routes.knowledge.uploads.uuid.uuid4", lambda: SimpleNamespace(hex="existing")
    )
    dispatch = Mock()
    monkeypatch.setattr(api, "_run_dataset_rag_agent", dispatch)
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"new private document"))
    assert (await _upload(file)).status_code == 400
    assert existing.read_bytes() == b"accepted document from another request"
    assert file.file.closed
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_upload_component_uses_only_its_injected_dispatch_and_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.fastapi_routes.knowledge.uploads import DocumentUpload

    facade_dispatch = Mock(side_effect=AssertionError("unexpected facade access"))
    monkeypatch.setattr(api, "_run_dataset_rag_agent", facade_dispatch)
    monkeypatch.setattr(api, "_DATASET_UPLOAD_MAX_BYTES", 1)
    seen: list[Path] = []

    def dispatch(**kwargs: Any) -> JSONResponse:
        saved = Path(kwargs["params"]["file_path"])
        assert saved.read_bytes() == b"document"
        seen.append(saved)
        return JSONResponse({"success": True})

    upload = DocumentUpload(
        dispatch=dispatch,
        directory=lambda: tmp_path,
        extensions=frozenset({".txt"}),
        max_bytes=8,
        logger=logging.getLogger(__name__),
    )
    file = UploadFile(filename="document.txt", file=io.BytesIO(b"document"))
    response = await upload.ingest(
        "independent",
        _request(),
        file=file,
        source="",
        tenant_id="",
        version="",
        version_label="",
        chunk_strategy="semantic",
    )
    assert response.status_code == 200 and file.file.closed
    assert len(seen) == 1 and seen[0].is_file()
    facade_dispatch.assert_not_called()
