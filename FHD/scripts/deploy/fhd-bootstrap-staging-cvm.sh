#!/usr/bin/env bash
# Idempotent CVM bootstrap for FHD staging channel (same host as production).
#
# Creates:
#   /root/fhd-staging.env
#   /opt/fhd-staging  (seeded from latest stable tarball)
#   /var/www/update/releases/staging/server/fhd-manifest.json
#   fhd-staging.service on XCAGI_API_PORT=5101
#   nginx: staging.xiu-ci.com + path https://xiu-ci.com/fhd-staging-api/
#
# Run on CVM as root:
#   bash FHD/scripts/deploy/fhd-bootstrap-staging-cvm.sh
set -euo pipefail

umask 077

STABLE_MANIFEST="${FHD_STABLE_MANIFEST:-/var/www/update/releases/stable/server/fhd-manifest.json}"
STAGING_DIR="${FHD_STAGING_RELEASE_DIR:-/var/www/update/releases/staging/server}"
DEPLOY_ROOT="${FHD_STAGING_DEPLOY_ROOT:-/opt/fhd-staging}"
ENV_FILE="${FHD_STAGING_ENV_FILE:-/root/fhd-staging.env}"
PROD_ENV="${FHD_PROD_ENV_FILE:-/root/fhd-full.env}"
API_PORT="${FHD_STAGING_API_PORT:-5101}"
SERVICE_NAME="${FHD_STAGING_SERVICE_NAME:-fhd-staging.service}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[err] must run as root on CVM" >&2
  exit 1
fi
if [[ ! -f "$PROD_ENV" ]]; then
  echo "[err] missing prod env: $PROD_ENV" >&2
  exit 1
fi
if [[ ! -f "$STABLE_MANIFEST" ]]; then
  echo "[err] missing stable manifest: $STABLE_MANIFEST" >&2
  exit 1
fi

echo "[1/7] ensure staging database"
PW="$(docker exec modstore_deploy-postgres-1 printenv POSTGRES_PASSWORD)"
if ! docker exec modstore_deploy-postgres-1 psql -U xcagi -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='xcagi_staging'" | grep -q 1; then
  docker exec -e PGPASSWORD="$PW" modstore_deploy-postgres-1 \
    psql -U modstore -d postgres -c "CREATE DATABASE xcagi_staging OWNER xcagi;"
