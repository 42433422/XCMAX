#!/usr/bin/env bash
# 在生产机 .env 末尾追加/更新日更闭环开关（幂等片段）
set -euo pipefail
ENV_FILE="${1:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/.env}"
MARK_BEGIN="# >>> daily-closure v10 (managed)"
MARK_END="# <<< daily-closure v10"
BACKUP="${ENV_FILE}.bak.$(date +%Y%m%d%H%M%S)"
cp "$ENV_FILE" "$BACKUP"
python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
begin = "# >>> daily-closure v10 (managed)"
end = "# <<< daily-closure v10"
block = """# >>> daily-closure v10 (managed)
MODSTORE_REPO_ROOT=/root/XCMAX
XCMAX_MONOREPO_ROOT=/root/XCMAX
MODSTORE_RELEASE_TRAIN_JSON=/root/XCMAX/FHD/config/release_train.json
MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=primary
MODSTORE_DAILY_ORCHESTRATOR_ENABLED=1
MODSTORE_DAILY_DIGEST_ENABLED=1
MODSTORE_DAILY_MEETING_ENABLED=1
MODSTORE_DAILY_VIBE_PREP_ENABLED=1
MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED=1
MODSTORE_DAILY_VIBE_EXECUTE_ENABLED=1
MODSTORE_RELEASE_TRAIN_ENABLED=1
MODSTORE_AUTO_PR_ENABLED=1
MODSTORE_AUTO_PR_BASE_BRANCH=main
MODSTORE_DEPLOY_PUSH_REMOTE=origin
MODSTORE_DEPLOY_PUSH_BRANCH_PREFIX=auto/daily-
MODSTORE_OPS_STAGED_AUTO_APPROVE=1
MODSTORE_OPS_STAGED_AUTO_MAX_FILES=24
MODSTORE_SLO_HALT_AUTO_MERGE=1
MODSTORE_RELEASE_SLO_HALT=1
MODSTORE_CR_GIT_BRANCH_ENABLED=1
MODSTORE_CR_GIT_APPLY_COMMIT=1
MODSTORE_CR_GIT_AUTO_PR=1
MODSTORE_AUTO_APPROVE_ENABLED=1
MODSTORE_AUTO_APPROVE_REQUIRE_CI=1
MODSTORE_CR_NARROW_CI_ENABLED=1
MODSTORE_INBOX_POLL_ENABLED=1
MODSTORE_POST_DEPLOY_SMOKE_ENABLED=1
MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1
MODSTORE_DEPLOY_HEALTH_URL=http://127.0.0.1:9999/api/health
MODSTORE_POST_DEPLOY_MARKET_URL=https://xiu-ci.com/market/download
MODSTORE_LINE_PRIMARY_LINES=P-S
MODSTORE_LINE_SHADOW_LINES=P-W,P-App,S-R
MODSTORE_DR_PROBE_ENABLED=1
MODSTORE_ONDEMAND_BACKUP_ENABLED=1
MODSTORE_SURFACE_AUDIT_AUTO_START=1
MODSTORE_RUN_BACKGROUND_JOBS=1
# <<< daily-closure v10
"""
if begin in text:
    pre, rest = text.split(begin, 1)
    _, post = rest.split(end, 1)
    text = pre.rstrip() + "\n\n" + block + post.lstrip("\n")
else:
    text = text.rstrip() + "\n\n" + block + "\n"
path.write_text(text, encoding="utf-8")
print(f"patched {path}")
PY
echo "backup: $BACKUP"
