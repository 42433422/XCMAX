#!/usr/bin/env bash
# 在 Linux 服务器上以 root 执行：统一 systemd 的 EnvironmentFile 到 modstore-git/.env，
# 收紧权限，追加 LLM 占位说明。
#
# 注意：若 /root/modstore-git 是指向 /root/成都修茈科技有限公司 的符号链接，则
# modstore-git/MODstore_deploy/.env 与 成都修茈/.../MODstore_deploy/.env 为同一文件，
# 绝不可对二者再做 ln -sf（会形成自引用循环）。本脚本会检测并跳过合并步骤。
#
# 上传后请确保 LF 换行： sed -i 's/\r$//' fix_server_env_unify.sh
set -euo pipefail

MAIN=/etc/systemd/system/modstore.service
ENV_CANON=/root/modstore-git/MODstore_deploy/.env
ENV_CN="/root/成都修茈科技有限公司/MODstore_deploy/.env"
TS="$(date +%Y%m%d%H%M%S)"

CANON_REAL="$(readlink -f "$ENV_CANON" 2>/dev/null || true)"
CN_REAL="$(readlink -f "$ENV_CN" 2>/dev/null || true)"

if [[ ! -f "$ENV_CANON" ]] && [[ ! -L "$ENV_CANON" ]]; then
  echo "ERROR: missing $ENV_CANON" >&2
  exit 1
fi

if grep -q 'releases/xcai-82b5c8b/MODstore_deploy/.env' "$MAIN" 2>/dev/null; then
  cp -a "$MAIN" "${MAIN}.bak.${TS}"
  sed -i 's|EnvironmentFile=-/root/releases/xcai-82b5c8b/MODstore_deploy/.env|EnvironmentFile=-/root/modstore-git/MODstore_deploy/.env|' "$MAIN"
  echo "OK: systemd EnvironmentFile -> $ENV_CANON"
else
  echo "NOTE: main unit already different; current EnvironmentFile lines:"
  grep -E '^EnvironmentFile' "$MAIN" || true
fi

if [[ -n "$CANON_REAL" && -n "$CN_REAL" && "$CANON_REAL" == "$CN_REAL" ]]; then
  echo "OK: skip .env symlink (modstore-git and 成都修茈 resolve to same file: $CANON_REAL)"
else
  if [[ -f "$ENV_CN" ]] && [[ ! -L "$ENV_CN" ]]; then
    cp -a "$ENV_CN" "${ENV_CN}.bak.${TS}"
    rm -f "$ENV_CN"
    ln -sf "$ENV_CANON" "$ENV_CN"
    echo "OK: symlink $ENV_CN -> $ENV_CANON"
  elif [[ -L "$ENV_CN" ]]; then
    echo "NOTE: $ENV_CN already symlink -> $(readlink "$ENV_CN" 2>/dev/null || true)"
  elif [[ ! -e "$ENV_CN" ]]; then
    mkdir -p "$(dirname "$ENV_CN")"
    ln -sf "$ENV_CANON" "$ENV_CN"
    echo "OK: created $ENV_CN -> $ENV_CANON"
  fi
fi

chmod 600 "$ENV_CANON" 2>/dev/null || chmod 600 "$CANON_REAL"

if ! grep -q 'MODSTORE_LLM_ENV_BLOCK_v1' "$ENV_CANON"; then
  {
    echo ""
    echo "# MODSTORE_LLM_ENV_BLOCK_v1 — 平台 LLM：到各厂商控制台创建密钥后取消注释并填值，然后: systemctl restart modstore"
    echo "# MINIMAX_API_KEY="
    echo "# MINIMAX_BASE_URL=https://api.minimaxi.com"
    echo "# OPENAI_API_KEY="
    echo "# DEEPSEEK_API_KEY="
    echo "# MOONSHOT_API_KEY="
    echo "# DASHSCOPE_API_KEY="
    echo "# ARK_API_KEY="
  } >>"$ENV_CANON"
  echo "OK: appended LLM template block"
fi

systemctl daemon-reload
systemctl restart modstore
sleep 2
systemctl is-active modstore.service
systemctl show modstore.service -p EnvironmentFiles,WorkingDirectory --no-pager
