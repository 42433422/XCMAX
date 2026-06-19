"""文档同步 Action Handler：doc-knowledge-curator 专属的文档读写与同步处理器。

安全约束：
- 写入前必须通过 scope_globs 白名单校验
- 写入前必须通过 forbidden_globs 黑名单校验
- 禁止写入 .py/.vue/.ts/nginx-*.conf/_local_secrets/**
- 所有写入操作记录审计日志
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

from modstore_server.tools.doc_consistency_checker import run_full_consistency_check
from modstore_server.tools.markdown_lint import lint_file

logger = logging.getLogger(__name__)

DOC_SYNC_EMPLOYEE_IDS = frozenset({"doc-knowledge-curator"})

_DEFAULT_SCOPE_GLOBS = [
    "README.md",
    "ESkill.md",
    "docs/**",
    "*.md",
    "yuangon/**/README.md",
]

_DEFAULT_FORBIDDEN_GLOBS = [
    "*.py",
    "*.vue",
    "*.ts",
    "nginx-*.conf",
    "_local_secrets/**",
]


def _repo_root() -> Path:
    env = os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    p = Path(__file__).resolve()
    for depth in (4, 3, 5):
        if depth <= len(p.parents):
            cand = p.parents[depth - 1]
            if (cand / "MODstore_deploy" / "modstore_server").is_dir():
                return cand
    return p.parents[3]


def _match_glob(filepath: str, patterns: Sequence[str]) -> bool:
    name = Path(filepath).name
    parts = filepath.replace("\\", "/")
    for pattern in patterns:
        p = pattern.strip()
        if not p:
            continue
        if p.startswith(("./", "/")):
            anchored = p[2:] if p.startswith("./") else p[1:]
            if fnmatch.fnmatch(parts, anchored):
                return True
            continue
        if "/" in p:
            if fnmatch.fnmatch(parts, p):
                return True
            if fnmatch.fnmatch(parts, f"**/{p}"):
                return True
        else:
            if fnmatch.fnmatch(name, p):
                return True
            if fnmatch.fnmatch(parts, f"**/{p}"):
                return True
    return False


def validate_scope(
    filepath: str, scope_globs: Sequence[str], forbidden_globs: Sequence[str]
) -> tuple[bool, str]:
    if _match_glob(filepath, forbidden_globs):
        return False, f"文件 '{filepath}' 匹配禁止模式，禁止写入"
    if not _match_glob(filepath, scope_globs):
        return False, f"文件 '{filepath}' 不在允许范围 (scope_globs) 内"
    resolved = Path(filepath).resolve()
    try:
        root = _repo_root().resolve()
        resolved.relative_to(root)
    except ValueError:
        return False, f"文件路径 '{filepath}' 超出仓库根目录"
    return True, ""


def read_doc(filepath: str) -> Dict[str, Any]:
    try:
        p = Path(filepath)
        if not p.is_file():
            return {"ok": False, "error": f"文件不存在: {filepath}"}
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "content": content, "size": len(content)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def write_doc(
    filepath: str, content: str, *, scope_globs: Sequence[str], forbidden_globs: Sequence[str]
) -> Dict[str, Any]:
    ok, msg = validate_scope(filepath, scope_globs, forbidden_globs)
    if not ok:
        return {"ok": False, "error": msg}

    try:
        p = Path(filepath)
        original = ""
        if p.is_file():
            original = p.read_text(encoding="utf-8", errors="replace")

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")

        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{filepath}",
                tofile=f"b/{filepath}",
            )
        )
        diff_summary = "".join(diff_lines[:200])

        lint_result = lint_file(filepath, mode="auto")

        return {
            "ok": True,
            "filepath": filepath,
            "size_written": len(content.encode("utf-8")),
            "diff_summary": diff_summary,
            "markdown_lint_errors": lint_result.error_count,
            "markdown_lint_result": lint_result.to_dict(),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def generate_diff(original: str, updated: str, filepath: str = "") -> str:
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        )
    )
    return "".join(diff_lines)


def detect_changes(signals: Dict[str, Any], repo_root: Path) -> List[str]:
    affected: List[str] = []
    changed_files = signals.get("changed_files") or []
    source = signals.get("source_employee") or ""

    for cf in changed_files:
        cf_str = str(cf).replace("\\", "/")
        if cf_str.endswith((".md",)):
            affected.append(cf_str)
        elif cf_str.endswith(("employee.yaml",)):
            emp_dir = Path(cf_str).parent
            readme = str(emp_dir / "README.md").replace("\\", "/")
            if (repo_root / readme).is_file():
                affected.append(readme)
        elif cf_str == "ESkill.md":
            affected.append(cf_str)

    if source == "mods-and-eskill-curator":
        eskill_path = repo_root / "ESkill.md"
        if eskill_path.is_file() and "ESkill.md" not in affected:
            affected.append("ESkill.md")

    if source == "vibe-coding-maintainer":
        docs_api = repo_root / "docs"
        if docs_api.is_dir():
            for f in docs_api.rglob("*.md"):
                rel = str(f.relative_to(repo_root)).replace("\\", "/")
                if rel not in affected:
                    affected.append(rel)

    return list(dict.fromkeys(affected))


@dataclass
class DocSyncResult:
    status: str = "ok"
    changed_docs: List[str] = field(default_factory=list)
    markdown_lint_errors: int = 0
    diff_summary: str = ""
    consistency_check: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "changed_docs": self.changed_docs,
            "markdown_lint_errors": self.markdown_lint_errors,
            "diff_summary": self.diff_summary[:4000],
            "consistency_check": self.consistency_check,
            "errors": self.errors,
        }


def dispatch_doc_sync_handler(
    actions_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
) -> Dict[str, Any]:
    if employee_id not in DOC_SYNC_EMPLOYEE_IDS:
        return {
            "handler": "doc_sync",
            "ok": False,
            "error": f"doc_sync handler not allowed for employee '{employee_id}'",
        }

    cfg = actions_cfg.get("doc_sync") if isinstance(actions_cfg.get("doc_sync"), dict) else {}
    root = _repo_root()

    scope_globs = cfg.get("scope_globs") or _DEFAULT_SCOPE_GLOBS
    forbidden_globs = cfg.get("forbidden_globs") or _DEFAULT_FORBIDDEN_GLOBS

    if cfg.get("scope_globs_ref"):
        try:
            import yaml

            yaml_path = (
                root / "yuangon" / "quality-and-docs" / "doc-knowledge-curator" / "employee.yaml"
            )
            if yaml_path.is_file():
                yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(yaml_data, dict):
                    scope_globs = yaml_data.get("scope_globs") or scope_globs
                    forbidden_globs = yaml_data.get("forbidden_globs") or forbidden_globs
        except Exception:
            pass

    result = DocSyncResult()
    reasoning_text = str(reasoning.get("reasoning") or "")

    try:
        reasoning_data = json.loads(reasoning_text)
    except (json.JSONDecodeError, TypeError):
        reasoning_data = {}

    if not isinstance(reasoning_data, dict):
        reasoning_data = {}

    doc_operations = reasoning_data.get("doc_operations") or []
    change_signals = reasoning_data.get("change_signals") or reasoning_data.get("incident") or {}

    if change_signals:
        affected = detect_changes(change_signals, root)
        result.changed_docs = affected

    for op in doc_operations:
        if not isinstance(op, dict):
            continue
        op_type = str(op.get("type") or "").strip().lower()
        filepath = str(op.get("filepath") or "").strip()

        if not filepath:
            result.errors.append("doc_operation missing filepath")
            continue

        full_path = str(root / filepath) if not Path(filepath).is_absolute() else filepath

        if op_type == "read":
            read_result = read_doc(full_path)
            if not read_result.get("ok"):
                result.errors.append(f"read failed: {read_result.get('error')}")
        elif op_type == "write":
            content = str(op.get("content") or "")
            write_result = write_doc(
                full_path, content, scope_globs=scope_globs, forbidden_globs=forbidden_globs
            )
            if write_result.get("ok"):
                result.changed_docs.append(filepath)
                result.markdown_lint_errors += write_result.get("markdown_lint_errors", 0)
                result.diff_summary += write_result.get("diff_summary", "")
            else:
                result.errors.append(f"write failed: {write_result.get('error')}")
        elif op_type == "lint":
            lint_result = lint_file(full_path, mode="auto")
            result.markdown_lint_errors += lint_result.error_count
        else:
            result.errors.append(f"unknown doc_operation type: {op_type}")

    if cfg.get("consistency_check"):
        try:
            consistency = run_full_consistency_check(root)
            result.consistency_check = consistency
            if consistency.get("total_errors", 0) > 0:
                result.status = "has_errors"
        except Exception as exc:
            result.errors.append(f"consistency check failed: {exc}")

    if result.markdown_lint_errors > 0:
        result.status = "has_errors" if result.status == "ok" else result.status

    if not doc_operations and not change_signals:
        result.status = "ok"
        result.diff_summary = "No doc operations or change signals provided; sync skipped."

    _write_doc_sync_audit(
        employee_id=employee_id,
        user_id=user_id,
        task=task,
        result=result,
    )

    return {
        "handler": "doc_sync",
        "ok": result.status == "ok",
        **result.to_dict(),
    }


def _write_doc_sync_audit(
    *,
    employee_id: str,
    user_id: int,
    task: str,
    result: DocSyncResult,
) -> None:
    try:
        from modstore_server.models import OpsActionAuditLog, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = OpsActionAuditLog(
                user_id=int(user_id) if user_id else None,
                employee_id=employee_id,
                handler="doc_sync",
                command_id="doc_sync",
                args_json=json.dumps({"task": task[:500]}, ensure_ascii=False),
                host_id="local",
                exit_code=0 if result.status == "ok" else 1,
                stdout_excerpt=json.dumps(result.to_dict(), ensure_ascii=False)[:12000],
                stderr_excerpt="",
                duration_ms=0.0,
                approval_required=False,
                dry_run=False,
                error="; ".join(result.errors[:5]) if result.errors else "",
            )
            session.add(row)
            session.commit()
    except Exception as exc:
        logger.exception("doc_sync audit write failed: %s", exc)
