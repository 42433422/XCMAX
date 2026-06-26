#!/usr/bin/env python3
"""将 admin 账户默认 LLM 设为 xiaomi / mimo-v2.5-pro（本地 SQLite/Postgres）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT / ".env.local", override=True)

from modstore_server.models import User, get_session_factory

PROVIDER = "xiaomi"
MODEL = "mimo-v2.5-pro"
USERNAME = "admin"


def main() -> int:
    sf = get_session_factory()
    with sf() as db:
        user = db.query(User).filter(User.username == USERNAME).first()
        if not user:
            print(f"FAIL: 未找到用户 {USERNAME!r}，请先启动 API 完成 bootstrap")
            return 1
        user.default_llm_json = json.dumps(
            {"provider": PROVIDER, "model": MODEL}, ensure_ascii=False
        )
        db.commit()
        print(f"OK: {USERNAME} default_llm -> {PROVIDER} / {MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
