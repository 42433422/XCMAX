#!/usr/bin/env bash
# 同步本地 yuangon 编制目录到公网 CVM，并确保 MODSTORE_REPO_ROOT 指向含 yuangon 的仓库根。
# 用法: DEPLOY_ALLOW_PUBLIC=1 bash FHD/scripts/dev/sync_yuangon_to_prod.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
DEPLOY_SCRIPTS="${XCMAX_ROOT}/成都修茈科技有限公司/deploy/scripts"

# shellcheck disable=SC1091
source "${DEPLOY_SCRIPTS}/load-deploy-env.sh"
_load_deploy_env

export DEPLOY_ALLOW_PUBLIC="${DEPLOY_ALLOW_PUBLIC:-1}"
export DEPLOY_SSH_PASSWORD="${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}"

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "[err] 请设置 DEPLOY_SSH_PASSWORD" >&2
  exit 2
fi

YUANGON_LOCAL="${XCMAX_ROOT}/成都修茈科技有限公司/yuangon"
REMOTE_REPO_ROOT="${REMOTE_REPO_ROOT:-/root/成都修茈科技有限公司}"
REMOTE_YUANGON="${REMOTE_REPO_ROOT}/yuangon"
MODSTORE_ROOT="${MODSTORE_API_ROOT:-/root/modstore-git/MODstore_deploy}"
TAR_YG="/tmp/yuangon-sync-$$.tgz"
trap 'rm -f "${TAR_YG}"' EXIT

if [[ ! -d "${YUANGON_LOCAL}" ]]; then
  echo "[err] 本地 yuangon 不存在: ${YUANGON_LOCAL}" >&2
  exit 1
fi

echo "[pack] yuangon → ${TAR_YG}"
tar -C "$(dirname "${YUANGON_LOCAL}")" -czf "${TAR_YG}" "$(basename "${YUANGON_LOCAL}")"

REMOTE_CMD="set -e
mkdir -p ${REMOTE_REPO_ROOT}
cd ${REMOTE_REPO_ROOT}
tar -xzf /tmp/yuangon-sync.tgz
rm -f /tmp/yuangon-sync.tgz
count=\$(find ${REMOTE_YUANGON} -name employee.yaml | wc -l)
echo yuangon_employee_yaml_count=\$count
ENV_FILE=${MODSTORE_ROOT}/.env
touch \"\$ENV_FILE\"
if ! grep -q '^MODSTORE_REPO_ROOT=' \"\$ENV_FILE\" 2>/dev/null; then
  echo MODSTORE_REPO_ROOT=${REMOTE_REPO_ROOT} >> \"\$ENV_FILE\"
  echo added_MODSTORE_REPO_ROOT
else
  sed -i 's|^MODSTORE_REPO_ROOT=.*|MODSTORE_REPO_ROOT=${REMOTE_REPO_ROOT}|' \"\$ENV_FILE\"
  echo updated_MODSTORE_REPO_ROOT
fi
systemctl restart modstore
sleep 2
systemctl is-active modstore
${MODSTORE_ROOT}/.venv/bin/python -c \"from modstore_server.daily_employee_briefs import collect_yuangon_pack_excerpt; ex,w=collect_yuangon_pack_excerpt('ecosystem-partner-onboard-officer'); print('eco_excerpt_len', len(ex)); print('eco_warns', w[:1])\""

/usr/bin/expect <<EOF
set timeout 600
set pw \$env(DEPLOY_SSH_PASSWORD)
set host \$env(DEPLOY_SSH_HOST)
set user \$env(DEPLOY_SSH_USER)
set port \$env(DEPLOY_SSH_PORT)

proc scp_up {local remote} {
  global pw host user port
  spawn scp -o StrictHostKeyChecking=no -P \$port \$local \${user}@\${host}:\$remote
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    eof {}
  }
  catch wait result
  set exit_code [lindex \$result 3]
  if {\$exit_code != 0} { exit \$exit_code }
}

proc ssh_run {cmd} {
  global pw host user port
  spawn ssh -o StrictHostKeyChecking=no -p \$port \${user}@\${host} \$cmd
  expect {
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    -re "active" { puts "\nmodstore active" }
    eof {}
  }
  catch wait result
  set exit_code [lindex \$result 3]
  if {\$exit_code != 0} { exit \$exit_code }
}

scp_up "${TAR_YG}" /tmp/yuangon-sync.tgz
ssh_run {${REMOTE_CMD}}
EOF

echo "[ok] yuangon 已同步到 ${REMOTE_YUANGON}，MODSTORE_REPO_ROOT 已写入并重启 modstore"
