"""本机文件只读授权：路径边界、授权生命周期与增量索引。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.application.local_file_access import indexer, paths, service
from app.infrastructure.tenant_scope import tenant_scope


def _grant(root, mode="folder"):
    return SimpleNamespace(id=1, owner_user_id=1, mode=mode, root_path=str(root), is_active=True)


def _write(path, text="hello"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_resolve_allows_file_inside_grant_root(tmp_path):
    allowed = _write(tmp_path / "docs" / "a.txt")
    assert paths.resolve_authorized_path(_grant(tmp_path), allowed) == allowed.resolve()


def test_resolve_rejects_sibling_prefix(tmp_path):
    root = tmp_path / "work"
    outside = _write(tmp_path / "work-other" / "a.txt")
    root.mkdir()
    with pytest.raises(paths.LocalFilePathError):
        paths.resolve_authorized_path(_grant(root), outside)


def test_resolve_rejects_symlink_escape(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    outside = _write(tmp_path / "secret.txt")
    link = root / "escape.txt"
    os.symlink(outside, link)
    with pytest.raises(paths.LocalFilePathError):
        paths.resolve_authorized_path(_grant(root), link)


@pytest.mark.parametrize(
    "relative",
    [".ssh/id_rsa.txt", "node_modules/pkg/readme.md", "docs/.env", "keys/server.pem"],
)
def test_resolve_rejects_sensitive_paths(tmp_path, relative):
    target = _write(tmp_path / relative)
    with pytest.raises(paths.LocalFilePathError):
        paths.resolve_authorized_path(_grant(tmp_path), target)


def test_resolve_rejects_unsupported_suffix_and_oversize(tmp_path, monkeypatch):
    binary = _write(tmp_path / "app.bin")
    with pytest.raises(paths.LocalFilePathError):
        paths.resolve_authorized_path(_grant(tmp_path), binary)

    monkeypatch.setattr(paths, "MAX_FILE_BYTES", 4)
    big = _write(tmp_path / "big.txt", "0123456789")
    with pytest.raises(paths.LocalFilePathError):
        paths.resolve_authorized_path(_grant(tmp_path), big)


def test_iter_candidate_files_skips_denied_and_unknown_types(tmp_path):
    _write(tmp_path / "good.md", "a")
    _write(tmp_path / "skip.bin", "a")
    _write(tmp_path / ".ssh" / "id_rsa.txt", "a")
    found = [item.relative_path for item in paths.iter_candidate_files(tmp_path)]
    assert found == ["good.md"]


def test_create_list_and_revoke_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "request_purge", lambda *_args: False)
    with tenant_scope(1):
        grant = service.create_grant(owner_id=7, tenant=1, mode="folder", root_path=str(tmp_path))
        assert grant["is_active"] is True
        assert [row["id"] for row in service.list_grants(owner_id=7, tenant=1)] == [grant["id"]]
        assert service.list_grants(owner_id=8, tenant=1) == []

        file_path = _write(tmp_path / "note.txt")
        loaded = service.grant_for_read(owner_id=7, tenant=1, grant_id=grant["id"])
        assert service.assert_readable(loaded, file_path) == file_path.resolve()

        service.revoke_grant(owner_id=7, tenant=1, grant_id=grant["id"])
        with pytest.raises(service.LocalFileAccessError):
            service.grant_for_read(owner_id=7, tenant=1, grant_id=grant["id"])


def test_full_disk_requires_macos_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "detect_full_disk_access", lambda: "denied")
    with tenant_scope(1), pytest.raises(service.LocalFileAccessError) as exc:
        service.create_grant(owner_id=7, tenant=1, mode="full_disk", root_path=str(tmp_path))
    assert exc.value.code == "local_file_full_disk_denied"


def test_indexer_indexes_updates_and_cleans_up(tmp_path, monkeypatch):
    calls: list[tuple] = []

    class FakeService:
        def ingest_document(self, **kwargs):
            calls.append(("ingest", kwargs["document_id"]))
            # 知识库可能改写 document_id；索引必须保存回执里的真实 id 才能删除。
            return {"success": True, "document": {"document_id": "doc_receipt"}}

        def delete_document(self, dataset_id, document_id, **_kwargs):
            calls.append(("delete", document_id))
            return {"success": True}

    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        lambda: FakeService(),
    )

    with tenant_scope(1):
        grant = service.create_grant(owner_id=7, tenant=1, mode="folder", root_path=str(tmp_path))
        doc = _write(tmp_path / "手册.txt", "第一版")
        indexer._sync_grant(grant["id"], 7, 1)
        rows = indexer._existing_document(grant["id"], 7, 1, str(doc.resolve()))
        assert rows is not None and rows.status == "indexed"
        assert rows.document_id == "doc_receipt"
        assert [call[0] for call in calls] == ["ingest"]
        first_digest = rows.sha256

        doc.write_text("第二版", encoding="utf-8")
        indexer._sync_grant(grant["id"], 7, 1)
        rows = indexer._existing_document(grant["id"], 7, 1, str(doc.resolve()))
        assert rows.sha256 != first_digest
        assert [call[0] for call in calls] == ["ingest", "ingest"]

        doc.unlink()
        indexer._sync_grant(grant["id"], 7, 1)
        rows = indexer._existing_document(grant["id"], 7, 1, str(doc.resolve()))
        assert rows.status == "deleted"
        assert calls[-1][0] == "delete"


@pytest.mark.parametrize("receipt", [{"success": False, "message": "写入被拒绝"}, None, "invalid"])
def test_indexer_records_failure_and_retries_same_document(tmp_path, monkeypatch, receipt):
    failed_path = _write(tmp_path / "failed.txt")
    other_path = _write(tmp_path / "other.txt")
    failures = {str(failed_path): receipt}
    calls: list[tuple[str, str]] = []

    class FakeService:
        def ingest_document(self, **kwargs):
            calls.append((kwargs["source"], kwargs["document_id"]))
            if kwargs["source"] in failures:
                return failures[kwargs["source"]]
            return {"success": True, "document": {"document_id": kwargs["document_id"]}}

    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        lambda: FakeService(),
    )
    with tenant_scope(1):
        grant = service.create_grant(owner_id=7, tenant=1, mode="folder", root_path=str(tmp_path))
        indexer._sync_grant(grant["id"], 7, 1)
        failed = indexer._existing_document(grant["id"], 7, 1, str(failed_path))
        other = indexer._existing_document(grant["id"], 7, 1, str(other_path))
        assert failed.status == "error" and failed.attempt_count == 1
        assert failed.last_error == (
            receipt["message"] if isinstance(receipt, dict) else "知识库写入失败"
        )
        assert other.status == "indexed"
        status = service.get_grant(owner_id=7, tenant=1, grant_id=grant["id"])
        assert (status.scan_status, status.error_count, status.indexed_count) == ("ready", 1, 1)

        failures.clear()
        indexer._sync_grant(grant["id"], 7, 1)
        retried = indexer._existing_document(grant["id"], 7, 1, str(failed_path))
        assert retried.status == "indexed" and retried.attempt_count == 0
        assert retried.last_error == ""
        failed_ids = [document_id for source, document_id in calls if source == str(failed_path)]
        assert len(failed_ids) == 2 and failed_ids[0] == failed_ids[1] == retried.document_id
        assert retried.document_id
        assert [source for source, _ in calls].count(str(other_path)) == 1
        status = service.get_grant(owner_id=7, tenant=1, grant_id=grant["id"])
        assert (status.scan_status, status.error_count, status.indexed_count) == ("ready", 0, 1)
        assert status.skipped_count == 1


@pytest.mark.parametrize("error", [RuntimeError("unexpected"), TypeError("unexpected")])
def test_indexer_does_not_classify_programming_error_as_ingest_failure(
    tmp_path, monkeypatch, error
):
    path = _write(tmp_path / "note.txt")

    class FakeService:
        def ingest_document(self, **_kwargs):
            raise error

    monkeypatch.setattr(
        "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
        lambda: FakeService(),
    )
    with tenant_scope(1):
        grant = service.create_grant(owner_id=7, tenant=1, mode="folder", root_path=str(tmp_path))
        with pytest.raises(type(error)) as caught:
            indexer._sync_grant(grant["id"], 7, 1)
        assert caught.value is error
        assert indexer._existing_document(grant["id"], 7, 1, str(path)) is None
