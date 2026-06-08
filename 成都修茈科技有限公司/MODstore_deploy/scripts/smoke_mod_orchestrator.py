"""
一次性「做 Mod」冒烟：直调 workbench_api._run_pipeline（绕过 JWT），极小 brief。

用法（在 MODstore_deploy 根目录）:
  python scripts/smoke_mod_orchestrator.py
  python scripts/smoke_mod_orchestrator.py --user-id 1

依赖：数据库可连、该用户已配置可用 LLM Key（resolve_llm_provider_model_auto）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import py_compile
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _http_json(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, str]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        data = raw
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"").decode("utf-8", errors="replace")


async def _watch_steps(sid: str, stop: asyncio.Event) -> None:
    from modstore_server.workbench_api import WORKBENCH_SESSIONS

    while not stop.is_set():
        sess = WORKBENCH_SESSIONS.get(sid) or {}
        steps = sess.get("steps") or []
        line = " | ".join(f"{s.get('id')}:{s.get('status')}" for s in steps if isinstance(s, dict))
        print(f"[poll] status={sess.get('status')} steps={line[:200]}...")
        await asyncio.sleep(3)


async def _main(user_id: Optional[int]) -> int:
    os.chdir(ROOT)
    from modstore_server.models import CatalogItem, User, get_session_factory
    from modstore_server.mod_scaffold_runner import analyze_mod_employee_readiness
    from modstore_server.workbench_api import (
        WORKBENCH_SESSIONS,
        _default_steps,
        _persist_workbench_session_unlocked,
        _planning_record,
        _run_pipeline,
    )

    sf = get_session_factory()
    with sf() as db:
        if user_id is not None:
            user = db.query(User).filter(User.id == int(user_id)).first()
        else:
            user = db.query(User).order_by(User.id.asc()).first()
        if not user:
            print("ERROR: no user in DB")
            return 2
        uid = int(user.id)
        print(f"Using user id={uid} email={getattr(user, 'email', '')}")

    sid = uuid.uuid4().hex[:24]
    suggested = f"smoke-emp-mod-{sid[:8]}"
    payload: Dict[str, Any] = {
        "intent": "mod",
        "brief": (
            "做一个只有 2 名员工的迷你测试 Mod："
            "员工 A 把输入文本总结成三条要点；员工 B 只回复简短问候。"
            "不要接入任何外部真实 API。"
        ),
        "suggested_mod_id": suggested,
        "replace": True,
        "generate_full_suite": True,
        "generate_frontend": False,
        "execution_mode": "workflow",
        "planning_messages": [],
        "execution_checklist": [],
        "source_documents": [],
    }

    WORKBENCH_SESSIONS[sid] = {
        "id": sid,
        "user_id": uid,
        "intent": "mod",
        "status": "running",
        "steps": _default_steps("mod", "workflow"),
        "planning_record": _planning_record(payload),
        "artifact": None,
        "error": None,
        "validate_warnings": None,
        "sandbox_report": None,
        "script_result": None,
    }
    _persist_workbench_session_unlocked(sid)
    print(f"session_id={sid} suggested_mod_id={suggested}")

    stop = asyncio.Event()
    watcher = asyncio.create_task(_watch_steps(sid, stop))
    try:
        await _run_pipeline(sid, uid, payload)
    finally:
        stop.set()
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass

    sess = WORKBENCH_SESSIONS.get(sid) or {}
    status = sess.get("status")
    print(f"\n=== pipeline finished status={status} error={sess.get('error')} ===")
    for s in sess.get("steps") or []:
        if isinstance(s, dict):
            print(f"  {s.get('id')}: {s.get('status')} — {s.get('message')}")

    art = sess.get("artifact") or {}
    mod_id = str(art.get("mod_id") or "").strip()
    if not mod_id:
        print("ERROR: no mod_id in artifact")
        return 1

    from modstore_server.mod_scaffold_runner import modstore_library_path

    mod_dir = modstore_library_path() / mod_id
    if not mod_dir.is_dir():
        print(f"WARN: mod_dir missing at {mod_dir}, trying MODMAN_LIBRARY fallback")
        alt = os.environ.get("MODMAN_LIBRARY", "").strip()
        if alt:
            mod_dir = Path(alt).expanduser().resolve() / mod_id
    print(f"\nmod_dir={mod_dir}")

    bp = mod_dir / "backend" / "blueprints.py"
    if not bp.is_file():
        print(f"ERROR: missing {bp}")
        return 1
    src = bp.read_text(encoding="utf-8")
    if "import_mod_backend_py" not in src:
        print("ERROR: blueprints.py does not reference import_mod_backend_py")
        return 1
    try:
        py_compile.compile(str(bp), doraise=True)
    except py_compile.PyCompileError as e:
        print(f"ERROR: blueprints py_compile: {e}")
        return 1
    print("blueprints.py: OK (import_mod_backend_py + py_compile)")

    emp_dir = mod_dir / "backend" / "employees"
    py_files = sorted(emp_dir.glob("*.py")) if emp_dir.is_dir() else []
    py_files = [p for p in py_files if p.name != "__init__.py"]
    if not py_files:
        print("WARN: no backend/employees/*.py")
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            print(f"ERROR: {p.name} py_compile: {e}")
            return 1
        t = p.read_text(encoding="utf-8")
        if "async def run(" not in t:
            print(f"ERROR: {p.name} missing async def run")
            return 1
    print(f"employees: {len(py_files)} file(s) OK")

    with sf() as db2:
        rows = (
            db2.query(CatalogItem)
            .filter(CatalogItem.pkg_id.like(f"{mod_id}-%"), CatalogItem.artifact == "employee_pack")
            .all()
        )
        print(f"catalog employee_pack rows for prefix {mod_id}-*: {len(rows)}")
        for r in rows[:6]:
            print(f"  pkg_id={r.pkg_id} version={r.version} stored={getattr(r, 'stored_filename', '')}")

    with sf() as db3:
        user3 = db3.query(User).filter(User.id == uid).first()
        readiness = analyze_mod_employee_readiness(db3, user3, mod_dir)  # type: ignore[arg-type]
    print(f"\nemployee_readiness ok={readiness.get('ok')} summary={readiness.get('summary')}")
    if readiness.get("gaps"):
        for g in (readiness.get("gaps") or [])[:8]:
            print(f"  gap: {g}")

    # FHD HTTP（默认 5000；前端代理 5001 同路径）
    for base in ("http://127.0.0.1:5000", "http://127.0.0.1:5001"):
        hello_url = f"{base}/api/mod/{mod_id}/hello"
        code, text = _http_json("GET", hello_url)
        print(f"\nGET {hello_url} -> {code} {text[:300]}")
        if code != 200:
            continue
        emp_url = f"{base}/api/mod/{mod_id}/employees"
        c2, t2 = _http_json("GET", emp_url)
        print(f"GET {emp_url} -> {c2} {t2[:400]}")
        emp_list: List[Dict[str, Any]] = []
        try:
            j = json.loads(t2)
            if isinstance(j, dict):
                d = j.get("data")
                if isinstance(d, list):
                    emp_list = [x for x in d if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
        first_id = ""
        if emp_list and isinstance(emp_list[0], dict):
            first_id = str(emp_list[0].get("id") or "").strip()
        if first_id:
            run_url = f"{base}/api/mod/{mod_id}/employees/{first_id}/run"
            c3, t3 = _http_json("POST", run_url, {"text": "冒烟测试一句话"})
            print(f"POST {run_url} -> {c3} {t3[:500]}")

    print("\nartifact keys:", sorted(art.keys()))
    return 0 if status == "done" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, default=None)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_main(args.user_id)))
