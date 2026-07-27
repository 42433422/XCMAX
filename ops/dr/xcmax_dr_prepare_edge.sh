#!/usr/bin/env bash
# Install a minimal, deterministic Nginx edge on DR using the backed-up
# xiu-ci.com certificate. Drill mode blocks mutating HTTP methods to avoid a
# split-brain write while production remains active.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

MODE="drill"
case "${1:-}" in
  ""|--drill) MODE="drill" ;;
  --promoted) MODE="promoted" ;;
  *) echo "用法: $0 [--drill|--promoted]" >&2; exit 2 ;;
esac

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
RESTORE_CONFIG="${OPS_DR_RESTORE_CONFIG:-$DR_ROOT/restore-config}"
SOURCE_ROOT="${OPS_DR_SOURCE_ROOT:-$DR_ROOT/runtime/source/成都修茈科技有限公司}"
CERT_SOURCE="$RESTORE_CONFIG/etc/nginx/ssl"
NGINX_CONF="/etc/nginx/sites-available/xcmax-dr.conf"
FHD_PORT="${OPS_DR_FHD_PORT:-15100}"
MODSTORE_PORT="${OPS_DR_MODSTORE_PORT:-19999}"

[[ -f "$CERT_SOURCE/xiu-ci.com.crt" && -f "$CERT_SOURCE/xiu-ci.com.key" ]] || {
  echo "缺少恢复的 xiu-ci.com 证书或私钥" >&2
  exit 1
}
[[ -f "$SOURCE_ROOT/index.html" ]] || {
  echo "缺少官网静态入口: $SOURCE_ROOT/index.html" >&2
  exit 1
}
[[ -f "$SOURCE_ROOT/MODstore_deploy/market/dist/index.html" ]] || {
  echo "缺少 MODstore 前端构建产物" >&2
  exit 1
}

if ! command -v nginx >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq nginx
fi

install -d -m 0755 /etc/nginx/ssl /var/lib/xcmax-dr
install -m 0644 "$CERT_SOURCE/xiu-ci.com.crt" /etc/nginx/ssl/xiu-ci.com.crt
install -m 0600 "$CERT_SOURCE/xiu-ci.com.key" /etc/nginx/ssl/xiu-ci.com.key
if [[ -f "$CERT_SOURCE/xiu-ci.com_bundle.crt" ]]; then
  install -m 0644 "$CERT_SOURCE/xiu-ci.com_bundle.crt" \
    /etc/nginx/ssl/xiu-ci.com_bundle.crt
fi

openssl x509 -checkend 604800 -noout -in /etc/nginx/ssl/xiu-ci.com.crt
openssl x509 -in /etc/nginx/ssl/xiu-ci.com.crt -noout -ext subjectAltName |
  grep -q 'DNS:xiu-ci.com'

usermod -a -G xcmaxapp www-data
chmod g+rX "$DR_ROOT" "$DR_ROOT/runtime" "$DR_ROOT/runtime/source" "$SOURCE_ROOT"
find "$SOURCE_ROOT" -type d -exec chmod g+rx {} +
find "$SOURCE_ROOT" -type f -exec chmod g+r {} +

mutation_guard=""
if [[ "$MODE" == "drill" ]]; then
  mutation_guard='if ($request_method !~ ^(GET|HEAD|OPTIONS)$) { return 503; }'
fi

cat >"$NGINX_CONF" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name xiu-ci.com www.xiu-ci.com;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name xiu-ci.com www.xiu-ci.com;

    ssl_certificate /etc/nginx/ssl/xiu-ci.com.crt;
    ssl_certificate_key /etc/nginx/ssl/xiu-ci.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header X-XCMAX-DR "43.138.211.142" always;
    add_header X-XCMAX-DR-Mode "$MODE" always;
    $mutation_guard

    location = /__dr/health {
        default_type application/json;
        return 200 '{"status":"ok","node":"43.138.211.142","mode":"$MODE"}';
    }

    location /fhd-api/ {
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:${FHD_PORT}/;
    }

    location /api/ {
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass http://127.0.0.1:${MODSTORE_PORT};
    }

    location /market/ {
        alias $SOURCE_ROOT/MODstore_deploy/market/dist/;
        try_files \$uri \$uri/ /market/index.html;
    }

    root $SOURCE_ROOT;
    index index.html;
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sfn "$NGINX_CONF" /etc/nginx/sites-enabled/xcmax-dr.conf
nginx -t
systemctl enable nginx >/dev/null
systemctl restart nginx
printf '%s\n' "$MODE" >/var/lib/xcmax-dr/edge_mode
curl -fsS -H 'Host: xiu-ci.com' http://127.0.0.1/__dr/health >/dev/null
curl -kfsS --resolve "xiu-ci.com:443:127.0.0.1" \
  https://xiu-ci.com/__dr/health >/dev/null
echo "DR Nginx/TLS 已就绪: mode=$MODE"
