#!/usr/bin/env python3
"""Lab run: 做员工流程复刻 Word 全量读取（训练 LLM 写码），不覆盖正式包。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_URL = (os.environ.get("SMOKE_BASE_URL") or "http://127.0.0.1:8765").rstrip("/")
USERNAME = os.environ.get("SMOKE_USERNAME") or "admin"
PASSWORD = os.environ.get("SMOKE_PASSWORD") or "admin123"
PROVIDER = os.environ.get("SMOKE_LLM_PROVIDER") or "xiaomi"
MODEL = os.environ.get("SMOKE_LLM_MODEL") or "mimo-v2.5-pro"
PACK_ID = os.environ.get("LAB_PACK_ID") or "word-full-read-employee-llm-lab"
OUT_JSON = Path(
    os.environ.get("LAB_RESULT_JSON") or ROOT / "artifacts" / "word_read_employee_lab_result.json"
)

BRIEF = f"""员工包 ID：{PACK_ID}
员工名称：Word全量读取员工（LLM 实验包）
版本：0.1.0-lab

参考平台已有 word-full-read-employee，制作一个功能等价的 direct_python 员工包。

全量提取 Word 文档：用户上传 .docx 后，真实解析（禁止 LLM 编造正文），输出：
1. outputs/document_full.json — 含 paragraphs、tables、outline、blocks、sections、images、styles、headers_footers、core_properties、comments、metadata、plain_text
2. outputs/document_full.txt — 纯文本汇总
3. outputs/images/ — 内嵌图片

技术要求：
- handlers 必须仅为 ["direct_python"]
- runtime_kind: word_full_extract
- backend/vendor 须有 convert_file(src, output_path, ...) 实现；优先 OOXML 解析，可选用 python-docx 增强
- 不支持旧版 .doc 二进制，仅 .docx
- manifest.json 含完整 employee_config_v2
- 成功条件：实际写出 document_full.json，否则返回明确错误

本包用于 LLM 写码训练对比，可与 library/word-full-read-employee 对照质检。"""


def _http_json(method: str, url: str, *, token=None, body=None, timeout: int = 120):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _step_summary(session: dict) -> list[dict]:
    out = []
    for s in session.get("steps") or []:
        out.append(
            {
                "id": s.get("id"),
                "status": s.get("status"),
                "detail": (s.get("detail") or s.get("message") or "")[:300],
            }
        )
    return out


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "intent": "employee",
        "brief": BRIEF,
        "description": BRIEF,
        "employee_target": "pack_only",
        "embed_script_workflow": False,
        "provider": PROVIDER,
        "model": MODEL,
        "replace": False,
        "pack_id": PACK_ID,
    }
    code, login_body = _http_json(
        "POST",
        f"{BASE_URL}/api/auth/login",
        body={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
    if code >= 400 or not isinstance(login_body, dict) or not login_body.get("access_token"):
        print(json.dumps({"ok": False, "stage": "login", "status": code}, ensure_ascii=False))
        return 2
    token = str(login_body["access_token"])

    started = time.time()
    code, start_body = _http_json(
        "POST", f"{BASE_URL}/api/workbench/sessions", token=token, body=metadata, timeout=120
    )
    if code >= 400 or not isinstance(start_body, dict):
        print(
            json.dumps(
                {"ok": False, "stage": "start", "status": code, "text": str(start_body)[:2000]},
                ensure_ascii=False,
            )
        )
        return 1
    sid = start_body.get("session_id")
    final = None
    deadline = time.time() + 45 * 60
    last_log = 0.0
    while time.time() < deadline:
        code, poll_body = _http_json(
            "GET", f"{BASE_URL}/api/workbench/sessions/{sid}", token=token, timeout=60
        )
        if code >= 400 or not isinstance(poll_body, dict):
            print(json.dumps({"ok": False, "stage": "poll", "status": code}, ensure_ascii=False))
            return 1
        final = poll_body
        st = final.get("status")
        if time.time() - last_log >= 15:
            steps = _step_summary(final)
            active = [s for s in steps if s["status"] not in ("done", "skipped", "error")]
            print(
                json.dumps(
                    {
                        "t": int(time.time() - started),
                        "status": st,
                        "active": active[:3],
                        "done_steps": len([s for s in steps if s["status"] == "done"]),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            last_log = time.time()
        if st in ("done", "error"):
            break
        time.sleep(3)

    art = (final or {}).get("artifact") if isinstance((final or {}).get("artifact"), dict) else {}
    qr = art.get("quality_report") if isinstance(art.get("quality_report"), dict) else {}
    pack_dir = ROOT / "library" / PACK_ID
    convert_py = pack_dir / "backend" / "vendor" / "word_full_read" / "convert.py"
    employee_py = (
        list((pack_dir / "backend" / "employees").glob("*.py"))
        if (pack_dir / "backend" / "employees").is_dir()
        else []
    )

    cleanup_result = None
    try:
        from modstore_server.employee_pack_cleanup import cleanup_experimental_pack

        cleanup_result = cleanup_experimental_pack(PACK_ID, metadata={"experimental_pack": True})
    except Exception as exc:  # noqa: BLE001
        cleanup_result = {"error": str(exc)[:300]}

    report = {
        "ok": (final or {}).get("status") == "done",
        "session_id": sid,
        "elapsed_sec": int(time.time() - started),
        "provider": PROVIDER,
        "model": MODEL,
        "pack_id": PACK_ID,
        "final_status": (final or {}).get("status"),
        "pipeline_label": qr.get("pipeline_label"),
        "runtime_generation": art.get("runtime_generation"),
        "domain_smoke": art.get("domain_smoke"),
        "golden_comparison": art.get("golden_comparison"),
        "cleanup": cleanup_result,
        "rule_spec_runtime_kind": (
            (((final or {}).get("artifact") or {}).get("rule_spec") or {}).get("runtime_kind")
            if isinstance((final or {}).get("artifact"), dict)
            else None
        ),
        "quality_report": qr,
        "six_dimension": art.get("six_dimension_report"),
        "pack_exists": pack_dir.is_dir(),
        "has_convert_py": convert_py.is_file(),
        "employee_modules": [p.name for p in employee_py],
        "steps": _step_summary(final or {}),
        "error": (final or {}).get("error"),
    }
    OUT_JSON.write_text(
        json.dumps({"report": report, "final": final}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
