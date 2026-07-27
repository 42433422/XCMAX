#!/usr/bin/env bash
# Install a deterministic Nginx edge on DR using the backed-up xiu-ci.com
# certificate. Active-peer mode serves safe reads locally and pins mutations,
# file-backed routes and non-replicated services to the single primary.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

MODE="drill"
case "${1:-}" in
  ""|--drill) MODE="drill" ;;
  --active-peer) MODE="active-peer" ;;
  --promoted) MODE="promoted" ;;
  *) echo "用法: $0 [--drill|--active-peer|--promoted]" >&2; exit 2 ;;
esac

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
RESTORE_CONFIG="${OPS_DR_RESTORE_CONFIG:-$DR_ROOT/restore-config}"
SOURCE_ROOT="${OPS_DR_SOURCE_ROOT:-$DR_ROOT/runtime/source/成都修茈科技有限公司}"
CERT_SOURCE="$RESTORE_CONFIG/etc/nginx/ssl"
NGINX_CONF="/etc/nginx/sites-available/xcmax-dr.conf"
PRIMARY_ROUTES_CONF="/etc/nginx/snippets/xcmax-dr-primary-routes.conf"
FHD_PORT="${OPS_DR_FHD_PORT:-15100}"
MODSTORE_PORT="${OPS_DR_MODSTORE_PORT:-19999}"
PRIMARY_HTTPS_PORT="${OPS_DR_PRIMARY_HTTPS_PORT:-24443}"
PRIMARY_FHD_PORT="${OPS_DR_PRIMARY_FHD_PORT:-25100}"
PRIMARY_MODSTORE_PORT="${OPS_DR_PRIMARY_MODSTORE_PORT:-29999}"

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
stateful_fhd_port="$FHD_PORT"
stateful_modstore_port="$MODSTORE_PORT"
if [[ "$MODE" == "active-peer" ]]; then
  stateful_fhd_port="$PRIMARY_FHD_PORT"
  stateful_modstore_port="$PRIMARY_MODSTORE_PORT"
  cat >"$PRIMARY_ROUTES_CONF" <<EOF
# Services which are not installed on the DR node remain pinned to production.
location ^~ /api/kellai/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /kellai/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /kellai-api/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /downloads/kellai/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /sandbox/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /api/xcmax/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /api/realtime/ { include proxy_params; proxy_http_version 1.1; proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600s; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /api/workbench/voice/ { include proxy_params; proxy_http_version 1.1; proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600s; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /api/asr/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
location ^~ /uploads/ { include proxy_params; proxy_ssl_server_name on; proxy_ssl_name xiu-ci.com; proxy_pass https://127.0.0.1:${PRIMARY_HTTPS_PORT}; }
EOF
else
  : >"$PRIMARY_ROUTES_CONF"
fi
chmod 0644 "$PRIMARY_ROUTES_CONF"

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
    add_header X-XCMAX-Node "dr-$MODE" always;
    $mutation_guard

    location = /__dr/health {
        default_type application/json;
        return 200 '{"status":"ok","node":"43.138.211.142","mode":"$MODE"}';
    }

    include $PRIMARY_ROUTES_CONF;

    location = /fhd-api/ws/im {
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_pass http://127.0.0.1:${FHD_PORT}/ws/im;
    }

    location = /ws/im {
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_pass http://127.0.0.1:${FHD_PORT}/ws/im;
    }

    location /fhd-api/ {
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        set \$xcmax_fhd_upstream http://127.0.0.1:${FHD_PORT};
        if (\$request_method !~ ^(GET|HEAD|OPTIONS)$) {
            set \$xcmax_fhd_upstream http://127.0.0.1:${stateful_fhd_port};
        }
        if (\$uri ~* /(upload|download|file|asset|attachment|avatar|media|export)(/|s|$)) {
            set \$xcmax_fhd_upstream http://127.0.0.1:${stateful_fhd_port};
        }
        rewrite ^/fhd-api/(.*)$ /\$1 break;
        proxy_pass \$xcmax_fhd_upstream;
    }

    location /api/ {
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        set \$xcmax_modstore_upstream http://127.0.0.1:${MODSTORE_PORT};
        if (\$request_method !~ ^(GET|HEAD|OPTIONS)$) {
            set \$xcmax_modstore_upstream http://127.0.0.1:${stateful_modstore_port};
        }
        if (\$uri ~* /(upload|download|file|asset|attachment|avatar|media|export)(/|s|$)) {
            set \$xcmax_modstore_upstream http://127.0.0.1:${stateful_modstore_port};
        }
        proxy_pass \$xcmax_modstore_upstream;
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
