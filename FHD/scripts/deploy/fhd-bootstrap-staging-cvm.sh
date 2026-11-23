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
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/verify_release_identity.sh
. "$SCRIPT_DIR/lib/verify_release_identity.sh"

STABLE_MANIFEST="${FHD_STABLE_MANIFEST:-/var/www/update/releases/stable/server/fhd-manifest.json}"
STAGING_DIR="${FHD_STAGING_RELEASE_DIR:-/var/www/update/releases/staging/server}"
DEPLOY_ROOT="${FHD_STAGING_DEPLOY_ROOT:-/opt/fhd-staging}"
ENV_FILE="${FHD_STAGING_ENV_FILE:-/root/fhd-staging.env}"
PROD_ENV="${FHD_PROD_ENV_FILE:-/root/fhd-full.env}"
API_PORT="${FHD_STAGING_API_PORT:-5101}"
SERVICE_NAME="${FHD_STAGING_SERVICE_NAME:-fhd-staging.service}"
DATA_ROOT="${FHD_STAGING_DATA_ROOT:-/var/lib/xcagi-staging}"
SERVICE_PYTHON="${FHD_STAGING_PYTHON:-/usr/bin/python3}"

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
TMP="$(mktemp -d /tmp/fhd-staging-seed.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
MANIFEST_SNAPSHOT="$TMP/source-manifest.json"
cp "$STABLE_MANIFEST" "$MANIFEST_SNAPSHOT"
ARTIFACT="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["artifact"])' "$MANIFEST_SNAPSHOT")"
GIT_SHA="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("git_sha",""))' "$MANIFEST_SNAPSHOT")"
SHA256="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sha256"])' "$MANIFEST_SNAPSHOT")"
ARCHIVE_VERIFY_SHA256="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("archive_verifier_sha256",""))' "$MANIFEST_SNAPSHOT")"
ADMIN_SHA256="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("admin_console_sha256",""))' "$MANIFEST_SNAPSHOT")"
TARBALL="$(dirname "$STABLE_MANIFEST")/$ARTIFACT"
TRUSTED_ARCHIVE_VERIFY="${FHD_TRUSTED_ARCHIVE_VERIFY:-/opt/fhd-full/scripts/deploy/lib/verify_release_archive.py}"
[[ "$ARTIFACT" != */* && -f "$TARBALL" && "$GIT_SHA" =~ ^[0-9a-f]{40,64}$ \
  && "$SHA256" =~ ^[0-9a-f]{64}$ && "$ADMIN_SHA256" =~ ^[0-9a-f]{64}$ \
  && "$ARCHIVE_VERIFY_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "[err] stable release identity or artifact is incomplete" >&2; exit 1;
}
ACTUAL_SHA256="$(python3 - "$TARBALL" <<'PY'
import hashlib, sys
with open(sys.argv[1], "rb") as stream:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
print(digest.hexdigest())
PY
)"
ACTUAL_VERIFY_SHA256="$(python3 - "$TRUSTED_ARCHIVE_VERIFY" <<'PY'
import hashlib, sys
with open(sys.argv[1], "rb") as stream:
    print(hashlib.sha256(stream.read()).hexdigest())
PY
)"
[[ "$ACTUAL_SHA256" == "$SHA256" && "$ACTUAL_VERIFY_SHA256" == "$ARCHIVE_VERIFY_SHA256" ]] || {
  echo "[err] stable artifact or trusted candidate verifier SHA256 mismatch" >&2; exit 1;
}
python3 "$TRUSTED_ARCHIVE_VERIFY" --archive "$TARBALL"
BUNDLED_ARCHIVE_VERIFY_SHA256="$(python3 - "$TARBALL" <<'PY'
import hashlib, tarfile, sys
with tarfile.open(sys.argv[1], "r:gz") as archive:
    matches = [member for member in archive.getmembers()
               if member.name.removeprefix("./") == "scripts/deploy/lib/verify_release_archive.py"]
    if len(matches) != 1 or not matches[0].isfile():
        raise SystemExit("release archive verifier member is missing or ambiguous")
    source = archive.extractfile(matches[0])
    if source is None:
        raise SystemExit("release archive verifier member cannot be read")
    print(hashlib.sha256(source.read()).hexdigest())
PY
)"
[[ "$BUNDLED_ARCHIVE_VERIFY_SHA256" == "$ARCHIVE_VERIFY_SHA256" ]] || {
  echo "[err] bundled verifier differs from exact candidate source" >&2; exit 1;
}
[[ -x "$SERVICE_PYTHON" ]] || { echo "[err] staging service Python is missing" >&2; exit 1; }
[[ "$(realpath -m "$ENV_FILE")" != "$(realpath -m "$PROD_ENV")" ]] || {
  echo "[err] staging cannot overwrite the production env file" >&2; exit 1;
}
if [[ -f "$DEPLOY_ROOT/.deploy-git-sha" && "$(cat "$DEPLOY_ROOT/.deploy-git-sha")" != "$GIT_SHA" ]]; then
  echo "[err] staging already has a different release; use fhd-apply-release.sh for verified upgrade/rollback" >&2
  exit 1
fi
python3 "$SCRIPT_DIR/lib/staging_environment.py" "$PROD_ENV" "$TMP/staging.env" \
  "$DEPLOY_ROOT" "$API_PORT" "$DATA_ROOT"

echo "[1/7] ensure staging database"
PW="$(docker exec modstore_deploy-postgres-1 printenv POSTGRES_PASSWORD)"
if ! docker exec modstore_deploy-postgres-1 psql -U xcagi -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='xcagi_staging'" | grep -q 1; then
  docker exec -e PGPASSWORD="$PW" modstore_deploy-postgres-1 \
    psql -X -v ON_ERROR_STOP=1 -U modstore -d postgres -c "CREATE DATABASE xcagi_staging OWNER xcagi;"
fi
TABLES="$(docker exec modstore_deploy-postgres-1 psql -U xcagi -d xcagi_staging -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
EXPECTED_TABLES="$(docker exec modstore_deploy-postgres-1 psql -U xcagi -d xcagi -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
if [[ "${TABLES// /}" == 0 ]]; then
  echo "[info] cloning schema from xcagi -> xcagi_staging (tables=$TABLES)"
  docker exec -e PGPASSWORD="$PW" modstore_deploy-postgres-1 \
    pg_dump -U modstore -d xcagi --schema-only --no-owner --no-privileges \
    > "$TMP/xcagi_schema.sql"
  # The migration revision is schema metadata; no customer/business rows are cloned.
  docker exec -e PGPASSWORD="$PW" modstore_deploy-postgres-1 \
    pg_dump -U modstore -d xcagi --data-only --table=public.alembic_version --no-owner --no-privileges \
    >> "$TMP/xcagi_schema.sql"
  docker exec -i modstore_deploy-postgres-1 \
    psql -X --single-transaction -v ON_ERROR_STOP=1 -U xcagi -d xcagi_staging \
    < "$TMP/xcagi_schema.sql"
  TABLES="$(docker exec modstore_deploy-postgres-1 psql -U xcagi -d xcagi_staging -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
  echo "[ok] staging tables=$TABLES"
fi
[[ "${TABLES// /}" =~ ^[0-9]+$ && "${EXPECTED_TABLES// /}" =~ ^[0-9]+$ \
  && "${EXPECTED_TABLES// /}" -gt 0 && "${TABLES// /}" -ge "${EXPECTED_TABLES// /}" ]] || {
  echo "[err] staging schema is incomplete; bootstrap stopped" >&2; exit 1;
}

echo "[2/7] write $ENV_FILE"
install -m 600 "$TMP/staging.env" "$ENV_FILE"

echo "[3/7] seed $DEPLOY_ROOT from stable tarball"
# Stable artifact and exact-source verifier were checked before earlier staging writes.

install -d -m 755 "$DEPLOY_ROOT"
tar -xzf "$TARBALL" -C "$TMP"
if systemctl is-active --quiet "$SERVICE_NAME"; then
  systemctl stop "$SERVICE_NAME"
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "[err] staging service did not stop before seeding" >&2; exit 1;
  fi
fi
python3 "$TMP/scripts/deploy/lib/mod_tree_guard.py" apply \
  --source "$TMP/mods" --target "$DEPLOY_ROOT/mods" --state "$TMP/mods-state" \
  --previous-archive "$DEPLOY_ROOT/.deploy-last.tar.gz" --deploy-root "$DEPLOY_ROOT"
for item in .build-identity.json app XCAGI alembic alembic.ini config xcagi_common resources packages templates requirements-langgraph-runtime.txt requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$TMP/$item" ]]; then
    rsync -a --delete "$TMP/$item" "$DEPLOY_ROOT/"
  fi
done
mkdir -p "$DEPLOY_ROOT/scripts"
rsync -a --delete "$TMP/scripts/" "$DEPLOY_ROOT/scripts/"
if [[ -d "$TMP/docker" ]]; then
  mkdir -p "$DEPLOY_ROOT/docker"
  rsync -a "$TMP/docker/" "$DEPLOY_ROOT/docker/"
fi
printf '%s\n' "$SHA256" > "$DEPLOY_ROOT/.deploy-sha256"
printf '%s\n' "$GIT_SHA" > "$DEPLOY_ROOT/.deploy-git-sha"
printf '%s\n' "$ADMIN_SHA256" > "$DEPLOY_ROOT/.deploy-admin-console-sha256"
cp -f "$TARBALL" "$DEPLOY_ROOT/.deploy-last.tar.gz"

echo "[4/7] validate bundled runtime"
PYTHONPATH="$DEPLOY_ROOT" "$SERVICE_PYTHON" - <<'PY'
from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources
assert_vendored_sources()
PY

echo "[5/7] systemd $SERVICE_NAME"
install -d -m 700 "$DATA_ROOT" "$DATA_ROOT/autonomy" "$DATA_ROOT/uploads"
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
ExecStart=${SERVICE_PYTHON} ${DEPLOY_ROOT}/XCAGI/run.py
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
sed -i "s/127\.0\.0\.1:5101/127.0.0.1:${API_PORT}/g" /etc/nginx/conf.d/xiu-ci-fhd-staging.conf

python3 - "$API_PORT" <<'PY'
import re
import sys
from pathlib import Path
p = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
text = p.read_text()
port = str(int(sys.argv[1]))
if re.search(r"location\s+(?:=|\^~)\s+/fhd-staging-api/", text):
    text, count = re.subn(
        r"(location\s+(?:=|\^~)\s+/fhd-staging-api/[^{}]*\{[^{}]*proxy_pass http://127\.0\.0\.1:)\d+",
        lambda match: match[1] + port, text,
    )
    if count != 2:
        raise SystemExit("existing staging path proxy is incomplete")
    p.write_text(text)
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
    p.write_text(text.replace(marker, snippet.replace(":5101/", ":" + port + "/") + marker, 1))
    print("injected /fhd-staging-api/ path proxy")
PY
nginx -t
systemctl reload nginx

echo "[7/7] wait local health on :$API_PORT"
for i in $(seq 1 60); do
  if verify_release_health_identity "http://127.0.0.1:${API_PORT}/api/health?lite=true" \
      "$GIT_SHA" "" "$SHA256" "$ADMIN_SHA256"; then
    echo "[ok] local release identity verified attempt=$i"
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

PUBLIC_HEALTH="$(curl --noproxy '*' -fsS --max-time 8 --resolve xiu-ci.com:443:127.0.0.1 \
  'https://xiu-ci.com/fhd-staging-api/api/health?lite=true')"
verify_release_identity_payload "$PUBLIC_HEALTH" "$GIT_SHA" "" "$SHA256" "$ADMIN_SHA256"

# Publish only after both service and nginx identify the verified seed release.
install -d -m 755 "$STAGING_DIR"
cp "$TARBALL" "$STAGING_DIR/.${ARTIFACT}.tmp"
mv "$STAGING_DIR/.${ARTIFACT}.tmp" "$STAGING_DIR/$ARTIFACT"
python3 - "$MANIFEST_SNAPSHOT" "$STAGING_DIR/fhd-manifest.json" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path
source, target = map(Path, sys.argv[1:])
manifest = json.loads(source.read_text())
manifest["channel"] = "staging"
with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
    json.dump(manifest, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
os.replace(stream.name, target)
PY
chmod 644 "$STAGING_DIR/$ARTIFACT" "$STAGING_DIR/fhd-manifest.json"
echo "[ok] staging bootstrap complete"
echo "     env=$ENV_FILE"
echo "     root=$DEPLOY_ROOT"
echo "     service=$SERVICE_NAME port=$API_PORT"
echo "     health_path=https://xiu-ci.com/fhd-staging-api/api/health"
echo "     health_host=https://staging.xiu-ci.com/fhd-api/api/health (needs DNS A -> this CVM)"
