"""References to original uploads from the same authenticated chat revision."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, RunContextScope
from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest, validate_runtime_goal

REFERENCE_PREFIX = "conversation-upload:"
EVIDENCE_SOURCE = "conversation_uploads"
_MAX_REFERENCES = 8
_MAX_GROUP = 4

AttachmentViews = dict[str, Any] | list[dict[str, Any]]


@dataclass(frozen=True)
class ConversationUpload:
    origin: str
    name: str
    upload_id: str
    sha256: str

    @property
    def reference(self) -> str:
        return REFERENCE_PREFIX + canonical_digest([self.origin, self.upload_id, self.sha256])[:40]

    def descriptor(self) -> dict[str, str]:
        return {"name": self.name, "upload_id": self.reference, "source_run_id": self.origin}


def conversation_upload_scope(context: dict[str, Any]) -> RunContextScope | None:
    tenant = str(context.get("tenant_id") or "")
    session = context.get("session_id") or context.get("conversation_id")
    revision = context.get("_conversation_revision")
    if (
        not tenant.isdecimal()
        or not isinstance(session, str)
        or not session
        or type(revision) is not int
    ):
        return None
    if context.get("conversation_id") not in (None, "", session) or revision < 0:
        return None
    return RunContextScope(
        tenant, str(context.get("mod_id") or context.get("active_mod_id") or ""), session, revision
    )


def original_conversation_uploads(run: AgentRun) -> list[ConversationUpload]:
    if run.metadata.get("runtime_type") != "xiaox":
        return []
    try:
        digest = validate_runtime_goal(run)
        if digest != run.metadata.get("runtime_goal_digest"):
            return []
        attachments = run.metadata["runtime_goal_contract"]["request"]["attachments"]
    except (KeyError, TypeError, ValueError):
        return []
    entries = []
    for item in attachments[:4] if isinstance(attachments, list) else ():
        if not isinstance(item, dict) or item.get("source") != "owned_elt_upload":
            continue
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        name, upload_id, sha = item.get("name"), metadata.get("upload_id"), metadata.get("sha256")
        if (
            isinstance(name, str)
            and 0 < len(name) <= 255
            and isinstance(upload_id, str)
            and 0 < len(upload_id) <= 80
            and isinstance(sha, str)
            and re.fullmatch(r"[0-9a-f]{64}", sha)
        ):
            entries.append(ConversationUpload(run.run_id, name, upload_id, sha))
    return entries


def conversation_upload_evidence(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("attachments"):
        return {}
    return next(
        (
            item
            for item in request.get("context_evidence") or []
            if item.get("source") == EVIDENCE_SOURCE
        ),
        {},
    )


def recalled_conversation_uploads(request: dict[str, Any]) -> list[dict[str, str]]:
    entries = conversation_upload_evidence(request).get("entries", [])
    if not isinstance(entries, list) or not all(
        isinstance(item, dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in item.items())
        for item in entries
    ):
        return []
    return entries


def conversation_upload_directory(run: AgentRun, context: dict[str, Any]) -> list[dict[str, str]]:
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.db.models.elt import EltUpload
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.time import utc_now_naive

    scope = conversation_upload_scope(context)
    if scope is None or not run.user_id.isdecimal():
        return []
    originals = get_agent_run_repository().list_recent(
        user_id=run.user_id,
        runtime_scope=scope,
        matches=lambda earlier: (
            earlier.created_at < run.created_at
            and bool(
                (earlier.metadata.get("runtime_goal_contract") or {})
                .get("request", {})
                .get("attachments")
            )
        ),
        limit=_MAX_REFERENCES * 2,
    )
    uploads: dict[str, ConversationUpload] = {}
    for earlier in sorted(originals, key=lambda item: (item.created_at, item.run_id), reverse=True):
        for ref in original_conversation_uploads(earlier):
            uploads.setdefault(ref.upload_id, ref)
    if not uploads:
        return []
    with tenant_scope(int(scope.tenant_id)), get_db() as db:
        rows = (
            db.query(EltUpload.id, EltUpload.sha256)
            .filter(
                EltUpload.id.in_(uploads),
                EltUpload.owner_user_id == int(run.user_id),
                EltUpload.tenant_id == int(scope.tenant_id),
                EltUpload.expires_at > utc_now_naive(),
            )
            .all()
        )
    available = dict(rows)
    return [ref.descriptor() for key, ref in uploads.items() if available.get(key) == ref.sha256][
        :_MAX_REFERENCES
    ]


def _scoped_source(run: AgentRun, context: dict[str, Any], origin: str) -> AgentRun:
    from app.application.agent_orchestrator.run_lifecycle import continuation_conversation_error
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    scope = conversation_upload_scope(context)
    if scope is None or not scope.matches(run) or continuation_conversation_error(run, context):
        raise PermissionError("原会话已变化，无法继续读取附件")
    source = get_agent_run_repository().get(origin)
    if (
        source is not None
        and source.user_id == run.user_id
        and scope.matches(source)
        and source.created_at < run.created_at
    ):
        return source
    raise PermissionError("本轮没有该附件引用，请在原会话重新选择附件")


def _scoped_conversation_upload(
    run: AgentRun, context: dict[str, Any], entry: dict[str, str]
) -> ConversationUpload:
    source = _scoped_source(run, context, entry["source_run_id"])
    for upload in original_conversation_uploads(source):
        if upload.reference == entry["upload_id"]:
            return upload
    raise PermissionError("本轮没有该附件引用，请在原会话重新选择附件")


def _preceding_source_matches(run: AgentRun, source: AgentRun, context: dict[str, Any]) -> bool:
    """Match the previous user message in this run's frozen SQL transcript."""
    from app.application.ai_chat.dialogue_memory import conversation_key
    from app.db.models import AIConversation
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_scope

    scope = conversation_upload_scope(context)
    rows, ids = context.get("_chat_history_messages"), context.get("_chat_history_ids")
    if (
        scope is None
        or context.get("_chat_history_source") != "sql"
        or context.get("_chat_history_revision") != scope.revision
        or not isinstance(rows, list)
        or not isinstance(ids, list)
        or len(rows) != len(ids)
    ):
        return False
    prior_user_id = max(
        (
            row_id
            for item, row_id in zip(rows, ids, strict=True)
            if isinstance(item, dict) and item.get("role") == "user" and type(row_id) is int
        ),
        default=0,
    )
    key = conversation_key(context)
    if prior_user_id < 1 or not key:
        return False
    with tenant_scope(int(scope.tenant_id)), get_db() as db:
        row = (
            db.query(AIConversation.conversation_metadata)
            .filter(
                AIConversation.id == prior_user_id,
                AIConversation.session_id == scope.session_id,
                AIConversation.user_id == run.user_id,
                AIConversation.role == "user",
            )
            .first()
        )
    try:
        metadata = json.loads(row[0] or "{}") if row else {}
    except (TypeError, ValueError):
        return False
    if not isinstance(metadata, dict):
        return False
    binding, summary = (metadata.get(key) for key in ("business_harness", "summary"))
    source_turn = (source.metadata.get("runtime_context") or {}).get("turn_id")
    return bool(
        isinstance(binding, dict)
        and isinstance(summary, dict)
        and source_turn
        and source_turn != context.get("turn_id")
        and binding.get("recall_bound") is True
        and binding.get("conversation_key") == key
        and binding.get("conversation_id") == scope.session_id
        and binding.get("run_id") == summary.get("run_id") == source.run_id
        and binding.get("turn_id") == summary.get("turn_id") == source_turn
    )


