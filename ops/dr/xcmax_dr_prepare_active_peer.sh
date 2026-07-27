#!/usr/bin/env bash
# Prepare the DR node as an always-on application peer. Database, Redis and
# write-path service calls stay single-primary through a restricted SSH tunnel.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

ACTION="${1:---activate}"
case "$ACTION" in
  --keygen|--print-public-key|--activate) ;;
  *)
    echo "用法: $0 [--keygen|--print-public-key|--activate]" >&2
    exit 2
    ;;
esac

PRIMARY_IP="${OPS_DR_PRIMARY_IP:-119.27.178.147}"
PEER_USER="${OPS_DR_PEER_USER:-xcmaxdrpeer}"
LOCAL_USER="${OPS_DR_LOCAL_PEER_USER:-xcmaxpeer}"
PEER_HOME="${OPS_DR_LOCAL_PEER_HOME:-/var/lib/xcmax-dr-peer}"
KEY_FILE="${OPS_DR_PEER_KEY:-$PEER_HOME/primary_tunnel_ed25519}"
KNOWN_HOSTS="${OPS_DR_PEER_KNOWN_HOSTS:-$PEER_HOME/known_hosts}"
PIN_FILE="${OPS_DR_PRIMARY_HOSTKEY_PIN_FILE:-/etc/xcmax-dr/primary_hostkey_sha256}"
PIN="${OPS_DR_PRIMARY_HOSTKEY_SHA256:-}"
PREPARE_RUNTIME="${OPS_DR_PREPARE_RUNTIME:-/usr/local/sbin/xcmax-dr-prepare-runtime}"
PREPARE_EDGE="${OPS_DR_PREPARE_EDGE:-/usr/local/sbin/xcmax-dr-prepare-edge}"

if ! id "$LOCAL_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$PEER_HOME" \
    --shell /usr/sbin/nologin "$LOCAL_USER"
fi
install -d -o "$LOCAL_USER" -g "$LOCAL_USER" -m 0700 "$PEER_HOME"
install -d -o root -g root -m 0755 /etc/xcmax-dr

if [[ ! -s "$KEY_FILE" ]]; then
  runuser -u "$LOCAL_USER" -- \
    ssh-keygen -q -t ed25519 -N "" -C "xcmax-dr-active-peer" -f "$KEY_FILE"
fi
chown "$LOCAL_USER:$LOCAL_USER" "$KEY_FILE" "$KEY_FILE.pub"
chmod 0600 "$KEY_FILE"
chmod 0644 "$KEY_FILE.pub"

if [[ "$ACTION" == "--keygen" || "$ACTION" == "--print-public-key" ]]; then
  cat "$KEY_FILE.pub"
  exit 0
fi

if [[ -z "$PIN" && -s "$PIN_FILE" ]]; then
  PIN="$(tr -d '[:space:]' <"$PIN_FILE")"
fi
[[ "$PIN" =~ ^SHA256:[A-Za-z0-9+/]+$ ]] || {
  echo "拒绝连接：请通过 OPS_DR_PRIMARY_HOSTKEY_SHA256 固定生产 SSH 主机指纹" >&2
  exit 1
}

scan="$(mktemp)"
trap 'rm -f -- "$scan"' EXIT
ssh-keyscan -T 10 -t ed25519 "$PRIMARY_IP" >"$scan" 2>/dev/null
[[ -s "$scan" ]] || {
  echo "无法获取生产 SSH 主机密钥" >&2
  exit 1
}
actual_pin="$(ssh-keygen -lf "$scan" -E sha256 | awk 'NR == 1 {print $2}')"
[[ "$actual_pin" == "$PIN" ]] || {
  echo "生产 SSH 主机指纹不匹配: expected=$PIN actual=$actual_pin" >&2
  exit 1
}
install -o "$LOCAL_USER" -g "$LOCAL_USER" -m 0600 "$scan" "$KNOWN_HOSTS"
printf '%s\n' "$PIN" >"$PIN_FILE"
chmod 0644 "$PIN_FILE"

cat >/etc/systemd/system/xcmax-dr-primary-tunnel.service <<EOF
[Unit]
Description=XCMAX DR restricted tunnel to the single primary
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$LOCAL_USER
ExecStart=/usr/bin/ssh -NT -i $KEY_FILE -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ConnectTimeout=10 -L 127.0.0.1:24443:127.0.0.1:443 -L 127.0.0.1:25100:127.0.0.1:5100 -L 127.0.0.1:25432:127.0.0.1:5432 -L 127.0.0.1:25433:127.0.0.1:5433 -L 127.0.0.1:26379:127.0.0.1:6379 -L 127.0.0.1:28080:127.0.0.1:8080 -L 127.0.0.1:29999:127.0.0.1:9999 $PEER_USER@$PRIMARY_IP
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 /etc/systemd/system/xcmax-dr-primary-tunnel.service
systemctl daemon-reload
systemctl enable --now xcmax-dr-primary-tunnel.service

deadline=$((SECONDS + 30))
while ((SECONDS < deadline)); do
  if systemctl is-active --quiet xcmax-dr-primary-tunnel.service &&
    ss -H -lnt | awk '{print $4}' | grep -qE '127\.0\.0\.1:25433$'; then
    break
  fi
  sleep 1
done
systemctl is-active --quiet xcmax-dr-primary-tunnel.service
ss -H -lnt | awk '{print $4}' | grep -qE '127\.0\.0\.1:25433$'

OPS_DR_RUNTIME_MODE=active-peer \
OPS_DR_APP_PG_PORT=25433 \
OPS_DR_PAYMENT_PG_PORT=25432 \
OPS_DR_REDIS_PORT=26379 \
OPS_DR_PAYMENT_API_PORT=28080 \
OPS_DR_PG_PRESERVE_CREDENTIALS=1 \
  "$PREPARE_RUNTIME"
"$PREPARE_EDGE" --active-peer

install -d -m 0700 /var/lib/xcmax-dr
date -u +%s >/var/lib/xcmax-dr/active_peer_enabled_at
echo "DR 活动应用节点已就绪：读流量本地、写与有状态文件流量固定回单主"
