#!/usr/bin/env bash
# Install a tunnel-only account on the production node. The account can only
# forward the exact loopback ports needed by the active DR application peer.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

PUBLIC_KEY_FILE=""
while (($#)); do
  case "$1" in
    --public-key-file)
      PUBLIC_KEY_FILE="${2:-}"
      shift 2
      ;;
    *)
      echo "用法: $0 --public-key-file <DR 公钥文件>" >&2
      exit 2
      ;;
  esac
done

[[ -s "$PUBLIC_KEY_FILE" ]] || {
  echo "缺少 DR 隧道公钥文件" >&2
  exit 1
}

PEER_USER="${OPS_DR_PEER_USER:-xcmaxdrpeer}"
DR_IP="${OPS_DR_SECONDARY_IP:-43.138.211.142}"
PEER_HOME="${OPS_DR_PEER_HOME:-/var/lib/xcmax-dr-peer}"
SSHD_DROPIN="/etc/ssh/sshd_config.d/90-xcmax-dr-peer.conf"

read -r key_type key_body key_comment <"$PUBLIC_KEY_FILE"
[[ "$key_type" == "ssh-ed25519" && -n "$key_body" ]] || {
  echo "DR 隧道公钥必须是 ssh-ed25519" >&2
  exit 1
}
[[ "$key_body" =~ ^[A-Za-z0-9+/=]+$ ]] || {
  echo "DR 隧道公钥格式非法" >&2
  exit 1
}

if ! id "$PEER_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$PEER_HOME" \
    --shell /usr/sbin/nologin "$PEER_USER"
fi

install -d -o "$PEER_USER" -g "$PEER_USER" -m 0700 "$PEER_HOME/.ssh"
authorized_key="$PEER_HOME/.ssh/authorized_keys"
key_options="$(
  printf '%s' \
    "from=\"$DR_IP\",command=\"/usr/bin/sleep infinity\",restrict,port-forwarding" \
    ",permitopen=\"127.0.0.1:443\"" \
    ",permitopen=\"127.0.0.1:5100\"" \
    ",permitopen=\"127.0.0.1:5432\"" \
    ",permitopen=\"127.0.0.1:5433\"" \
    ",permitopen=\"127.0.0.1:6379\"" \
    ",permitopen=\"127.0.0.1:8080\"" \
    ",permitopen=\"127.0.0.1:9999\""
)"
printf '%s %s %s %s\n' \
  "$key_options" "$key_type" "$key_body" "${key_comment:-xcmax-dr-peer}" \
  >"$authorized_key"
chown "$PEER_USER:$PEER_USER" "$authorized_key"
chmod 0600 "$authorized_key"

install -d -m 0755 /etc/ssh/sshd_config.d
cat >"$SSHD_DROPIN" <<EOF
Match User $PEER_USER
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    AllowTcpForwarding local
    GatewayPorts no
EOF
chmod 0644 "$SSHD_DROPIN"

sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd
echo "生产隧道账号已就绪: user=$PEER_USER source=$DR_IP"
