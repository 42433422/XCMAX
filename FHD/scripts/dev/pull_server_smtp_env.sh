#!/usr/bin/env bash
# 从公网 MODstore 服务器拉取 SMTP 相关 .env 行 → 本机 FHD/XCAGI/.env.smtp.local
# 凭据：deploy/.env.deploy.local（DEPLOY_SSH_PASSWORD）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOY_ENV="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/deploy/.env.deploy.local"
OUT="${FHD_ROOT}/XCAGI/.env.smtp.local"
MODSTORE_ROOT="${MODSTORE_API_ROOT:-/root/modstore-git/MODstore_deploy}"

log() { printf '[pull-smtp] %s\n' "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -f "${DEPLOY_ENV}" ]] || fail "未找到 ${DEPLOY_ENV}"
# shellcheck disable=SC1090
source "${DEPLOY_ENV}"

HOST="${DEPLOY_SSH_HOST:-119.27.178.147}"
USER="${DEPLOY_SSH_USER:-root}"
PORT="${DEPLOY_SSH_PORT:-22}"
PW="${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}"
[[ -n "${PW}" ]] || fail "DEPLOY_SSH_PASSWORD 未设置"

REMOTE_CMD="grep -hE '^(MODSTORE_SMTP|MODSTORE_SENDER|MODSTORE_EMAIL|MODSTORE_DAILY_DIGEST)' ${MODSTORE_ROOT}/.env ${MODSTORE_ROOT}/.env.local ${MODSTORE_ROOT}/.env.production 2>/dev/null"

TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

/usr/bin/expect <<EXPECT_EOF >"${TMP}" 2>&1
set timeout 60
set pw "${PW}"
spawn ssh -o StrictHostKeyChecking=no -p ${PORT} ${USER}@${HOST} ${REMOTE_CMD}
expect {
  -re "(?i)password:" { send "\$pw\r"; exp_continue }
  eof {}
}
catch wait r
set ec [lindex \$r 3]
if {\$ec != 0} { exit \$ec }
EXPECT_EOF

if grep -qiE 'connection refused|no route|could not resolve|permission denied' "${TMP}"; then
  fail "SSH 失败（${HOST}:${PORT}）— 请在腾讯云安全组开放 SSH 后重试"
fi

# 去掉 expect/spawn 噪声，只保留远程 grep 输出
grep -E '^MODSTORE_' "${TMP}" > "${TMP}.clean" || true
mv "${TMP}.clean" "${TMP}"

if [[ ! -s "${TMP}" ]]; then
  fail "服务器未返回 SMTP 配置行（检查 ${MODSTORE_ROOT}/.env.local）"
fi

# 同名键多文件时：非占位符行优先（真实授权码通常在 .env.local）
python3 - "${TMP}" "${OUT}" "${HOST}" <<'PY'
import sys
from datetime import datetime, timezone

src, out, host = sys.argv[1:4]
kv: dict[str, str] = {}
for raw in open(src, encoding="utf-8", errors="replace"):
    line = raw.strip().replace("\r", "")
    if not line.startswith("MODSTORE_") or "=" not in line:
        continue
    key, val = line.split("=", 1)
    val = val.strip()
    if ("your-" in val or val == "CHANGE_ME") and key in kv:
        continue
    kv[key] = val

pwd = kv.get("MODSTORE_SMTP_PASSWORD", "")
if not pwd or "your-" in pwd:
    print("未解析到真实 MODSTORE_SMTP_PASSWORD", file=sys.stderr)
    sys.exit(1)

kv["MODSTORE_EMAIL_DEBUG"] = "0"
order = [
    "MODSTORE_SMTP_HOST", "MODSTORE_SMTP_PORT", "MODSTORE_SMTP_USER", "MODSTORE_SMTP_PASSWORD",
    "MODSTORE_SENDER_EMAIL", "MODSTORE_SENDER_NAME", "MODSTORE_DAILY_DIGEST_EMAIL",
    "MODSTORE_IMAP_HOST", "MODSTORE_IMAP_PORT", "MODSTORE_IMAP_USER", "MODSTORE_IMAP_PASSWORD",
    "MODSTORE_EMAIL_INTAKE_ENABLED", "MODSTORE_EMAIL_DEBUG",
]
kv.setdefault("MODSTORE_IMAP_HOST", "imap.qq.com")
kv.setdefault("MODSTORE_IMAP_PORT", "993")
if kv.get("MODSTORE_SMTP_USER"):
    kv.setdefault("MODSTORE_IMAP_USER", kv["MODSTORE_SMTP_USER"])
if kv.get("MODSTORE_SMTP_PASSWORD"):
    kv.setdefault("MODSTORE_IMAP_PASSWORD", kv["MODSTORE_SMTP_PASSWORD"])
kv.setdefault("MODSTORE_EMAIL_INTAKE_ENABLED", "1")
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
lines = [f"# 从 {host} 同步 {ts} — 勿提交 git"]
for k in order:
    if k in kv:
        lines.append(f"{k}={kv[k]}")
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
[[ $? -eq 0 ]] || fail "解析 SMTP 配置失败"
chmod 600 "${OUT}"
log "已写入 ${OUT}（$(wc -l < "${OUT}" | tr -d ' ') 行）"
log "请重启: bash FHD/scripts/dev/run_modstore_daily_local.sh"
