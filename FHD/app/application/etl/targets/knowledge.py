"""Knowledge-base ETL target adapter."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from app.application.etl.errors import EtlError
from app.application.etl.targets.base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.etl.targets.helpers import is_uploaded_document_path, issue
from app.infrastructure.tenant_scope import tenant_id_for_write


class KnowledgeAdapter(TargetAdapter):
    type = "knowledge"
    label = "知识库"
    reversible = True
    actions = ("new", "update", "skip")
    fields = (
        TargetField(
            "document_path",
            "文档路径",
            aliases=("document_path",),
            updatable=True,
        ),
        TargetField("content", "内容", aliases=("内容", "正文"), updatable=True),
        TargetField("source_key", "来源键", aliases=("来源", "来源键")),
    )
    default_match_keys = ("content_hash",)

    def validate(self, data):
        if not data.get("document_path") and not data.get("content"):
            return [issue("ETL_KNOWLEDGE_CONTENT_REQUIRED", "content", "文档或内容不能为空")]
        return []

    @staticmethod
    def _content_hash(data: dict[str, Any], context: dict[str, Any]) -> str:
        content = str(data.get("content") or "")
        if content:
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
        return str(context.get("file_sha256") or "")

    @staticmethod
    def _source_label(data: dict[str, Any], context: dict[str, Any]) -> str:
        return str(data.get("source_key") or context.get("file_name") or "etl-import")

    def _documents(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        cache = context.setdefault("_preview_cache", {})
        cache_key = f"knowledge:{tenant_id_for_write()}"
        if cache_key in cache:
            return cast("list[dict[str, Any]]", cache[cache_key])
        from app.application.dataset_rag_app_service import (
            DATASET_READ_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        tenant_key = str(tenant_id_for_write())
        status = get_dataset_rag_app_service().status(
            dataset_id="office-docking",
            tenant_id=tenant_key,
            access_context=DatasetAccessContext(
                actor_id=str(context.get("owner_user_id") or ""),
                tenant_id=tenant_key,
                permissions=frozenset({DATASET_READ_PERMISSION}),
            ),
        )
        documents = status.get("documents") if isinstance(status, dict) else None
        if (
            not isinstance(status, dict)
            or status.get("success") is not True
            or not isinstance(documents, list)
            or any(not isinstance(document, dict) for document in documents)
        ):
            raise EtlError(
                "ETL_KNOWLEDGE_STATUS_FAILED", "无法确认知识库现状，请重试预演", status_code=503
            )
        cache[cache_key] = documents
        return cast("list[dict[str, Any]]", cache[cache_key])

    def preview(self, db, data, *, allowed_update_fields, context):
        issues = self.validate(data)
        document_path = str(data.get("document_path") or "").strip()
        if document_path and not is_uploaded_document_path(document_path, context):
            issues.append(
                issue(
                    "ETL_DOCUMENT_PATH_FORBIDDEN",
                    "document_path",
                    "知识库文档路径必须指向本次上传文件",
                )
            )
        if issues:
            return PreviewDecision("error", issues=issues, reason="validation_failed")
        content_hash = self._content_hash(data, context)
        source_label = self._source_label(data, context)
        documents = self._documents(context)
        duplicate = next(
            (
                document
                for document in documents
                if str((document.get("metadata") or {}).get("content_hash") or "") == content_hash
            ),
            None,
        )
        if duplicate:
            return PreviewDecision(
                "skip",
                match_ref=str(duplicate.get("document_id") or ""),
                before=json_safe(duplicate),
                after=json_safe(duplicate),
                reason="duplicate_content_hash",
            )
        source_matches = [
            document for document in documents if str(document.get("source") or "") == source_label
        ]
        previous = (
            max(source_matches, key=lambda item: int(item.get("version") or 1))
            if source_matches
            else None
        )
        after = {
            **json_safe(data),
            "content_hash": content_hash,
            "source_key": source_label,
        }
        if previous:
            if {"content", "document_path"} & set(allowed_update_fields):
                return PreviewDecision(
                    "update",
                    match_ref=str(previous.get("document_id") or ""),
                    before=json_safe(previous),
                    after=after,
                    reason="confirmed_source_replacement",
                )
            return PreviewDecision(
                "skip",
                match_ref=str(previous.get("document_id") or ""),
                before=json_safe(previous),
                after=json_safe(previous),
                reason="source_exists_update_not_confirmed",
            )
        return PreviewDecision("new", after=after, reason="content_not_found")

    def execute_row(self, db, data, *, action, match_ref, allowed_update_fields, context):
        from app.application.dataset_rag_app_service import (
            DATASET_WRITE_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        document_path = str(data.get("document_path") or "").strip()
        if document_path and not is_uploaded_document_path(document_path, context):
            raise EtlError(
                "ETL_DOCUMENT_PATH_FORBIDDEN",
                "知识库文档路径必须指向本次上传文件",
            )
        run_id = str(context.get("run_id") or "")
        if not run_id:
            raise EtlError("ETL_EXECUTION_CONTEXT_REQUIRED", "知识库写入缺少运行标识")
        stable = self._content_hash(data, context)
        tenant_key = str(tenant_id_for_write())
        scoped_hash = hashlib.sha256(f"{tenant_key}:{stable}".encode()).hexdigest()
        document_id = f"etl-{scoped_hash}"
        # Preview caches never authorize an execution. A retry may reuse only
        # this run's own receipt; another run's duplicate must be re-previewed.
        fresh_context = {key: value for key, value in context.items() if key != "_preview_cache"}
        decision = self.preview(
            db, data, allowed_update_fields=allowed_update_fields, context=fresh_context
        )
        own_retry = (
            decision.reason == "duplicate_content_hash"
            and str(((decision.before or {}).get("metadata") or {}).get("etl_run_id") or "")
            == run_id
        )
        expected_before = context.get("preview_before")
        if not own_retry and (
            decision.action != action
            or decision.match_ref != match_ref
            or (expected_before is not None and json_safe(decision.before or {}) != expected_before)
        ):
            raise EtlError("ETL_PREVIEW_STALE", "知识库已发生变化，请重新预演", status_code=409)
        source_version = int((decision.before or {}).get("version") or 0)
        source_label = self._source_label(data, context)
        access = DatasetAccessContext(
            actor_id=str(context.get("owner_user_id") or ""),
            tenant_id=tenant_key,
            permissions=frozenset({DATASET_WRITE_PERMISSION}),
        )
        result = get_dataset_rag_app_service().ingest_document(
            dataset_id="office-docking",
            source=source_label,
            text=str(data.get("content") or ""),
            file_path=str(data.get("document_path") or ""),
            document_id=document_id,
            tenant_id=tenant_key,
            metadata={"etl_run_id": run_id, "content_hash": stable},
            idempotency_key=f"etl:{run_id}:{stable}",
            expected_source_version=source_version,
            access_context=access,
        )
        if isinstance(result, dict) and result.get("error_code") in {
            "dataset_document_conflict",
            "dataset_source_version_conflict",
        }:
            raise EtlError("ETL_PREVIEW_STALE", "知识库已发生变化，请重新预演", status_code=409)
        document = result.get("document") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or not isinstance(document, dict)
            or document.get("document_id") != document_id
            or str(document.get("tenant_id") or "") != tenant_key
            or type(document.get("version")) is not int
            or document["version"] < 1
        ):
            raise EtlError("ETL_KNOWLEDGE_INGEST_FAILED", "知识库写入未返回有效回执")
        return {
            "match_ref": document_id,
            "after": {
                "document_id": document_id,
                "content_hash": stable,
                "source_key": source_label,
                "version": document.get("version"),
            },
        }

    def rollback_row(self, db, *, match_ref, before, after, context):
        from app.application.dataset_rag_app_service import (
            DATASET_WRITE_PERMISSION,
            DatasetAccessContext,
            get_dataset_rag_app_service,
        )

        version = after.get("version")
        run_id = str(context.get("run_id") or "")
        content_hash = str(after.get("content_hash") or "")
        if (
            type(version) is not int
            or version < 1
            or not run_id
            or not content_hash
            or after.get("document_id") != match_ref
        ):
            raise EtlError("ETL_KNOWLEDGE_ROLLBACK_RECEIPT_REQUIRED", "缺少可验证的知识库撤销回执")
        result = get_dataset_rag_app_service().delete_document(
            dataset_id="office-docking",
            document_id=match_ref,
            expected_version=version,
            expected_metadata={"etl_run_id": run_id, "content_hash": content_hash},
            access_context=DatasetAccessContext(
                actor_id=str(context.get("owner_user_id") or ""),
                tenant_id=str(tenant_id_for_write()),
                permissions=frozenset({DATASET_WRITE_PERMISSION}),
            ),
        )
        if isinstance(result, dict) and result.get("error_code") == "dataset_document_conflict":
            raise EtlError(
                "ETL_ROLLBACK_CONCURRENT_CHANGE",
                "知识库文档已有后续修改，未执行撤销",
                status_code=409,
            )
        if not isinstance(result, dict) or result.get("success") is not True:
            raise EtlError("ETL_KNOWLEDGE_ROLLBACK_FAILED", "知识库撤销失败")
