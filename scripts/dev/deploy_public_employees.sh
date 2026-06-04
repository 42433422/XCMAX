#!/usr/bin/env bash
# 同步编制员工包 + MODstore 后端到公网 CVM，并刷新 Catalog。
# 用法:
#   DEPLOY_ALLOW_PUBLIC=1 bash FHD/scripts/dev/deploy_public_employees.sh
# 凭据: 成都修茈科技有限公司/deploy/.env.deploy.local 或 market/.deploy-ssh.local
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
XCMAX_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
DEPLOY_SCRIPTS="${XCMAX_ROOT}/成都修茈科技有限公司/deploy/scripts"
MARKET_SCRIPTS="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy/market/scripts"

# shellcheck disable=SC1091
source "${DEPLOY_SCRIPTS}/load-deploy-env.sh"
_load_deploy_env

export DEPLOY_ALLOW_PUBLIC="${DEPLOY_ALLOW_PUBLIC:-1}"
export DEPLOY_SSH_PASSWORD="${DEPLOY_SSH_PASSWORD:-${DEPLOY_PW:-}}"

if [[ -z "${DEPLOY_SSH_PASSWORD:-}" ]]; then
  echo "[err] 请设置 DEPLOY_SSH_PASSWORD（见 deploy/.env.deploy.local）" >&2
  exit 2
fi

REMOTE_FHD="${REMOTE_FHD:-/root/XCMAX/FHD}"
REMOTE_XCMAX="${REMOTE_XCMAX:-/root/XCMAX}"
MODSTORE_ROOT="${MODSTORE_API_ROOT:-/root/modstore-git/MODstore_deploy}"
# 线上 uvicorn 实际从 editable 包装载 modstore_server（常见为中文路径），须与 MODSTORE_ROOT 同步。
MODSTORE_RUNTIME_ROOT="${MODSTORE_RUNTIME_ROOT:-/root/成都修茈科技有限公司/MODstore_deploy}"
PY="${MODSTORE_ROOT}/.venv/bin/python"

TAR_MS="/tmp/modstore_server-employees-$$.tgz"
TAR_EMP="/tmp/fhd-employees-$$.tgz"
trap 'rm -f "${TAR_MS}" "${TAR_EMP}"' EXIT

MS_LOCAL="${XCMAX_ROOT}/成都修茈科技有限公司/MODstore_deploy/modstore_server"
echo "[pack] modstore_server → ${TAR_MS}"
tar -C "$(dirname "${MS_LOCAL}")" -czf "${TAR_MS}" "$(basename "${MS_LOCAL}")"

echo "[pack] FHD/mods/_employees → ${TAR_EMP}"
tar -C "${FHD_ROOT}/mods" -czf "${TAR_EMP}" _employees

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
    -re "Connection refused" { puts stderr "\n\[err\] SSH 连接被拒绝"; exit 10 }
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    -re "Permission denied" { puts stderr "\n\[err\] SSH 密码错误"; exit 11 }
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
    -re "Connection refused" { puts stderr "\n\[err\] SSH 连接被拒绝"; exit 10 }
    -re "(?i)password:" { send "\$pw\r"; exp_continue }
    -re "Permission denied" { puts stderr "\n\[err\] SSH 密码错误"; exit 11 }
    -re "active" { puts "\nmodstore active" }
    eof {}
  }
  catch wait result
  set exit_code [lindex \$result 3]
  if {\$exit_code != 0} { exit \$exit_code }
}

scp_up "${TAR_MS}" /tmp/modstore_server-employees.tgz
scp_up "${TAR_EMP}" /tmp/fhd-employees.tgz
scp_up "${FHD_ROOT}/scripts/dev/sync_fhd_employee_packs_to_catalog.py" /tmp/sync_fhd_employee_packs_to_catalog.py

ssh_run "set -e
mkdir -p '${REMOTE_XCMAX}/FHD/mods' '${MODSTORE_ROOT}' '${MODSTORE_RUNTIME_ROOT}'
cd '${MODSTORE_ROOT}'
tar -xzf /tmp/modstore_server-employees.tgz
rm -f /tmp/modstore_server-employees.tgz
rsync -a --delete '${MODSTORE_ROOT}/modstore_server/' '${MODSTORE_RUNTIME_ROOT}/modstore_server/'
find '${MODSTORE_ROOT}/modstore_server' '${MODSTORE_RUNTIME_ROOT}/modstore_server' -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
mkdir -p '${REMOTE_FHD}/mods'
tar -xzf /tmp/fhd-employees.tgz -C '${REMOTE_FHD}/mods'
rm -f /tmp/fhd-employees.tgz
mkdir -p '${REMOTE_FHD}/scripts/dev'
cp -f /tmp/sync_fhd_employee_packs_to_catalog.py '${REMOTE_FHD}/scripts/dev/'
'${PY}' '${REMOTE_FHD}/scripts/dev/sync_fhd_employee_packs_to_catalog.py' --force
systemctl restart modstore
sleep 2
systemctl is-active modstore
curl -sS -m 10 http://127.0.0.1:9999/api/health | head -c 120 || true
"
EOF

echo "[ok] 公网员工包与 MODstore 后端已同步，modstore 已重启"
