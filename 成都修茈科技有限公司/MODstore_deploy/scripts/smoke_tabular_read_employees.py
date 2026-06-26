#!/usr/bin/env python3
"""冒烟：4 个「全量读取」员工包 — 模拟 execute-file 全流程（解析 + llm_context + 下载元数据）。"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[1]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

READ_PACKS = (
    ("excel-full-read-employee", "sample.xlsx", "xlsx"),
    ("csv-full-read-employee", "sample.csv", "csv"),
    ("pdf-full-read-employee", "sample.pdf", "pdf"),
    ("word-full-read-employee", "sample.docx", "docx"),
)


def _fixture_bytes(kind: str) -> bytes:
    if kind == "xlsx":
        from modstore_server.excel_tabular_runtime import minimal_xlsx_fixture_bytes

        return minimal_xlsx_fixture_bytes()
    if kind == "csv":
        return "name,score\nalice,90\nbob,85\n".encode("utf-8")
    if kind == "pdf":
        from modstore_server.pdf_extract_runtime import minimal_pdf_fixture_bytes

        return minimal_pdf_fixture_bytes()
    if kind == "docx":
        from modstore_server.word_extract_runtime import minimal_docx_bytes

        return minimal_docx_bytes()
    raise ValueError(kind)


def _simulate_execute_file(
    employee_id: str, payload: bytes, filename: str, user_id: int = 1
) -> dict:
    from modstore_server.employee_api import (
        _collect_llm_context_text,
        _persist_employee_outputs_for_download,
    )
    from modstore_server.services.employee import get_default_employee_client

    repo_root = MODSTORE_ROOT
    session_dir = repo_root / "var" / "employee_uploads" / str(user_id) / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / filename
    dest.write_bytes(payload)
    input_data = {
        "action": "convert",
        "file_path": str(dest.resolve()),
        "workspace_root": str(session_dir.resolve()),
        "original_filename": filename,
    }
    try:
        result = get_default_employee_client().execute_task(
            employee_id=employee_id,
            task="全量读取",
            input_data=input_data,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "result not dict", "raw": str(result)[:500]}
        llm_text = _collect_llm_context_text(session_dir, result)
        downloads = _persist_employee_outputs_for_download(user_id, session_dir, dest, result)
        out = dict(result)
        out["llm_context_chars"] = len(llm_text or "")
        out["llm_context_preview"] = (llm_text or "")[:400]
        out["output_downloads"] = downloads
        inner = result.get("result") if isinstance(result.get("result"), dict) else {}
        outputs = inner.get("outputs") if isinstance(inner.get("outputs"), list) else []
        dp_ok = any(
            isinstance(o, dict) and o.get("handler") == "direct_python" and o.get("ok") is True
            for o in outputs
        )
        has_real_context = bool(llm_text.strip()) and "### outputs/" in llm_text
        out["ok"] = dp_ok and (has_real_context or bool(downloads))
        out["direct_python_ok"] = dp_ok
        if not out["ok"]:
            err = next(
                (
                    str(o.get("error") or "")
                    for o in outputs
                    if isinstance(o, dict) and o.get("error")
                ),
                "",
            )
            out["error"] = err or "direct_python 未成功或未写出 outputs 文件"
        return out
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:800]}
    finally:
        import shutil

        shutil.rmtree(session_dir, ignore_errors=True)


def main() -> int:
    rows = []
    all_ok = True
    for pack_id, fname, kind in READ_PACKS:
        try:
            payload = _fixture_bytes(kind)
        except Exception as exc:
            rows.append({"pack_id": pack_id, "ok": False, "stage": "fixture", "error": str(exc)})
            all_ok = False
            continue
        res = _simulate_execute_file(pack_id, payload, fname)
        row = {
            "pack_id": pack_id,
            "ok": bool(res.get("ok")),
            "llm_context_chars": res.get("llm_context_chars", 0),
            "downloads": len(res.get("output_downloads") or []),
            "error": res.get("error"),
            "preview": res.get("llm_context_preview"),
        }
        if not row["ok"]:
            all_ok = False
            err_outputs = res.get("outputs") if isinstance(res, dict) else None
            if err_outputs:
                row["outputs_tail"] = json.dumps(err_outputs, ensure_ascii=False)[:600]
        rows.append(row)

    print(json.dumps({"ok": all_ok, "rows": rows}, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
