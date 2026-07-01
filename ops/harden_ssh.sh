#!/usr/bin/env bash
# 在你的 Mac 上运行：给生产 CVM 换上 SSH 密钥并关掉密码登录（root 弱密码是全仓最大单点风险）。
#
#   bash ops/harden_ssh.sh            # 全流程（会提示确认两次）
#   bash ops/harden_ssh.sh --revert   # 恢复密码登录（需已有密钥）
#
# 安全设计：
#   1. 先装公钥并「用密钥实测登录成功」，才会动 sshd 配置——不会把自己锁在门外。
#   2. sshd 改动走 /etc/ssh/sshd_config.d/99-xcmax-hardening.conf 独立文件，
#      改前 sshd -t 语法校验，revert = 删该文件 + reload。
#   3. 万一失联：腾讯云控制台 → 实例 → VNC 登录仍可救（与 sshd 无关）。
set -euo pipefail

HOST="${FHD_PUSH_HOST:-119.27.178.147}"
USER="root"
KEY="${OPS_SSH_KEY:-$HOME/.ssh/xcmax_cvm_ed25519}"
DROPIN="/etc/ssh/sshd_config.d/99-xcmax-hardening.conf"

say() { printf '\033[1;34m[harden]\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--revert" ]]; then
  say "恢复密码登录..."
  ssh -i "$KEY" -o IdentitiesOnly=yes "${USER}@${HOST}" \
    "rm -f ${DROPIN} && (sshd -t && systemctl reload sshd || systemctl reload ssh)"
  say "已恢复（${DROPIN} 已删除）"
  exit 0
fi

if [[ ! -f "$KEY" ]]; then
  say "生成专用密钥 $KEY"
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "xcmax-cvm-$(date +%Y%m%d)"
fi

say "第 1 步：安装公钥（此步会要求输入 root 密码，最后一次用密码）"
ssh-copy-id -i "${KEY}.pub" "${USER}@${HOST}"

say "第 2 步：验证密钥登录"
if ! ssh -i "$KEY" -o IdentitiesOnly=yes -o PasswordAuthentication=no \
    -o ConnectTimeout=10 "${USER}@${HOST}" "echo key-login-ok"; then
  say "密钥登录失败，中止（密码登录未被改动）"
  exit 1
fi
say "密钥登录 OK"

say "第 3 步：关闭密码认证（drop-in: ${DROPIN}）"
read -r -p "确认关闭密码登录? 失联时可用腾讯云控制台 VNC 恢复 [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
  say "已取消。密钥已可用，密码登录保持开启。"
  exit 0
fi
ssh -i "$KEY" -o IdentitiesOnly=yes "${USER}@${HOST}" bash -s <<'REMOTE'
set -euo pipefail
mkdir -p /etc/ssh/sshd_config.d
# 主配置若没 include sshd_config.d，则补一行（放最前，Include 需在其它指令前生效也可用追加+校验兜底）
if ! grep -qE '^[Ii]nclude +/etc/ssh/sshd_config.d/\*\.conf' /etc/ssh/sshd_config; then
  sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
fi
cat > /etc/ssh/sshd_config.d/99-xcmax-hardening.conf <<'CONF'
# XCMAX ops/harden_ssh.sh 生成——密钥登录专用；删除本文件并 reload 即恢复
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 4
CONF
sshd -t
systemctl reload sshd 2>/dev/null || systemctl reload ssh
echo "sshd reloaded"
REMOTE

say "第 4 步：新开连接复验（密钥应通，密码应拒）"
ssh -i "$KEY" -o IdentitiesOnly=yes -o PasswordAuthentication=no \
  "${USER}@${HOST}" "echo hardened-ok && sshd -T 2>/dev/null | grep -i passwordauthentication || true"

say "完成。以后连接：ssh -i $KEY root@$HOST"
say "建议把以下加入 ~/.ssh/config："
cat <<EOF

Host xcmax-cvm
    HostName $HOST
    User root
    IdentityFile $KEY
    IdentitiesOnly yes
EOF
