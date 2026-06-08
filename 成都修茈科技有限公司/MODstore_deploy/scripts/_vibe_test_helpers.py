"""临时测试辅助：用 admin token 调用 workbench 编排接口并轮询。

仅用于"员工vibecoding功能测试"会话。可随时删。
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional

import requests


BASE_URL = os.environ.get("MODSTORE_BASE_URL", "http://127.0.0.1:8765")


def headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def start_employee_session(token: str, brief: str, *, model: str = "mimo-v2.5-pro") -> Dict[str, Any]:
    body = {
        "intent": "employee",
        "brief": brief,
        "employee_target": "pack_only",
        "provider": "xiaomi",
        "model": model,
        "replace": True,
    }
    r = requests.post(f"{BASE_URL}/api/workbench/sessions", headers=headers(token), json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def poll_session(token: str, sid: str, *, interval: float = 1.0, max_seconds: int = 600) -> Dict[str, Any]:
    start = time.time()
    last_status: Optional[str] = None
    while time.time() - start < max_seconds:
        r = requests.get(f"{BASE_URL}/api/workbench/sessions/{sid}", headers=headers(token), timeout=30)
        r.raise_for_status()
        s = r.json()
        st = str(s.get("status") or "")
        if st != last_status:
            print(f"[poll t+{int(time.time()-start)}s] status={st} steps={len(s.get('steps') or [])}", flush=True)
            last_status = st
        if st in {"done", "error"}:
            return s
        time.sleep(interval)
    raise TimeoutError(f"workbench session {sid} did not finish in {max_seconds}s")


def execute_employee(token: str, employee_id: str, task: str, input_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # employee_api 用 query string 取 task
    params = {"task": task}
    body = input_data or {}
    r = requests.post(
        f"{BASE_URL}/api/employees/{employee_id}/execute",
        headers=headers(token),
        params=params,
        json=body,
        timeout=180,
    )
    if r.status_code >= 400:
        try:
            print("[execute] HTTP", r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=2))
        except Exception:
            print("[execute] HTTP", r.status_code, r.text[:500])
        r.raise_for_status()
    return r.json()


def build_doc_task(intent: str, repo_root: str, files: list[str]) -> str:
    """读取 files 内容并打包成 doc-organizer brief 期望的 JSON 任务。

    files 路径相对于 repo_root（即 MODstore_deploy/）。支持 ``path@start:end``
    语法只取行 ``[start, end]``（1-based, inclusive），用于在大文件里只挑相关片段。
    """
    from pathlib import Path

    payload: Dict[str, Any] = {"intent": intent, "files": []}
    base = Path(repo_root)
    for rel in files:
        slice_spec = ""
        rel_path = rel
        if "@" in rel and rel.rsplit("@", 1)[-1].count(":") == 1:
            rel_path, slice_spec = rel.rsplit("@", 1)
        full = base / rel_path
        if not full.is_file():
            raise FileNotFoundError(f"file not found: {full}")
        text = full.read_text(encoding="utf-8")
        if slice_spec:
            start_s, end_s = slice_spec.split(":")
            start = max(1, int(start_s))
            end = int(end_s)
            lines = text.splitlines(keepends=True)
            text = "".join(lines[start - 1 : end])
            text = f"# (excerpt {rel_path}:{start}-{end})\n" + text
        payload["files"].append({"path": rel_path.replace("\\", "/"), "content": text})
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    token = os.environ.get("MODSTORE_TOKEN", "")
    if not token:
        print("set MODSTORE_TOKEN env var first", file=sys.stderr)
        sys.exit(2)
    if cmd == "create_employee":
        brief = sys.argv[2] if len(sys.argv) > 2 else "做一个【文档整理员】员工"
        res = start_employee_session(token, brief)
        print("create:", json.dumps(res, ensure_ascii=False))
        sid = res["session_id"]
        final = poll_session(token, sid)
        print("final:", json.dumps(final, ensure_ascii=False)[:4000])
    elif cmd == "execute":
        emp_id = sys.argv[2]
        task = sys.argv[3]
        out = execute_employee(token, emp_id, task)
        print("execute:", json.dumps(out, ensure_ascii=False, indent=2)[:8000])
    elif cmd == "execute_doc":
        # execute_doc <emp_id> <intent> <repo_root> <file1> [file2] ...
        emp_id = sys.argv[2]
        intent = sys.argv[3]
        repo_root = sys.argv[4]
        files = sys.argv[5:]
        task = build_doc_task(intent, repo_root, files)
        print("task_len=", len(task), flush=True)
        out = execute_employee(token, emp_id, task)
        print("execute:", json.dumps(out, ensure_ascii=False, indent=2)[:12000])
    else:
        print("usage: create_employee <brief> | execute <emp_id> <task> | execute_doc <emp_id> <intent> <repo_root> <files...>")
        sys.exit(2)
