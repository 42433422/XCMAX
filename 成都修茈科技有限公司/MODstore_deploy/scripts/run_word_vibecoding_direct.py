#!/usr/bin/env python3
"""直调后端 vibecoding（不经 8765 编排），MiMo 写 convert + 冒烟 + 黄金对比。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / ".env.local", override=True)


BRIEF_TEMPLATE = """员工包 ID：{pack_id}
runtime_kind: word_full_extract
全量提取 Word docx，输出 document_full.json、document_full.txt、images/。
handlers 仅 direct_python。禁止编造正文，须真实解析 OOXML。"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--pack-id", type=str, default="")
    parser.add_argument("--provider", type=str, default=os.environ.get("SMOKE_LLM_PROVIDER") or "xiaomi")
    parser.add_argument("--model", type=str, default=os.environ.get("SMOKE_LLM_MODEL") or "mimo-v2.5-pro")
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()

    _load_env()
    os.chdir(ROOT)

    from modstore_server.employee_asset_pipeline import run_word_extract_employee_scaffold_async
    from modstore_server.employee_pack_cleanup import cleanup_experimental_pack
    from modstore_server.models import User, get_session_factory
    from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

    pack_id = (args.pack_id or f"word-full-read-employee-direct-{uuid.uuid4().hex[:8]}").strip()
    brief = BRIEF_TEMPLATE.format(pack_id=pack_id)
    session_id = uuid.uuid4().hex[:24]

    sf = get_session_factory()
    with sf() as db:
        if args.user_id is not None:
            user = db.query(User).filter(User.id == int(args.user_id)).first()
        else:
            user = db.query(User).order_by(User.id.asc()).first()
        if not user:
            print(json.dumps({"ok": False, "error": "no user in DB"}, ensure_ascii=False))
            return 2

        print(f"user_id={user.id} pack_id={pack_id} provider={args.provider} model={args.model}", flush=True)
        res = await run_word_extract_employee_scaffold_async(
            db,
            user,
            session_id=session_id,
            brief=brief,
            raw_files=[],
            replace=True,
            provider=args.provider,
            model=args.model,
            publish_to_catalog=False,
            force_llm_codegen=True,
            payload={"pack_id": pack_id, "experimental_pack": True},
        )

    rt = res.get("runtime_generation") if isinstance(res.get("runtime_generation"), dict) else {}
    gc = res.get("golden_comparison") if isinstance(res.get("golden_comparison"), dict) else {}
    ds = res.get("domain_smoke") if isinstance(res.get("domain_smoke"), dict) else {}

    report = {
        "ok": bool(res.get("ok")),
        "session_id": session_id,
        "pack_id": res.get("id"),
        "path": res.get("path"),
        "source": rt.get("source"),
        "llm_codegen": is_llm_codegen_source(rt),
        "parity": gc.get("parity_score"),
        "golden_passed": gc.get("passed"),
        "smoke_ok": ds.get("ok"),
        "round": rt.get("round"),
        "warnings": res.get("validate_warnings"),
        "error": rt.get("error"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not args.no_cleanup and pack_id:
        cleanup = cleanup_experimental_pack(pack_id, metadata={"experimental_pack": True})
        print("cleanup:", json.dumps(cleanup, ensure_ascii=False))

    passed = (
        report["ok"]
        and report["llm_codegen"]
        and report["smoke_ok"] is not False
        and (report["golden_passed"] is True or not gc.get("golden_pack_id"))
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
