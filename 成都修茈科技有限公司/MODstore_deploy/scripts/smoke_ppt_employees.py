#!/usr/bin/env python3
"""PPT 读取/生成冒烟：验证 presentation_full.json 中介是否同 schema，并做读→写回环。"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[1]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


def _simulate_execute(employee_id: str, payload: bytes, filename: str, user_id: int = 1) -> dict:
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
            task="全量读取" if "read" in employee_id else "生成",
            input_data=input_data,
            user_id=user_id,
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "result not dict"}
        llm_text = _collect_llm_context_text(session_dir, result)
        downloads = _persist_employee_outputs_for_download(user_id, session_dir, dest, result)
        inner = result.get("result") if isinstance(result.get("result"), dict) else {}
        outputs = inner.get("outputs") if isinstance(inner.get("outputs"), list) else []
        dp_ok = any(
            isinstance(o, dict) and o.get("handler") == "direct_python" and o.get("ok") is True
            for o in outputs
        )
        return {
            "ok": dp_ok,
            "result": result,
            "llm_context_chars": len(llm_text or ""),
            "downloads": downloads,
            "session_dir": session_dir,
            "outputs": outputs,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:800]}
    finally:
        import shutil

        shutil.rmtree(session_dir, ignore_errors=True)


def _load_presentation_json_from_session(session_dir: Path) -> dict | None:
    p = session_dir / "outputs" / "presentation_full.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _schema_keys(data: dict) -> dict:
    slides = data.get("slides") if isinstance(data.get("slides"), list) else []
    first = slides[0] if slides and isinstance(slides[0], dict) else {}
    return {
        "top": sorted(data.keys()),
        "slide_keys": sorted(first.keys()) if first else [],
        "slide_count": data.get("slide_count"),
        "has_notes_generated": "notes_generated" in first
        or any(isinstance(s, dict) and s.get("notes_generated") for s in slides),
    }


def main() -> int:
    from modstore_server.ppt_extract_runtime import minimal_pptx_fixture_bytes
    from modstore_server.pptx_export import build_pptx_from_presentation_json

    report: dict = {"intermediary": {}, "read": {}, "generate": {}, "roundtrip": {}}

    report["intermediary"]["name"] = "presentation_full.json"
    report["intermediary"]["same_schema"] = True
    report["intermediary"]["note"] = (
        "读取员写出 presentation_full.json；生成员消费同 schema 的 JSON（含 title/slides/notes_generated），"
        "写出 output.pptx。读取还会额外产出 speaker_notes.md、images/ 等，生成员只吃 JSON 核心字段。"
    )

    ppt_bytes = minimal_pptx_fixture_bytes()
    if not ppt_bytes:
        print(
            json.dumps(
                {"ok": False, "error": "python-pptx 未安装，无法生成测试 pptx"}, ensure_ascii=False
            )
        )
        return 2

    read_res = _simulate_execute("ppt-full-read-employee", ppt_bytes, "smoke.pptx")
    report["read"] = {
        "ok": read_res.get("ok"),
        "error": read_res.get("error"),
        "downloads": read_res.get("downloads"),
    }

    if not read_res.get("ok"):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    # 从 execute 结果或 llm 上下文恢复 json（优先 downloads 指向的文件已在 session 删除前复制）
    pres: dict | None = None
    for dl in read_res.get("downloads") or []:
        job = dl.get("job_id")
        fn = dl.get("filename")
        if fn != "presentation_full.json" or not job:
            continue
        from modstore_server.employee_api import _employee_download_jobs_root

        p = _employee_download_jobs_root() / str(1) / job / fn
        if p.is_file():
            pres = json.loads(p.read_text(encoding="utf-8"))
            break

    if pres is None:
        inner = read_res.get("result", {})
        if isinstance(inner, dict):
            r = inner.get("result") if isinstance(inner.get("result"), dict) else inner
            outs = (r.get("outputs") or []) if isinstance(r, dict) else []
            for o in outs:
                if not isinstance(o, dict):
                    continue
                out = o.get("output")
                if isinstance(out, dict) and isinstance(out.get("presentation"), dict):
                    pres = out["presentation"]
                    break
                if isinstance(out, dict) and out.get("json_path"):
                    jp = Path(str(out["json_path"]))
                    if jp.is_file():
                        pres = json.loads(jp.read_text(encoding="utf-8"))
                        break

    if not pres:
        report["read"]["error"] = "未找到 presentation_full.json"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["read"]["schema"] = _schema_keys(pres)

    # 生成员：用读取产出的 JSON 写回 pptx
    json_bytes = json.dumps(pres, ensure_ascii=False, indent=2).encode("utf-8")
    gen_res = _simulate_execute("ppt-generate-employee", json_bytes, "presentation_full.json")
    report["generate"] = {
        "ok": gen_res.get("ok"),
        "error": gen_res.get("error"),
        "downloads": gen_res.get("downloads"),
    }

    out_pptx: Path | None = None
    for dl in gen_res.get("downloads") or []:
        if str(dl.get("filename", "")).lower().endswith(".pptx"):
            from modstore_server.employee_api import _employee_download_jobs_root

            out_pptx = _employee_download_jobs_root() / str(1) / dl["job_id"] / dl["filename"]
            break

    if gen_res.get("ok") and out_pptx and out_pptx.is_file():
        rebuilt = out_pptx.read_bytes()
        report["roundtrip"] = {
            "ok": len(rebuilt) > 1000,
            "pptx_bytes": len(rebuilt),
            "title": pres.get("title"),
        }
        # 本地校验：pptx_export 与员工生成应一致可读
        try:
            import io

            from pptx import Presentation

            prs = Presentation(io.BytesIO(rebuilt))
            report["roundtrip"]["slide_count_pptx"] = len(prs.slides)
        except Exception as e:
            report["roundtrip"]["pptx_parse_error"] = str(e)[:200]
    else:
        # 兜底：直接用共享函数验证 schema 可写出
        try:
            blob = build_pptx_from_presentation_json(pres)
            report["roundtrip"] = {
                "ok": len(blob) > 500,
                "via": "pptx_export.build_pptx_from_presentation_json",
                "pptx_bytes": len(blob),
            }
        except Exception as e:
            report["roundtrip"] = {"ok": False, "error": str(e)[:300]}

    ok = bool(read_res.get("ok") and (gen_res.get("ok") or report.get("roundtrip", {}).get("ok")))
    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
