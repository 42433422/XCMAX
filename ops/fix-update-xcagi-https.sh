#!/usr/bin/env bash
# [可选/已弃用] 仅当恢复阿里云 update.xcagi.com 子域时使用。
# 当前 OTA SSOT：https://xiu-ci.com/releases/stable/（腾讯云 DNSPod，不依赖阿里云）
#
# 用法：
#   bash ops/fix-update-xcagi-https.sh
#   FHD_PUSH_HOST=119.27.178.147 bash ops/fix-update-xcagi-https.sh --remote
set -euo pipefail

HOST="${FHD_PUSH_HOST:-119.27.178.147}"
SSH_KEY="${FHD_PUSH_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE="${FHD_PUSH_USER:-root}@${HOST}"
SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no)

run_remote() {
  "${SSH[@]}" "$REMOTE" bash -s
}

remote_body() {
  cat <<'REMOTE'
set -euo pipefail
DOMAIN=update.xcagi.com
WEBROOT=/var/www/update
ACME=/root/.acme.sh/acme.sh
NGINX_CONF=/etc/nginx/conf.d/update.xcagi.com.conf

echo "[1/4] DNS 检查（须解析到本机公网 IP）"
RESOLVED=$(dig +short "$DOMAIN" A | head -1 || true)
LOCAL_IP=$(curl -s --max-time 5 https://api.ipify.org || curl -s --max-time 5 ifconfig.me || true)
echo "  resolved=$RESOLVED local_public=$LOCAL_IP"
if [[ -z "$RESOLVED" || "$RESOLVED" == "170.33.12.185" ]]; then
  echo "[err] DNS 仍指向欠费停放页或未配置。请在阿里云 DNS 将 $DOMAIN A 记录改为 119.27.178.147" >&2
  exit 2
fi

echo "[2/4] 申请 Let's Encrypt 证书（webroot）"
mkdir -p "$WEBROOT/.well-known/acme-challenge"
"$ACME" --issue -d "$DOMAIN" -w "$WEBROOT" --force || {
  echo "[err] acme.sh 签发失败；确认 80 端口可从公网访问且 DNS 已生效" >&2
  exit 3
}

CERT_DIR="/root/.acme.sh/${DOMAIN}_ecc"
if [[ ! -f "$CERT_DIR/fullchain.cer" ]]; then
  CERT_DIR="/root/.acme.sh/${DOMAIN}"
fi
install -d -m 0755 /etc/nginx/ssl
"$ACME" --install-cert -d "$DOMAIN" \
  --key-file /etc/nginx/ssl/update.xcagi.com.key \
  --fullchain-file /etc/nginx/ssl/update.xcagi.com.crt \
  --reloadcmd "nginx -t && systemctl reload nginx"

echo "[3/4] 写入 HTTPS server 块"
cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
if ! grep -q 'listen 443' "$NGINX_CONF"; then
  cat >> "$NGINX_CONF" <<'HTTPS'

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name update.xcagi.com;

    ssl_certificate /etc/nginx/ssl/update.xcagi.com.crt;
    ssl_certificate_key /etc/nginx/ssl/update.xcagi.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    root /var/www/update;
    autoindex off;

    location /releases/ {
        add_header Cache-Control "public, max-age=60";
        try_files $uri =404;
    }

    location ~* /latest(?:-mac)?\.yml$ {
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        try_files $uri =404;
    }

    location ~* \.(exe|dmg|pkg|zip|blockmap)$ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }
}
HTTPS
fi

echo "[4/4] nginx 校验并重载"
nginx -t
systemctl reload nginx
curl -fsSI "https://${DOMAIN}/releases/stable/enterprise/latest.yml" | head -5
echo "[ok] https://${DOMAIN} 已可用"
REMOTE
}

if [[ "${1:-}" == "--remote" ]]; then
  run_remote <<< "$(remote_body)"
else
  remote_body
fi
