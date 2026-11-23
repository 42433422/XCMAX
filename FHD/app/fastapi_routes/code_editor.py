"""Workspace 代码编辑 API（Brain / 规划工具）。"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from filelock import FileLock, Timeout
from pydantic import BaseModel

from app.db.models.local_file import CodeEditProposal
from app.db.session import get_host_db
from app.domain.ai.tier import assert_p2_elevated_claim_or_raise, resolve_ai_tier
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/code-editor", tags=["code-editor"])

_TEXT_EXT_OK = frozenset(
    {
        ".py",
        ".txt",
        ".md",
        ".vue",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".css",
        ".scss",
        ".html",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
    }
)


def _workspace_root() -> Path:
    raw = (os.environ.get("WORKSPACE_ROOT") or "").strip()
    if not raw:
        raise HTTPException(status_code=500, detail="WORKSPACE_ROOT is not set")
    return Path(raw).resolve()


def _safe_rel_path(rel: str) -> Path:
    s = (rel or "").strip().replace("\\", "/")
    if not s or ".." in Path(s).parts:
        raise HTTPException(status_code=400, detail="invalid path")
    root = _workspace_root()
    root_text = os.path.realpath(os.path.abspath(root))
    target_text = os.path.realpath(os.path.abspath(os.path.join(root_text, s)))
    root_prefix = root_text.rstrip(os.sep) + os.sep
    if target_text != root_text and not target_text.startswith(root_prefix):
        raise HTTPException(status_code=400, detail="path escapes workspace")
    target = Path(target_text)
    try:
        target.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path escapes workspace") from e
    return target


def chat_completion_no_tools(messages: list, **kw: object) -> str:
    """由 LLM 层实现；测试中 mock 此符号。"""
    raise NotImplementedError("chat_completion_no_tools not configured")


def _unified_diff(old: str, new: str, path: str) -> str:
    lines = list(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    return "".join(lines)


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _proposal_scope(user: Any) -> str:
    return json.dumps(
        {
            "user_id": int(user.id),
            "tenant_id": user.tenant_id,
            "workspace_root": str(_workspace_root()),
        },
        sort_keys=True,
    )


def _owned_edit(edit_id: str, user: Any) -> dict[str, Any]:
    with get_host_db() as db:
        row = (
            db.query(CodeEditProposal)
            .filter_by(edit_id=edit_id, user_id=int(user.id))
            .filter(CodeEditProposal.state != "applied")
            .first()
        )
        if row is None or row.scope_json != _proposal_scope(user):
            raise HTTPException(status_code=404, detail="unknown edit_id")
        return {**json.loads(row.payload_json), "state": row.state}


@router.get("/status")
def code_editor_status() -> dict:
    return {
        "success": True,
        "phase": "edit_diff_apply",
        "capabilities": ["analyze_readonly", "apply_p2", "propose_new_file", "draft_p2"],
        "version": 4,
    }


class AnalyzeBody(BaseModel):
    path: str | None = None
    message: str | None = None


@router.post("/analyze")
def code_editor_analyze(body: AnalyzeBody, _user: Any = Depends(get_logged_in_user)) -> dict:
    if not (body.path and str(body.path).strip()):
        return {"success": True, "kind": "noop"}
    rel = str(body.path).strip()
    try:
        path = _safe_rel_path(rel)
    except HTTPException:
        raise
    if not path.is_file():
        return {"success": True, "kind": "noop"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"success": True, "kind": "text_preview", "preview": text}


class EditBody(BaseModel):
    path: str
    new_content: str
    create_if_missing: bool = False


@router.post("/edit")
def code_editor_edit(body: EditBody, user: Any = Depends(get_logged_in_user)) -> dict:
    rel = str(body.path or "").strip()
    path = _safe_rel_path(rel)
    create = bool(body.create_if_missing)
    is_new = False
    old = ""
    if path.is_file():
        old = path.read_text(encoding="utf-8", errors="replace")
    elif path.is_dir():
        raise HTTPException(status_code=404, detail="path is a directory")
    elif create:
        ext = path.suffix.lower()
        if ext not in _TEXT_EXT_OK:
            raise HTTPException(
                status_code=400, detail="extension not allowed for create_if_missing"
            )
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        old = ""
        is_new = True
    else:
        raise HTTPException(status_code=404, detail="file not found")

    new = body.new_content
    edit_id = f"edit_{uuid.uuid4().hex}"
    diff = _unified_diff(old, new, rel)
    payload = {
        "path": str(path),
        "rel": rel,
        "old": old,
        "new": new,
        "unified_diff": diff,
        "is_new_file": is_new,
        "old_sha256": _sha256_text(old),
    }
    with get_host_db() as db:
        db.add(
            CodeEditProposal(
                edit_id=edit_id,
                user_id=int(user.id),
                scope_json=_proposal_scope(user),
                payload_json=json.dumps(payload),
            )
        )
    return {
        "success": True,
        "edit_id": edit_id,
        "unified_diff": diff,
        "is_new_file": is_new,
    }


@router.get("/diff/{edit_id}")
def code_editor_diff(edit_id: str, user: Any = Depends(get_logged_in_user)) -> dict:
    row = _owned_edit(edit_id, user)
    return {"success": True, "unified_diff": row.get("unified_diff") or ""}


@router.post("/apply/{edit_id}")
def code_editor_apply(
    edit_id: str, request: Request, user: Any = Depends(get_logged_in_user)
) -> dict:
    if resolve_ai_tier(request) != "p2":
        raise HTTPException(status_code=403, detail="p2 required")
    assert_p2_elevated_claim_or_raise(request)

    row = _owned_edit(edit_id, user)
    lock_root = Path(get_app_data_dir()) / "code-editor"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Lock the canonical resource, not the proposal or owner: two accounts can
    # have valid proposals for the same file, but only one original version wins.
    lock_key = _sha256_text(os.path.normcase(row["path"]))
    try:
        with FileLock(lock_root / f"{lock_key}.lock", timeout=30, mode=0o600):
            row = _owned_edit(edit_id, user)
            if row["state"] != "pending":
                raise HTTPException(status_code=409, detail="edit outcome requires verification")
            path = _safe_rel_path(row["rel"])
            if str(path) != row["path"]:
                raise HTTPException(status_code=409, detail="file path changed")
            created = bool(row["is_new_file"])
            if created and path.exists():
                raise HTTPException(status_code=409, detail="file already exists")
            if not created:
                if not path.is_file():
                    raise HTTPException(status_code=404, detail="file missing")
                old_disk = path.read_text(encoding="utf-8", errors="replace")
                if _sha256_text(old_disk) != row["old_sha256"]:
                    raise HTTPException(status_code=409, detail="file changed on disk")
            prepared = (
                _staged_edit(path, row["new"], create=created)
                if created or row["new"] != row["old"]
                else nullcontext(None)
            )
            with prepared as staged:
                # Commit before publication. Failed/uncertain writes stay blocked;
                # successful claims remain applied across the original restore flow.
                with get_host_db() as db:
                    claimed = (
                        db.query(CodeEditProposal)
                        .filter_by(
                            edit_id=edit_id,
                            user_id=int(user.id),
                            scope_json=_proposal_scope(user),
                            state="pending",
                        )
                        .update({"state": "applying"}, synchronize_session=False)
                    )
                    if claimed != 1:
                        raise HTTPException(status_code=409, detail="edit already claimed")
                if staged is not None:
                    _publish_edit(path, staged, create=created)
                with get_host_db() as db:
                    consumed = (
                        db.query(CodeEditProposal)
                        .filter_by(
                            edit_id=edit_id,
                            user_id=int(user.id),
                            scope_json=_proposal_scope(user),
                            state="applying",
                        )
                        .update({"state": "applied"}, synchronize_session=False)
                    )
                    if consumed != 1:
                        raise HTTPException(
                            status_code=409, detail="edit outcome requires verification"
                        )
            return {"success": True, "created": created}
    except Timeout as exc:
        raise HTTPException(status_code=409, detail="file is being edited") from exc


@contextmanager
def _staged_edit(path: Path, content: str, *, create: bool) -> Iterator[Path]:
    """Prepare bytes before claiming the edit; failure here cannot change the target."""
    staged = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".code-edit-", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if not create:
            staged.chmod(path.stat().st_mode & 0o777)
        yield staged
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def _publish_edit(path: Path, staged: Path, *, create: bool) -> None:
    """Publish once; every failure after the durable claim remains uncertain."""
    if create:
        # Linking is an atomic no-clobber publication even if another writer creates it.
        try:
            os.link(staged, path)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="file already exists") from exc
    else:
        os.replace(staged, path)
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class DraftBody(BaseModel):
    path: str
    instruction: str


@router.post("/draft")
def code_editor_draft(
    request: Request, body: DraftBody, _user: Any = Depends(get_logged_in_user)
) -> dict:
    if resolve_ai_tier(request) != "p2":
        raise HTTPException(status_code=403, detail="p2 required")
    assert_p2_elevated_claim_or_raise(request)

    rel = str(body.path or "").strip()
    path = _safe_rel_path(rel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    current = path.read_text(encoding="utf-8", errors="replace")
    messages = [
        {"role": "system", "content": "Return only the full new file content."},
        {
            "role": "user",
            "content": f"File {rel}:\n```\n{current}\n```\nInstruction: {body.instruction}",
        },
    ]
    try:
        out = chat_completion_no_tools(messages)
    except RECOVERABLE_ERRORS:
        logger.exception("code editor draft failed")
        return {"success": False, "message": "代码草稿服务暂时不可用", "is_new_file": False}

    if isinstance(out, str) and out.strip().upper().startswith("ERROR:"):
        return {"success": False, "message": out.strip(), "is_new_file": False}

    return {"success": True, "proposed_new_content": out, "is_new_file": False}
