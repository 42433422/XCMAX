"""Deterministic, read-only official-site content change auditor."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    change = dict(payload or {}).get("content_change")
    if not isinstance(change, dict):
        return _failed("content_change object is required", "missing_content_change")
    issues: list[dict[str, str]] = []
    files = change.get("files") if isinstance(change.get("files"), list) else []
    links = change.get("links") if isinstance(change.get("links"), list) else []
    locales = change.get("locales") if isinstance(change.get("locales"), list) else []
    validations = change.get("validations") if isinstance(change.get("validations"), list) else []
    clean_files: list[str] = []
    for index, value in enumerate(files[:200]):
        path = str(value or "").strip()[:500]
        allowed = path.endswith((".html", ".json", ".md", ".png", ".jpg", ".svg"))
        forbidden = any(token in path.lower() for token in ("nginx", "backend/", ".env"))
        if not allowed or forbidden or path.startswith("/") or ".." in path.split("/"):
            issues.append(
                {"code": "file_outside_content_scope", "path": f"content_change.files[{index}]"}
            )
        else:
            clean_files.append(path)
    if not clean_files:
        issues.append({"code": "missing_content_files", "path": "content_change.files"})
    if not locales:
        issues.append({"code": "missing_locales", "path": "content_change.locales"})
    if not validations:
        issues.append({"code": "missing_validations", "path": "content_change.validations"})
    broken = [
        str(item.get("url") or "")
        for item in links
        if isinstance(item, dict) and item.get("status") not in {200, 204}
    ]
    if broken:
        issues.append({"code": "broken_links", "path": "content_change.links"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": f"官网内容变更已只读核对：{len(clean_files)} 个内容文件、{len(links)} 条链接、{len(issues)} 个阻塞项；未修改或发布页面。",
        "files": clean_files,
        "issues": issues,
        "ready_for_edit": not issues,
        "evidence": [
            "input.content_change.files",
            "input.content_change.links",
            "input.content_change.locales",
            "input.content_change.validations",
        ],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
