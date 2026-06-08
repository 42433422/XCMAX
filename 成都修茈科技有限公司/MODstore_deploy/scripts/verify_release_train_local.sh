#!/usr/bin/env bash
# 本地 release_train 闭环冒烟：Phase A → 08:25 orchestrator（读取 .env）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.getcwd())
try:
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
except Exception:
    pass

os.environ.setdefault("XCMAX_MONOREPO_ROOT", str(root.parent.parent))
os.environ.setdefault("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "primary")
os.environ.setdefault("MODSTORE_RELEASE_TRAIN_REQUIRE_PHASE_A", "0")

import modstore_server.models as models

models._engine = None
models._SessionFactory = None
models.init_db()

from modstore_server.models import DailyDigestRecord, get_session_factory
from modstore_server.daily_vibe_line_execute_job import run_daily_vibe_line_execute_job
from modstore_server.daily_release_train_orchestrator_job import run_daily_release_train_orchestrator_job

sf = get_session_factory()
with sf() as session:
    row = DailyDigestRecord(
        day="local-verify",
        subject="local release_train verify",
        body_text="verify",
        vibe_prep_ps_md="# Vibe 预备 · P-S 软件线 · 补丁清单\n\n## [fhd-core-maintainer] 核心\n\n- **P0** local verify\n",
        vibe_prep_meta_json=json.dumps({"base_version": "local#verify#1"}),
        release_train_before="1.0.0.0",
        release_train_after="1.0.0.1",
        release_kind="daily",
    )
    session.add(row)
    session.commit()
    rid = int(row.id)

print("Phase A record_id=", rid)
a = run_daily_vibe_line_execute_job(record_id=rid, force=True)
print("Phase A:", json.dumps({k: a.get(k) for k in ("ok", "skipped", "unit_count", "error")}, ensure_ascii=False))
b = run_daily_release_train_orchestrator_job(record_id=rid, force=True)
print("Orchestrator ok:", b.get("ok"), "shadow:", b.get("shadow"), "mode:", b.get("digest_mode"))
print("phase_b ok:", (b.get("phase_b") or {}).get("ok"))
pipe = b.get("phase_c_pipeline") or {}
print("phase_c_pipeline:", json.dumps(
    {k: pipe.get(k) for k in ("ok", "paused", "executed_steps", "auto_approved", "error")},
    ensure_ascii=False,
))
PY
