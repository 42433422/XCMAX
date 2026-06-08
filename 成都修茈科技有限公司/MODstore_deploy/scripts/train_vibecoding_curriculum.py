#!/usr/bin/env python3
"""并行 vibecoding 课程表训练：多员工会话 + 黄金对比 + 实验包清理。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRAIN_MAX_PARALLEL = 4
BASE_URL = (os.environ.get("SMOKE_BASE_URL") or "http://127.0.0.1:8765").rstrip("/")
USERNAME = os.environ.get("SMOKE_USERNAME") or "admin"
PASSWORD = os.environ.get("SMOKE_PASSWORD") or "admin123"
PROVIDER = os.environ.get("SMOKE_LLM_PROVIDER") or "xiaomi"
MODEL = os.environ.get("SMOKE_LLM_MODEL") or "mimo-v2.5-pro"

WAVE_PACKS: Dict[int, List[str]] = {
    1: ["word-full-read-employee"],
    2: [
        "excel-full-read-employee",
        "csv-full-read-employee",
        "pdf-full-read-employee",
        "ppt-full-read-employee",
        "word-full-read-employee",
    ],
    3: [
        "word-generate-employee",
        "excel-generate-employee",
        "csv-generate-employee",
        "pdf-generate-employee",
        "ppt-generate-employee",
    ],
}

RUNTIME_BRIEF: Dict[str, str] = {
    "word-full-read-employee": (
        "员工包 runtime_kind: word_full_extract。全量提取 Word docx，输出 document_full.json 与 document_full.txt，"
        "handlers 仅 direct_python。禁止编造正文，须真实解析 OOXML。"
    ),
    "excel-full-read-employee": (
        "员工包 runtime_kind: excel_full_read。全量读取 Excel，输出结构化 JSON，handlers 仅 direct_python。"
    ),
    "csv-full-read-employee": (
        "员工包 runtime_kind: csv_full_read。全量读取 CSV，输出结构化 JSON，handlers 仅 direct_python。"
    ),
    "pdf-full-read-employee": (
        "员工包 runtime_kind: pdf_full_read。全量读取 PDF，输出 JSON，handlers 仅 direct_python。"
    ),
    "ppt-full-read-employee": (
        "员工包 runtime_kind: ppt_full_read。全量读取 PPT，输出 JSON，handlers 仅 direct_python。"
    ),
    "word-generate-employee": (
        "员工包 runtime_kind: word_generate。由 JSON 生成 docx，handlers 仅 direct_python。"
    ),
    "excel-generate-employee": (
        "员工包 runtime_kind: excel_generate。由 JSON 生成 xlsx，handlers 仅 direct_python。"
    ),
    "csv-generate-employee": (
        "员工包 runtime_kind: csv_generate。由 JSON 生成 csv，handlers 仅 direct_python。"
    ),
    "pdf-generate-employee": (
        "员工包 runtime_kind: pdf_generate。由 JSON 生成 pdf，handlers 仅 direct_python。"
    ),
    "ppt-generate-employee": (
        "员工包 runtime_kind: ppt_generate。由 JSON 生成 pptx，handlers 仅 direct_python。"
    ),
}


def _http_json_sync(method: str, url: str, *, token: Optional[str] = None, body: Optional[dict] = None, timeout: int = 120):
    import urllib.error
    import urllib.request

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
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": raw[:2000]}


async def _login_token() -> str:
    code, body = await asyncio.to_thread(
        _http_json_sync,
        "POST",
        f"{BASE_URL}/api/auth/login",
        body={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
    if code >= 400 or not isinstance(body, dict) or not body.get("access_token"):
        raise RuntimeError(f"login failed: {code} {body}")
    return str(body["access_token"])


async def _poll_session(token: str, sid: str, *, deadline: float) -> Dict[str, Any]:
    while time.time() < deadline:
        code, body = await asyncio.to_thread(
            _http_json_sync,
            "GET",
            f"{BASE_URL}/api/workbench/sessions/{sid}",
            token=token,
            timeout=60,
        )
        if code >= 400 or not isinstance(body, dict):
            await asyncio.sleep(3)
            continue
        if body.get("status") in ("done", "error"):
            return body
        await asyncio.sleep(3)
    return {"status": "timeout", "session_id": sid}


async def _run_one_pack(
    sem: asyncio.Semaphore,
    token: str,
    golden_id: str,
    run_id: str,
    *,
    deadline_min: int,
) -> Dict[str, Any]:
    from modstore_server.employee_golden_compare import RUNTIME_TO_GOLDEN_PACK
    from modstore_server.employee_pack_cleanup import cleanup_experimental_pack

    train_pack_id = f"{golden_id}-vibecode-train-{run_id[:8]}"
    brief = RUNTIME_BRIEF.get(golden_id) or f"参考 {golden_id}，制作等价 direct_python 员工包。runtime_kind 与黄金包一致。"
    brief = f"员工包 ID：{train_pack_id}\n{brief}"

    entry: Dict[str, Any] = {
        "golden_id": golden_id,
        "train_pack_id": train_pack_id,
        "started_at": time.time(),
    }
    async with sem:
        try:
            code, start = await asyncio.to_thread(
                _http_json_sync,
                "POST",
                f"{BASE_URL}/api/workbench/sessions",
                token=token,
                body={
                    "intent": "employee",
                    "brief": brief,
                    "description": brief,
                    "employee_target": "pack_only",
                    "embed_script_workflow": False,
                    "provider": PROVIDER,
                    "model": MODEL,
                    "replace": False,
                    "pack_id": train_pack_id,
                    "experimental_pack": True,
                },
                timeout=120,
            )
            if code >= 400 or not isinstance(start, dict):
                entry["ok"] = False
                entry["error"] = f"start failed {code}"
                return entry
            sid = str(start.get("session_id") or "")
            entry["session_id"] = sid
            final = await _poll_session(token, sid, deadline=time.time() + deadline_min * 60)
            entry["final_status"] = final.get("status")
            art = final.get("artifact") if isinstance(final.get("artifact"), dict) else {}
            entry["runtime_generation"] = art.get("runtime_generation")
            entry["golden_comparison"] = art.get("golden_comparison")
            entry["domain_smoke"] = art.get("domain_smoke")
            entry["parity_score"] = (art.get("golden_comparison") or {}).get("parity_score")
            entry["ok"] = final.get("status") == "done"
            entry["error"] = final.get("error")
            rk = golden_id
            for k, v in RUNTIME_TO_GOLDEN_PACK.items():
                if v == golden_id:
                    entry["runtime_kind"] = k
                    break
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = str(exc)[:500]
        finally:
            cleanup = cleanup_experimental_pack(train_pack_id, metadata={"experimental_pack": True})
            entry["cleanup"] = cleanup
            entry["elapsed_sec"] = int(time.time() - entry["started_at"])
    return entry


async def run_curriculum(
    *,
    wave: int,
    packs: List[str],
    parallel: int,
    deadline_min: int,
) -> Dict[str, Any]:
    run_id = uuid.uuid4().hex
    out_dir = ROOT / "artifacts" / "vibecoding_train_runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    token = await _login_token()
    sem = asyncio.Semaphore(max(1, parallel))
    tasks = [_run_one_pack(sem, token, pid, run_id, deadline_min=deadline_min) for pid in packs]
    results = await asyncio.gather(*tasks)

    passed = sum(1 for r in results if r.get("ok"))
    parities = [float(r["parity_score"]) for r in results if r.get("parity_score") is not None]
    summary = {
        "run_id": run_id,
        "wave": wave,
        "packs": packs,
        "parallel": parallel,
        "provider": PROVIDER,
        "model": MODEL,
        "pass_rate": passed / len(results) if results else 0.0,
        "passed": passed,
        "total": len(results),
        "parity_avg": round(sum(parities) / len(parities), 1) if parities else None,
        "results": results,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Vibecoding curriculum training harness")
    parser.add_argument("--wave", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--pack", type=str, default="", help="comma-separated golden pack ids")
    parser.add_argument("--parallel", type=int, default=TRAIN_MAX_PARALLEL)
    parser.add_argument("--deadline-min", type=int, default=45)
    args = parser.parse_args()

    packs = [p.strip() for p in args.pack.split(",") if p.strip()] if args.pack else list(WAVE_PACKS[args.wave])
    summary = asyncio.run(
        run_curriculum(wave=args.wave, packs=packs, parallel=args.parallel, deadline_min=args.deadline_min)
    )
    return 0 if summary.get("passed") == summary.get("total") and summary.get("total") else 1


if __name__ == "__main__":
    raise SystemExit(main())