fi
TABLES="$(docker exec modstore_deploy-postgres-1 psql -U xcagi -d xcagi_staging -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [[ "${TABLES// /}" -lt 20 ]]; then
  echo "[info] cloning schema from xcagi -> xcagi_staging (tables=$TABLES)"
  docker exec -e PGPASSWORD="$PW" modstore_deploy-postgres-1 \
    pg_dump -U modstore -d xcagi --schema-only --no-owner --no-privileges \
    > /tmp/xcagi_schema.sql
  sed -i '/^\\restrict /d;/^\\unrestrict /d' /tmp/xcagi_schema.sql
  docker exec -i modstore_deploy-postgres-1 \
    psql -U xcagi -d xcagi_staging < /tmp/xcagi_schema.sql \
    >/tmp/xcagi_staging_restore.log 2>&1 || true
  TABLES="$(docker exec modstore_deploy-postgres-1 psql -U xcagi -d xcagi_staging -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  echo "[ok] staging tables=$TABLES"
fi

echo "[2/7] write $ENV_FILE"
python3 - <<PY
from pathlib import Path
import re

src = Path("$PROD_ENV").read_text().splitlines()
out = []
replacements = {
    "XCAGI_API_PORT": "$API_PORT",
    "XCAGI_AUTONOMY_DATA_DIR": "/var/lib/xcagi/autonomy-staging",
    "XCAGI_MODS_ROOT": "$DEPLOY_ROOT/mods",
    "WORKSPACE_ROOT": "$DEPLOY_ROOT",
    "XCMAX_MONOREPO_ROOT": "$DEPLOY_ROOT",
}
for line in src:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k, v = line.split("=", 1)
    k = k.strip()
    if k == "DATABASE_URL":
        v2 = re.sub(r"/xcagi(\\?|$)", r"/xcagi_staging\\1", v)
        out.append(f"DATABASE_URL={v2}")
        continue
    if k in replacements:
        out.append(f"{k}={replacements[k]}")
        continue
    out.append(line)

def ensure(key: str, value: str) -> None:
    if not any(l.startswith(key + "=") for l in out):
        out.append(f"{key}={value}")

for neuro in (
    "XCAGI_NEURO_BUS_DEDUP",
    "XCAGI_NEURO_BUS_CIRCUIT",
    "XCAGI_NEURO_BUS_RATE_LIMIT",
    "XCAGI_NEURO_BUS_TRACE",
    "XCAGI_NEURO_BUS_LIFELINE",
    "XCAGI_NEURO_BUS_DLQ_AUTO",
    "XCAGI_NEURO_BUS_SLA_LOG",
):
    ensure(neuro, "1")
ensure("MODSTORE_DEPLOY_TIER", "staging")
ensure("FHD_DEPLOY_TIER", "staging")
Path("$ENV_FILE").write_text("\n".join(out) + "\n")
text = Path("$ENV_FILE").read_text()
assert "XCAGI_API_PORT=$API_PORT" in text, text
assert "/xcagi_staging" in text
assert "XCAGI_NEURO_BUS_DEDUP=1" in text
print("env_ok", Path("$ENV_FILE").stat().st_size)
PY
chmod 600 "$ENV_FILE"

echo "[3/7] seed $DEPLOY_ROOT from stable tarball"
ARTIFACT="$(python3 -c "import json;print(json.load(open('$STABLE_MANIFEST'))['artifact'])")"
GIT_SHA="$(python3 -c "import json;print(json.load(open('$STABLE_MANIFEST')).get('git_sha',''))")"
SHA256="$(python3 -c "import json;print(json.load(open('$STABLE_MANIFEST'))['sha256'])")"
TARBALL="$(dirname "$STABLE_MANIFEST")/$ARTIFACT"
[[ -f "$TARBALL" ]] || { echo "[err] missing tarball $TARBALL" >&2; exit 1; }

install -d -m 755 "$DEPLOY_ROOT"
TMP="$(mktemp -d /tmp/fhd-staging-seed.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
tar -xzf "$TARBALL" -C "$TMP"
for item in .build-identity.json app XCAGI alembic alembic.ini config mods xcagi_common resources requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$TMP/$item" ]]; then
    rsync -a --delete "$TMP/$item" "$DEPLOY_ROOT/"
  fi
done
if [[ -d "$TMP/scripts/deploy" ]]; then
  mkdir -p "$DEPLOY_ROOT/scripts"
  rsync -a --delete "$TMP/scripts/deploy/" "$DEPLOY_ROOT/scripts/deploy/"
fi
if [[ -d "$TMP/docker" ]]; then
  mkdir -p "$DEPLOY_ROOT/docker"
  rsync -a "$TMP/docker/" "$DEPLOY_ROOT/docker/"
fi
if [[ ! -e "$DEPLOY_ROOT/.venv" && -x /opt/fhd-full/.venv/bin/python ]]; then
  ln -s /opt/fhd-full/.venv "$DEPLOY_ROOT/.venv"
fi
printf '%s\n' "$SHA256" > "$DEPLOY_ROOT/.deploy-sha256"
printf '%s\n' "$GIT_SHA" > "$DEPLOY_ROOT/.deploy-git-sha"
cp -f "$TARBALL" "$DEPLOY_ROOT/.deploy-last.tar.gz"

echo "[4/7] staging manifest"
install -d -m 755 "$STAGING_DIR"
if [[ ! -f "$STAGING_DIR/$ARTIFACT" ]]; then
  ln "$TARBALL" "$STAGING_DIR/$ARTIFACT" 2>/dev/null || cp -f "$TARBALL" "$STAGING_DIR/$ARTIFACT"
fi
python3 - <<PY
import json
from pathlib import Path
m = json.loads(Path("$STABLE_MANIFEST").read_text())
m["channel"] = "staging"
Path("$STAGING_DIR/fhd-manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
print("manifest", m.get("artifact"), m.get("git_sha"), m.get("channel"))
PY

echo "[5/7] systemd $SERVICE_NAME"
install -d -m 700 /var/lib/xcagi/autonomy-staging
cat > "/etc/systemd/system/${SERVICE_NAME}" <<UNIT
[Unit]
Description=XCAGI staging API (PostgreSQL)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${DEPLOY_ROOT}/XCAGI
Environment=PYTHONPATH=${DEPLOY_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/python3 ${DEPLOY_ROOT}/XCAGI/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "[6/7] nginx staging vhost + path proxy"
cat > /etc/nginx/conf.d/xiu-ci-fhd-staging.conf <<'NGINX'
server {
    listen 80;
    listen 443 ssl http2;
    server_name staging.xiu-ci.com;

    ssl_certificate     /etc/nginx/ssl/xiu-ci.com_bundle.crt;
    ssl_certificate_key /etc/nginx/ssl/xiu-ci.com.key;

    location = /fhd-api/api/health {
        proxy_pass http://127.0.0.1:5101/api/health;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location ^~ /fhd-api/ {
        proxy_pass http://127.0.0.1:5101/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
    }
    location / {
        return 302 /fhd-api/api/health;
    }
}
NGINX

python3 - <<'PY'
from pathlib import Path
p = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
text = p.read_text()
if "fhd-staging-api" in text:
    print("path proxy already present")
else:
    marker = "    location ^~ /fhd-api/ {"
    snippet = """    # FHD staging API (path-based; no staging DNS required)
    location = /fhd-staging-api/api/health {
        proxy_pass http://127.0.0.1:5101/api/health;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location ^~ /fhd-staging-api/ {
        proxy_pass http://127.0.0.1:5101/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
    }

"""
    if marker not in text:
        raise SystemExit("nginx marker for /fhd-api/ not found")
    p.write_text(text.replace(marker, snippet + marker, 1))
    print("injected /fhd-staging-api/ path proxy")
PY
nginx -t
systemctl reload nginx

echo "[7/7] wait local health on :$API_PORT"
for i in $(seq 1 60); do
  if curl -sf --noproxy '*' --max-time 3 "http://127.0.0.1:${API_PORT}/api/health?lite=true" >/tmp/fhd-staging-health.json; then
    echo "[ok] local health attempt=$i"
    head -c 240 /tmp/fhd-staging-health.json
    echo
    break
  fi
  sleep 3
  if [[ "$i" -eq 60 ]]; then
    echo "[err] staging health failed" >&2
    systemctl status "$SERVICE_NAME" --no-pager | head -50 >&2 || true
    journalctl -u "$SERVICE_NAME" -n 100 --no-pager >&2 || true
    exit 1
  fi
done

curl -sfk --max-time 5 -H 'Host: xiu-ci.com' \
  "https://127.0.0.1/fhd-staging-api/api/health" | head -c 200 || true
echo
echo "[ok] staging bootstrap complete"
echo "     env=$ENV_FILE"
echo "     root=$DEPLOY_ROOT"
echo "     service=$SERVICE_NAME port=$API_PORT"
echo "     health_path=https://xiu-ci.com/fhd-staging-api/api/health"
echo "     health_host=https://staging.xiu-ci.com/fhd-api/api/health (needs DNS A -> this CVM)"
