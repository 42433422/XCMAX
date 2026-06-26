#!/usr/bin/env python3
"""冒烟：Word 全量读取 → JSON 量化报告（模拟考试页整条链路）。"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[1]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


def _simulate_execute_file(
    employee_id: str, payload: bytes, filename: str, user_id: int = 1
) -> dict:
    from modstore_server.employee_api import (
        _collect_llm_context_text,
        _persist_employee_outputs_for_download,
    )
    from modstore_server.services.employee import get_default_employee_client

    session_dir = MODSTORE_ROOT / "var" / "employee_uploads" / str(user_id) / uuid.uuid4().hex
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
            task="考试试跑",
            input_data=input_data,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "result not dict"}
        llm_text = _collect_llm_context_text(session_dir, result)
        downloads = _persist_employee_outputs_for_download(user_id, session_dir, dest, result)
        out = dict(result)
        out["llm_context_text"] = llm_text
        out["output_downloads"] = downloads
        inner = result.get("result") if isinstance(result.get("result"), dict) else {}
        outputs = inner.get("outputs") if isinstance(inner.get("outputs"), list) else []
        dp_ok = any(
            isinstance(o, dict) and o.get("handler") == "direct_python" and o.get("ok") is True
            for o in outputs
        )
        has_doc = any(
            isinstance(d, dict) and "document_full.json" in str(d.get("filename") or "")
            for d in downloads
        )
        has_report_html = any(
            isinstance(d, dict) and "quantitative_report.html" in str(d.get("filename") or "")
            for d in downloads
        )
        if employee_id == "json-report-employee":
            out["ok"] = has_report_html or dp_ok
        else:
            out["ok"] = has_doc or "document_full.json" in (llm_text or "") or dp_ok
        if not out["ok"]:
            err = next(
                (
                    str(o.get("error") or "")
                    for o in outputs
                    if isinstance(o, dict) and o.get("error")
                ),
                "",
            )
            out["error"] = err or "Word 读取未产出 document_full.json"
        return out
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:800]}
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


def _json_bytes_from_word_result(word_res: dict) -> bytes:
    for d in word_res.get("output_downloads") or []:
        if not isinstance(d, dict):
            continue
        fn = str(d.get("filename") or "")
        if "document_full.json" not in fn:
            continue
        job_id = str(d.get("job_id") or "")
        user_id = 1
        from modstore_server.employee_api import _employee_download_jobs_root

        path = _employee_download_jobs_root() / str(user_id) / job_id / Path(fn).name
        if path.is_file():
            return path.read_bytes()
    llm = str(word_res.get("llm_context_text") or "")
    marker = "### outputs/document_full.json\n"
    if marker in llm:
        body = llm.split(marker, 1)[1].split("\n### ", 1)[0].strip()
        return body.encode("utf-8")
    raise RuntimeError("无法从 Word 结果取得 document_full.json")


def main() -> int:
    from modstore_server.word_extract_runtime import minimal_docx_bytes

    word_res = _simulate_execute_file(
        "word-full-read-employee", minimal_docx_bytes(), "exam-sample.docx"
    )
    if not word_res.get("ok"):
        print(
            json.dumps(
                {"ok": False, "stage": "word", "error": word_res.get("error")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    try:
        json_payload = _json_bytes_from_word_result(word_res)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "prepare_json", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    report_res = _simulate_execute_file("json-report-employee", json_payload, "document_full.json")
    downloads = report_res.get("output_downloads") or []
    has_html = any(
        isinstance(d, dict) and "quantitative_report.html" in str(d.get("filename") or "")
        for d in downloads
    )
    inner = report_res.get("result") if isinstance(report_res.get("result"), dict) else {}
    outputs = inner.get("outputs") if isinstance(inner.get("outputs"), list) else []
    report_dp_ok = any(
        isinstance(o, dict) and o.get("handler") == "direct_python" and o.get("ok") is True
        for o in outputs
    )
    ok = has_html and (report_dp_ok or bool(report_res.get("ok")))
    print(
        json.dumps(
            {
                "ok": ok,
                "word_downloads": len(word_res.get("output_downloads") or []),
                "report_downloads": len(downloads),
                "has_quantitative_report_html": has_html,
                "error": report_res.get("error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
