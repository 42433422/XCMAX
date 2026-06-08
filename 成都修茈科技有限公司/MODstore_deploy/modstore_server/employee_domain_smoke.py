"""员工包领域冒烟：进程内执行 direct_python（不依赖 HTTP）。"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


def _load_run_from_pack(pack_dir: Path, pack_id: str):
    backend = pack_dir / "backend" / "employees"
    if not backend.is_dir():
        return None
    candidates = list(backend.glob("*.py"))
    candidates = [p for p in candidates if p.name != "__init__.py"]
    if not candidates:
        return None
    mod_path = candidates[0]
    spec = importlib.util.spec_from_file_location(f"_emp_smoke_{pack_id}", mod_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, "run", None)


async def run_pack_domain_smoke(
    pack_dir: Path,
    *,
    pack_id: str,
    runtime_kind: str,
) -> Dict[str, Any]:
    """对已落盘员工包跑一次领域 fixture。"""
    pack_dir = Path(pack_dir)
    pid = str(pack_id or pack_dir.name).strip()
    rk = (runtime_kind or "").strip()
    out: Dict[str, Any] = {"ok": False, "runtime_kind": rk, "pack_id": pid, "skipped": False}

    if rk not in (
        "word_full_extract",
        "txt_full_read",
        "txt_generate",
        "excel_full_read",
        "csv_full_read",
        "pdf_full_read",
        "ppt_full_read",
    ):
        out["skipped"] = True
        out["ok"] = True
        out["note"] = "no domain smoke for runtime"
        return out

    run_fn = _load_run_from_pack(pack_dir, pid)
    if run_fn is None:
        out["error"] = "employee run() not found"
        return out

    session_dir = pack_dir.parent / ".domain_smoke" / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)
    try:
        if rk == "word_full_extract":
            from modstore_server.word_extract_runtime import minimal_docx_bytes

            fname = "smoke.docx"
            dest = session_dir / fname
            dest.write_bytes(minimal_docx_bytes())
            output_rel = "outputs/document_full.json"
        elif rk == "txt_full_read":
            from modstore_server.txt_extract_runtime import minimal_txt_fixture_bytes

            fname = "smoke.txt"
            dest = session_dir / fname
            dest.write_bytes(minimal_txt_fixture_bytes())
            output_rel = "outputs/document_full.txt"
        elif rk == "txt_generate":
            from modstore_server.txt_extract_runtime import minimal_txt_fixture_bytes

            fname = "inputs/document_full.txt"
            (session_dir / "inputs").mkdir(parents=True, exist_ok=True)
            dest = session_dir / "inputs" / "document_full.txt"
            dest.write_bytes(minimal_txt_fixture_bytes())
            output_rel = "outputs/generated_document.txt"
        else:
            out["skipped"] = True
            out["ok"] = True
            out["note"] = f"fixture not implemented for {rk}"
            return out

        payload = {
            "action": "convert",
            "file_path": str(dest.resolve()),
            "workspace_root": str(session_dir.resolve()),
            "output_relpath": output_rel,
        }
        ctx = {"workspace_root": str(session_dir.resolve())}
        result = run_fn(payload, ctx)
        if hasattr(result, "__await__"):
            result = await result

        ok = False
        if isinstance(result, dict):
            ok = bool(result.get("ok"))
            inner = result
        else:
            inner = {}

        out_path = session_dir / output_rel
        out["output_exists"] = out_path.is_file()
        if out_path.is_file():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    out["output_json_keys"] = list(data.keys())[:40]
            except (json.JSONDecodeError, OSError):
                out["output_json_keys"] = []
        out["ok"] = bool(ok and out.get("output_exists"))
        if not out["ok"]:
            out["error"] = str(inner.get("error") or inner.get("summary") or "domain smoke failed")[
                :500
            ]
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:800]
        return out
    finally:
        import shutil

        shutil.rmtree(session_dir, ignore_errors=True)