def conversation_upload_context(
    run: AgentRun, context: dict[str, Any], entries: list[dict[str, str]]
) -> AttachmentViews | None:
    """Read all members of one exact, unambiguous original selection, or none."""
    from app.application.agent_orchestrator.attachment_inputs import (
        AttachmentInputError,
        resolve_attachment_inputs,
    )

    if not 1 <= len(entries) <= _MAX_GROUP:
        return None
    origins = {item["source_run_id"] for item in entries}
    if len(origins) != 1:
        return None
    try:
        source = _scoped_source(run, context, next(iter(origins)))
        uploads = original_conversation_uploads(source)
        if [upload.descriptor() for upload in uploads] != entries:
            return None
        if len(uploads) > 1 and not _preceding_source_matches(run, source, context):
            return None
        artifacts = resolve_attachment_inputs(
            {**context, "attachment_upload_ids": [upload.upload_id for upload in uploads]},
            inline_context=True,
        )
    except (AttachmentInputError, PermissionError):
        return None
    if len(artifacts) != len(uploads) or any(
        artifact["name"] != upload.name
        or artifact["metadata"]["sha256"] != upload.sha256
        or artifact["metadata"]["upload_id"] != upload.upload_id
        for upload, artifact in zip(uploads, artifacts, strict=True)
    ):
        return None
    views = [
        {**upload.descriptor(), "sha256": upload.sha256, **artifact["preview"]}
        for upload, artifact in zip(uploads, artifacts, strict=True)
    ]
    return views if len(views) > 1 else views[0]


def recalled_attachment_view(run: AgentRun, context: dict[str, Any]) -> AttachmentViews | None:
    """Only expose frozen source text while the entire original selection still validates."""
    request = (run.metadata.get("runtime_goal_contract") or {}).get("request") or {}
    evidence = conversation_upload_evidence(request)
    expected = evidence.get("verified_reads", evidence.get("verified_read"))
    if expected is None or validate_runtime_goal(run) != run.metadata.get("runtime_goal_digest"):
        return None
    observed = conversation_upload_context(run, context, evidence["entries"])
    return observed if observed == expected else None


def resolve_conversation_upload(value: str, context: dict[str, Any]) -> ConversationUpload | None:
    if not value.startswith(REFERENCE_PREFIX):
        return None
    from app.infrastructure.xiaox.receipts import action_parent

    parent = action_parent(context)
    if parent is None:
        raise PermissionError("该附件引用只在原会话中可用")
    _, binding, _ = parent
    return bound_conversation_upload(value, binding.run, binding.context)


def bound_conversation_upload(
    value: str, run: AgentRun, context: dict[str, Any]
) -> ConversationUpload:
    """Resolve a frozen parent reference before a child exists, without executing it."""
    if validate_runtime_goal(run) != run.metadata.get("runtime_goal_digest"):
        raise PermissionError("原任务目标绑定已变化")
    request = run.metadata["runtime_goal_contract"]["request"]
    for item in recalled_conversation_uploads(request):
        if item["upload_id"] == value:
            return _scoped_conversation_upload(run, context, item)
    raise PermissionError("本轮没有该附件引用，请在原会话重新选择附件")
