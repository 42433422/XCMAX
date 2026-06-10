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
# 服务器跟跑：日更 digest/编排在 Mac；本机 cron 仅备份/DR/smoke + xcmax-site-auto-update 拉 git
MODSTORE_AUTOMATION_PRIMARY=local_mac
MODSTORE_AUTOMATION_ROLE=server
MODSTORE_REPO_ROOT=/root/XCMAX
XCMAX_MONOREPO_ROOT=/root/XCMAX
MODSTORE_RELEASE_TRAIN_JSON=/root/XCMAX/FHD/config/release_train.json
MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=off
MODSTORE_DAILY_ORCHESTRATOR_ENABLED=0
MODSTORE_DAILY_DIGEST_ENABLED=0
MODSTORE_DAILY_MEETING_ENABLED=0
MODSTORE_DAILY_VIBE_PREP_ENABLED=0
MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED=0
MODSTORE_DAILY_VIBE_EXECUTE_ENABLED=0
MODSTORE_RELEASE_TRAIN_ENABLED=0
MODSTORE_INBOX_POLL_ENABLED=0
MODSTORE_POST_DEPLOY_SMOKE_ENABLED=1
MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1
MODSTORE_DEPLOY_HEALTH_URL=http://127.0.0.1:9999/api/health
MODSTORE_POST_DEPLOY_MARKET_URL=https://xiu-ci.com/market/download
MODSTORE_DR_PROBE_ENABLED=1
MODSTORE_ONDEMAND_BACKUP_ENABLED=1
MODSTORE_SURFACE_AUDIT_AUTO_START=0
MODSTORE_SURFACE_AUDIT_PS_ENABLED=0
MODSTORE_RUN_BACKGROUND_JOBS=1
# <<< daily-closure v10
"""
managed_keys = {
    ln.split("=", 1)[0].strip()
    for ln in block.splitlines()
    if "=" in ln and not ln.strip().startswith("#")
}
# 去掉旧 managed 块，并剥离块内键的散落重复行（dedupe 保留最后值 → 块必须置尾）
while begin in text:
    pre, rest = text.split(begin, 1)
    _, post = rest.split(end, 1)
    text = pre + post
clean: list[str] = []
for line in text.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        clean.append(line)
        continue
    if "=" not in line:
        clean.append(line)
        continue
    key = line.split("=", 1)[0].strip()
    if key in managed_keys:
        continue
    clean.append(line)
text = "\n".join(clean).rstrip() + "\n\n" + block + "\n"
path.write_text(text, encoding="utf-8")
print(f"patched {path}")
PY
echo "backup: $BACKUP"
