"""Fresh results and path resolution for host-bundled file employees."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileEmployeeSupport:
    def __init__(self, module_file, rule_spec):
        self.module_file = module_file
        self.rule_spec = rule_spec

    def _ok(
        self,
        data: Any,
        *,
        warnings: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "summary": self._summary(data),
            "items": data if isinstance(data, list) else [data],
            "warnings": list(warnings or []),
            "error": "",
            "meta": dict(meta or {}),
        }

    def _err(
        self,
        msg: str,
        *,
        warnings: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": False,
            "summary": msg[:400],
            "items": [],
            "warnings": list(warnings or []),
            "error": msg[:1000],
            "meta": dict(meta or {}),
        }

    def _summary(self, data: Any) -> str:
        if isinstance(data, str):
            return data[:4000]
        try:
            return json.dumps(data, ensure_ascii=False)[:4000]
        except TypeError:
            return str(data)[:4000]

    def _pack_root(self) -> Path:
        return Path(self.module_file).resolve().parents[1]

    def _workspace_root(self, ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
        raw = payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()
        return Path(str(raw)).expanduser()

    def _resolve_input(self, payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
        raw = str(
            payload.get("file_path") or payload.get("path") or payload.get("excel_path") or ""
        ).strip()
        if not raw:
            raise FileNotFoundError("缺少 file_path：请上传或指定要处理的文件。")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = self._workspace_root(ctx, payload) / raw
        if not p.is_file():
            raise FileNotFoundError(f"文件不存在：{p}")
        return p

    def _resolve_output(self, payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
        rel = str(
            payload.get("output_relpath")
            or self.rule_spec.get("default_output_relpath")
            or "outputs/employee_output.xlsx"
        ).strip()
        p = Path(rel).expanduser()
        if not p.is_absolute():
            p = self._workspace_root(ctx, payload) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _resolve_template(self, payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:
        raw = str(
            payload.get("template_relpath")
            or self.rule_spec.get("default_template_relpath")
            or self.rule_spec.get("template_relpath")
            or ""
        ).strip()
        if not raw:
            return None
        candidates = []
        p = Path(raw).expanduser()
        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.append(self._workspace_root(ctx, payload) / raw)
            candidates.append(self._pack_root() / raw)
            candidates.append(self._pack_root() / "backend" / "templates" / raw)
            if raw.startswith("backend/"):
                candidates.append(self._pack_root() / raw[len("backend/") :])
        for cand in candidates:
            if cand.is_file():
                return cand
        bundled_templates = (
            sorted((self._pack_root() / "templates").rglob("*.xls*"))
            if (self._pack_root() / "templates").is_dir()
            else []
        )
        if bundled_templates:
            return bundled_templates[0]
        return None
