from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests


BASE_URL = (os.environ.get("SMOKE_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.environ.get("SMOKE_USERNAME") or "admin"
PASSWORD = os.environ.get("SMOKE_PASSWORD") or "admin123"
SMOKE_CASE = (os.environ.get("SMOKE_EMPLOYEE_CASE") or "attendance").strip().lower()

ATTENDANCE_BRIEF = """我要创建一个和现有「太阳鸟考勤员」一模一样的员工包。

员工包基础信息：
- 员工包 ID：taiyangniao-attendance-employee
- 员工名称：太阳鸟考勤员
- 版本：1.0.0
- 类型：employee_pack
- 运行方式：direct_python
- 禁止使用 echo
- 禁止 LLM 编造转换结果
- 用户上传 Excel 后必须真实执行 Python 转换

必须生成完整可打包的 employee_pack，backend/vendor/taiyangniao_attendance 内置完整转换模块。
manifest.json 的 employee_config_v2.actions.handlers 必须只有 ["direct_python"]。
"""

WORD_READ_BRIEF = """员工包 ID：word-full-read-employee
员工名称：Word全量读取员工

全量提取 Word 文档所有格式和信息。

目标：自动解析用户上传的 Word（.docx）文档，提取全部可识别内容，包括但不限于：
- 正文段落与 run 级样式（粗体/斜体等）
- 表格结构与单元格文本
- 内嵌图片（导出到 outputs/images/）
- 页眉页脚
- 文档元数据（作者、标题、创建/修改时间等）
- 批注（如有）

输出：
1. outputs/document_full.json — 结构化全量数据
2. outputs/document_full.txt — 纯文本汇总

员工必须使用 direct_python 真实解析，禁止 LLM 编造文档内容。
handlers 必须为 ["direct_python"]，backend/vendor 须含 convert_file 实现。"""

WORD_GEN_BRIEF = """员工包 ID：word-generate-employee
员工名称：Word生成员工

根据 document_full.json 生成 Word 文档，可选 template.docx 模板。
输出 generated_document.docx。handlers 含 direct_python。"""

TERMINAL = {"done", "skipped", "error"}


def _assert_employee_session(final: dict) -> list[str]:
    errs: list[str] = []
    steps = final.get("steps") or []
    if len(steps) < 14:
        errs.append(f"expected >=14 steps, got {len(steps)}")
    step_ids = [str(s.get("id") or "") for s in steps]
    if "six_dim_gate" not in step_ids:
        errs.append("missing step six_dim_gate")
    non_terminal = [s for s in steps if str(s.get("status") or "") not in TERMINAL]
    if non_terminal:
        errs.append(f"non-terminal steps: {[s.get('id') for s in non_terminal]}")
    art = final.get("artifact") or {}
    qr = art.get("quality_report")
    if not qr:
        errs.append("missing artifact.quality_report")
    elif isinstance(qr, dict) and not qr.get("items"):
        errs.append("quality_report.items empty")
    six = art.get("six_dimension_report")
    if not six or not isinstance(six, dict):
        errs.append("missing artifact.six_dimension_report")
    elif not (six.get("dimensions") or {}):
        errs.append("six_dimension_report.dimensions empty")
    if final.get("status") != "done":
        errs.append(f"status={final.get('status')}")
    if isinstance(qr, dict):
        if qr.get("critical_failed"):
            errs.append("quality_report.critical_failed=true")
        if qr.get("runnable") is False:
            errs.append("quality_report.runnable=false")
        if SMOKE_CASE == "word" and qr.get("pipeline_label") and qr.get("pipeline_label") != "word_full_extract":
            errs.append(f"unexpected pipeline_label={qr.get('pipeline_label')}")
        if SMOKE_CASE == "word_gen" and qr.get("pipeline_label") and qr.get("pipeline_label") != "word_generate":
            errs.append(f"unexpected pipeline_label={qr.get('pipeline_label')}")
    return errs


def main() -> int:
    if SMOKE_CASE == "word":
        brief = WORD_READ_BRIEF
        metadata = {
            "intent": "employee",
            "brief": brief,
            "description": brief,
            "employee_target": "pack_plus_workflow",
            "embed_script_workflow": True,
            "provider": os.environ.get("SMOKE_LLM_PROVIDER") or "deepseek",
            "model": os.environ.get("SMOKE_LLM_MODEL") or "deepseek-chat",
            "replace": True,
        }
        files = None
    elif SMOKE_CASE == "word_gen":
        from modstore_server.word_generate_runtime import minimal_document_full_json
        from modstore_server.word_extract_runtime import minimal_docx_bytes

        brief = WORD_GEN_BRIEF
        metadata = {
            "intent": "employee",
            "brief": brief,
            "description": brief,
            "employee_target": "pack_only",
            "provider": os.environ.get("SMOKE_LLM_PROVIDER") or "deepseek",
            "model": os.environ.get("SMOKE_LLM_MODEL") or "deepseek-chat",
            "replace": True,
        }
        import io
        import tempfile

        jf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        jf.write(json.dumps(minimal_document_full_json(), ensure_ascii=False).encode("utf-8"))
        jf.close()
        tf = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tf.write(minimal_docx_bytes())
        tf.close()
        files = (Path(jf.name), Path(tf.name))
    else:
        brief = ATTENDANCE_BRIEF
        src = Path(r"e:\FHD\424\钉钉导出来的考勤数据.xlsx")
        template = Path(r"e:\FHD\424\考勤-2026-3月份考勤统计表.xlsx")
        missing = [str(p) for p in (src, template) if not p.is_file()]
        if missing:
            print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
            return 2
        metadata = {
            "intent": "employee",
            "brief": brief,
            "description": brief,
            "employee_target": "pack_only",
            "provider": os.environ.get("SMOKE_LLM_PROVIDER") or "deepseek",
            "model": os.environ.get("SMOKE_LLM_MODEL") or "deepseek-chat",
            "replace": True,
        }
        files = (template, src)

    sess = requests.Session()
    login = sess.post(f"{BASE_URL}/api/auth/login", json={"username": USERNAME, "password": PASSWORD}, timeout=30)
    if login.status_code >= 400:
        print(json.dumps({"ok": False, "stage": "login", "status": login.status_code, "text": login.text[:1000]}, ensure_ascii=False))
        return 2
    token = login.json().get("access_token")
    sess.headers.update({"Authorization": f"Bearer {token}"})

    if files:
        if SMOKE_CASE == "word_gen":
            json_path, tpl_path = files
            with json_path.open("rb") as jf, tpl_path.open("rb") as tf:
                res = sess.post(
                    f"{BASE_URL}/api/workbench/sessions",
                    data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                    files=[
                        ("files", (json_path.name, jf, "application/json")),
                        ("files", (tpl_path.name, tf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                    ],
                    timeout=60,
                )
        else:
            template, src = files
            with template.open("rb") as tf, src.open("rb") as sf:
                res = sess.post(
                    f"{BASE_URL}/api/workbench/sessions",
                    data={"metadata": json.dumps(metadata, ensure_ascii=False)},
                    files=[
                        ("files", (template.name, tf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                        ("files", (src.name, sf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                    ],
                    timeout=60,
                )
    else:
        res = sess.post(
            f"{BASE_URL}/api/workbench/sessions",
            json=metadata,
            timeout=60,
        )
    if res.status_code >= 400:
        print(json.dumps({"ok": False, "stage": "start", "status": res.status_code, "text": res.text[:2000]}, ensure_ascii=False))
        return 1
    sid = res.json().get("session_id")
    final = None
    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        poll = sess.get(f"{BASE_URL}/api/workbench/sessions/{sid}", timeout=30)
        if poll.status_code >= 400:
            print(json.dumps({"ok": False, "stage": "poll", "status": poll.status_code, "text": poll.text[:1000]}, ensure_ascii=False))
            return 1
        final = poll.json()
        if final.get("status") in {"done", "error"}:
            break
        time.sleep(2)
    ok = bool(final and final.get("status") == "done")
    validation_errors = _assert_employee_session(final) if final else ["no final session"]
    if validation_errors:
        ok = False
    sys.stdout.buffer.write(
        (
            json.dumps(
                {
                    "ok": ok,
                    "case": SMOKE_CASE,
                    "session_id": sid,
                    "validation_errors": validation_errors,
                    "final": final,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            + "\n"
        ).encode("utf-8")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
