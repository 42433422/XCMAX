#!/usr/bin/env bash
# 在专用容灾机上准备隔离运行环境。
# - standby: 使用恢复库，FHD 停机，MODstore 仅供本机验证；
# - active-peer: 应用常态在线，经受限隧道使用生产单主数据；
# - promoted: 使用已提升的本地数据库，供灾难接管。
# 所有模式都保持 scheduler/payment 单 Leader，除 promotion 外不启动。

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
RUNTIME="$DR_ROOT/runtime"
DATA="$DR_ROOT/runtime-data"
RESTORE_CONFIG="$DR_ROOT/restore-config"
FHD_ROOT="$RUNTIME/fhd"
MODSTORE_ROOT="$RUNTIME/source/成都修茈科技有限公司/MODstore_deploy"
PG_ENV="${OPS_DR_PG_ENV:-/etc/xcmax-dr-postgres.env}"
RUNTIME_MODE="${OPS_DR_RUNTIME_MODE:-standby}"
APP_PG_PORT="${OPS_DR_APP_PG_PORT:-${OPS_DR_PG_PORT:-5432}}"
PAYMENT_PG_PORT="${OPS_DR_PAYMENT_PG_PORT:-$APP_PG_PORT}"
REDIS_PORT="${OPS_DR_REDIS_PORT:-6379}"
PAYMENT_API_PORT="${OPS_DR_PAYMENT_API_PORT:-18080}"
PG_PRESERVE_CREDENTIALS="${OPS_DR_PG_PRESERVE_CREDENTIALS:-0}"
APP_USER="${OPS_DR_APP_USER:-xcmaxapp}"
PAYMENT_SHA256="${OPS_DR_PAYMENT_SHA256:-1df90282e5f1ca4d8192fe6b2f77fe54b6300e7c1ef3013b8bcb24a2bbde54b6}"

case "$RUNTIME_MODE" in
  standby|active-peer|promoted) ;;
  *)
    echo "OPS_DR_RUNTIME_MODE 必须是 standby、active-peer 或 promoted" >&2
    exit 2
    ;;
esac
if [[ "$RUNTIME_MODE" == "active-peer" && "$PG_PRESERVE_CREDENTIALS" != "1" ]]; then
  echo "active-peer 必须保留生产数据库凭据" >&2
  exit 2
fi

for required in \
  "$FHD_ROOT/XCAGI/run.py" \
  "$FHD_ROOT/.venv/bin/python" \
  "$MODSTORE_ROOT/modstore_server/app.py" \
  "$MODSTORE_ROOT/.venv/bin/python" \
  "$PG_ENV" \
  "$RESTORE_CONFIG/root/fhd-full.env" \
  "$RESTORE_CONFIG/etc/xcmax/modstore.env"; do
  [[ -e "$required" ]] || {
    echo "缺少温备运行文件: $required" >&2
    exit 1
  }
done

id "$APP_USER" >/dev/null 2>&1 ||
  useradd --system --home "$DATA" --shell /usr/sbin/nologin "$APP_USER"

install -d -o "$APP_USER" -g "$APP_USER" -m 0750 \
  "$DATA/fhd" "$DATA/fhd/autonomy" "$DATA/fhd/mods" "$DATA/fhd/uploads" \
  "$DATA/fhd/saved_analyses" \
  "$DATA/modstore" "$DATA/modstore/data" "$DATA/redis"
install -d -o root -g "$APP_USER" -m 0750 "$RUNTIME/payment"

payment_incoming="$DR_ROOT/incoming/runtime-artifacts/payment-service-1.0.0.jar"
payment_jar="$RUNTIME/payment/payment-service-1.0.0.jar"
if [[ -s "$payment_incoming" ]]; then
  actual_payment_sha="$(sha256sum "$payment_incoming" | awk '{print $1}')"
  [[ "$actual_payment_sha" == "$PAYMENT_SHA256" ]] || {
    echo "支付 JAR 哈希不匹配: $actual_payment_sha" >&2
    exit 1
  }
  install -o root -g "$APP_USER" -m 0640 "$payment_incoming" "$payment_jar"
fi

sync_tree() {
  local src="$1" dest="$2"
  [[ -d "$src" ]] || return 0
  rsync -a "$src/" "$dest/"
}

sync_tree "$RESTORE_CONFIG/var/lib/xcagi" "$DATA/fhd/xcagi-state"
sync_tree "$RESTORE_CONFIG/opt/fhd-full/mods" "$DATA/fhd/mods"
sync_tree "$RESTORE_CONFIG/opt/fhd-full/uploads" "$DATA/fhd/uploads"

modstore_data_src="$RESTORE_CONFIG/opt/xcmax/current/成都修茈科技有限公司/MODstore_deploy/modstore_server/data"
sync_tree "$modstore_data_src" "$DATA/modstore/data"

latest="$(readlink -f "$DR_ROOT/archive/latest" 2>/dev/null || true)"
if [[ -n "$latest" && -s "$latest/modstore_sqlite.db.gz" ]]; then
  sqlite_tmp="$(mktemp "$DATA/modstore/.modstore.db.XXXXXX")"
  gzip -dc "$latest/modstore_sqlite.db.gz" >"$sqlite_tmp"
  chown "$APP_USER:$APP_USER" "$sqlite_tmp"
  chmod 0600 "$sqlite_tmp"
  mv -f "$sqlite_tmp" "$DATA/modstore/modstore.db"
fi
chown -R "$APP_USER:$APP_USER" "$DATA"
# 发布包由受限传输账号落盘时顶层可能是 0700；业务用户只获代码读取/执行权。
chgrp -R "$APP_USER" "$FHD_ROOT" "$MODSTORE_ROOT"
chmod -R g+rX "$FHD_ROOT" "$MODSTORE_ROOT"
if [[ ! -e "$FHD_ROOT/XCAGI/saved_analyses" ]]; then
  ln -s "$DATA/fhd/saved_analyses" "$FHD_ROOT/XCAGI/saved_analyses"
fi

python3 - \
  "$PG_ENV" \
  "$RESTORE_CONFIG/root/fhd-full.env" /etc/xcmax-dr-fhd.env \
  "$RESTORE_CONFIG/etc/xcmax/modstore.env" /etc/xcmax-dr-modstore.env \
  "$DATA" "$RUNTIME" "$APP_PG_PORT" "$PAYMENT_PG_PORT" \
  "$REDIS_PORT" "$PAYMENT_API_PORT" "$PG_PRESERVE_CREDENTIALS" \
  "$RUNTIME_MODE" <<'PY'
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

pg_env, fhd_src, fhd_dst, mod_src, mod_dst, data_root, runtime_root = map(
    Path, sys.argv[1:8]
)
app_pg_port = int(sys.argv[8])
payment_pg_port = int(sys.argv[9])
redis_port = int(sys.argv[10])
payment_api_port = int(sys.argv[11])
preserve_credentials = sys.argv[12] == "1"
runtime_mode = sys.argv[13]

def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values

def rewrite(src: Path, dst: Path, overrides: dict[str, str]) -> None:
    kept: list[str] = []
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        candidate = line[7:] if line.startswith("export ") else line
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
        if key in overrides:
            continue
        kept.append(raw)
    kept.extend(f"{key}={value}" for key, value in overrides.items())
    dst.write_text("\n".join(kept) + "\n", encoding="utf-8")
    dst.chmod(0o600)

def localize_url(value: str, port: int) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit(f"无法本地化服务 URL: {value[:24]}...")
    userinfo = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    return urlunsplit(
        (parsed.scheme, f"{userinfo}127.0.0.1:{port}", parsed.path, parsed.query, parsed.fragment)
    )

pg = parse(pg_env)
user = pg.get("POSTGRES_USER", "")
password = pg.get("POSTGRES_PASSWORD", "")
if not preserve_credentials and (not user or not password):
    raise SystemExit("PostgreSQL 温备凭据不完整")
encoded = f"{quote(user, safe='')}:{quote(password, safe='')}"
fhd_source = parse(fhd_src)
mod_source = parse(mod_src)

if preserve_credentials:
    fhd_database_url = localize_url(
        fhd_source.get("DATABASE_URL", ""), app_pg_port
    )
    modstore_database_url = localize_url(
        mod_source.get("DATABASE_URL", ""), app_pg_port
    )
    java_database_url = re.sub(
        r"^(jdbc:postgresql://)[^/]+/",
        rf"\g<1>127.0.0.1:{payment_pg_port}/",
        mod_source.get("JAVA_DATABASE_URL", ""),
    )
    database_user = mod_source.get("DATABASE_USER", "")
    database_password = mod_source.get("DATABASE_PASSWORD", "")
else:
    fhd_database_url = (
        f"postgresql+psycopg://{encoded}@127.0.0.1:{app_pg_port}/xcagi"
    )
    modstore_database_url = (
        f"postgresql+psycopg2://{encoded}@127.0.0.1:{app_pg_port}/modstore"
    )
    java_database_url = (
        f"jdbc:postgresql://127.0.0.1:{payment_pg_port}/payment_db"
    )
    database_user = user
    database_password = password

fhd_data = data_root / "fhd"
mod_data = data_root / "modstore"
source_root = runtime_root / "source"
fhd_overrides = {
    "DATABASE_URL": fhd_database_url,
    "FASTAPI_HOST": "127.0.0.1",
    "XCAGI_API_PORT": "15100",
    "XCAGI_UVICORN_RELOAD": "0",
    "XCAGI_DATA_DIR": str(fhd_data),
    "XCAGI_AUTONOMY_DATA_DIR": str(fhd_data / "autonomy"),
    "XCAGI_MODS_ROOT": str(fhd_data / "mods"),
    "WORKSPACE_ROOT": str(source_root),
    "XCMAX_MONOREPO_ROOT": str(source_root),
    "XCAGI_MARKET_BASE_URL": "http://127.0.0.1:19999",
    "MODSTORE_LOCAL_BASE_URL": "http://127.0.0.1:19999",
    "MODSTORE_DIGEST_BASE_URL": "http://127.0.0.1:19999",
    "MODSTORE_ALL_HANDS_BASE_URL": "http://127.0.0.1:19999",
    "XCMAX_NODE_ROLE": runtime_mode,
    "XCAGI_PASSIVE_NODE": "1" if runtime_mode == "active-peer" else "0",
}
mod_overrides = {
    "DATABASE_URL": modstore_database_url,
    "DATABASE_USER": database_user,
    "DATABASE_PASSWORD": database_password,
    "JAVA_DATABASE_URL": java_database_url,
    "SERVER_ADDRESS": "127.0.0.1",
    "SERVER_PORT": "18080",
    "POSTGRES_PORT": str(app_pg_port),
    "REDIS_URL": "redis://127.0.0.1:6379/0",
    "REDIS_PORT": "6379",
    "RABBITMQ_URL": "amqp://guest:guest@127.0.0.1:5672/",
    "FHD_API_BASE_URL": "http://127.0.0.1:15100",
    "MODSTORE_PUBLIC_API_BASE": "http://127.0.0.1:19999",
    "MODSTORE_PUBLIC_ORIGIN": "http://127.0.0.1:19999",
    "MODSTORE_DB_PATH": str(mod_data / "modstore.db"),
    "MODSTORE_RUNTIME_DIR": str(mod_data),
    "MODSTORE_REPO_ROOT": str(source_root),
    "XCMAX_MONOREPO_ROOT": str(source_root),
    "MODSTORE_RUN_BACKGROUND_JOBS": "0",
    "MODSTORE_AUTOMATION_PRIMARY": "prod",
    "MODSTORE_AUTOMATION_ROLE": "dr",
    "MODSTORE_DAILY_BACKUP_ENABLED": "0",
    "MODSTORE_DAILY_BRIEF_ENABLED": "0",
    "MODSTORE_DAILY_DIGEST_ENABLED": "0",
    "MODSTORE_DAILY_MEETING_ENABLED": "0",
    "MODSTORE_DAILY_ORCHESTRATOR_ENABLED": "0",
    "MODSTORE_DAILY_VIBE_PREP_ENABLED": "0",
    "MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED": "0",
    "MODSTORE_DAILY_VIBE_EXECUTE_ENABLED": "0",
    "MODSTORE_DAILY_SURFACE_AUDIT_ENABLED": "0",
    "MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED": "0",
    "MODSTORE_DAILY_SURFACE_PPT_ENABLED": "0",
    "MODSTORE_INBOX_POLL_ENABLED": "0",
    "MODSTORE_LLM_AUTOPILOT_ENABLED": "0",
    "MODSTORE_ONDEMAND_BACKUP_ENABLED": "0",
    "MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED": "0",
    "MODSTORE_RELEASE_TRAIN_ENABLED": "0",
    "MODSTORE_SURFACE_AUDIT_AUTO_START": "0",
    "XCMAX_NODE_ROLE": runtime_mode,
}
if runtime_mode == "active-peer":
    source_redis_url = mod_source.get("REDIS_URL", "")
    if not source_redis_url:
        raise SystemExit("active-peer 缺少生产 REDIS_URL")
    mod_overrides["REDIS_URL"] = localize_url(source_redis_url, redis_port)
    mod_overrides["REDIS_PORT"] = str(redis_port)
    payment_service_url = mod_source.get("JAVA_PAYMENT_SERVICE_URL", "")
    if not payment_service_url:
        raise SystemExit("active-peer 缺少生产 JAVA_PAYMENT_SERVICE_URL")
    mod_overrides["JAVA_PAYMENT_SERVICE_URL"] = localize_url(
        payment_service_url, payment_api_port
    )
    for redis_key in ("REDIS_URL", "CACHE_REDIS_URL", "XCAGI_REDIS_URL"):
        if fhd_source.get(redis_key):
            fhd_overrides[redis_key] = localize_url(
                fhd_source[redis_key], redis_port
            )
release_manifest = source_root / ".xcmax-release.json"
if release_manifest.is_file():
    try:
        release = json.loads(release_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        release = {}
    if isinstance(release, dict) and release.get("git_sha"):
        mod_overrides["MODSTORE_GIT_SHA"] = str(release["git_sha"])
        mod_overrides["MODSTORE_RELEASE_MANIFEST"] = str(release_manifest)
rewrite(fhd_src, fhd_dst, fhd_overrides)
rewrite(mod_src, mod_dst, mod_overrides)
PY

if ! docker inspect xcmax-dr-redis >/dev/null 2>&1; then
  docker run -d \
    --name xcmax-dr-redis \
    --restart unless-stopped \
    -p 127.0.0.1:6379:6379 \
    -v "$DATA/redis:/data" \
    redis:7-alpine \
    redis-server --appendonly yes >/dev/null
elif [[ "$(docker inspect -f '{{.State.Running}}' xcmax-dr-redis)" != "true" ]]; then
  docker start xcmax-dr-redis >/dev/null
fi

tunnel_after=""
if [[ "$RUNTIME_MODE" == "active-peer" ]]; then
  tunnel_after="xcmax-dr-primary-tunnel.service"
fi

cat >/etc/systemd/system/xcmax-dr-fhd.service <<EOF
[Unit]
Description=XCMAX DR FHD API (localhost only)
After=network-online.target docker.service $tunnel_after
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$FHD_ROOT/XCAGI
Environment=HOME=$DATA/fhd
Environment=PYTHONPATH=$FHD_ROOT
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/etc/xcmax-dr-fhd.env
ExecStart=$FHD_ROOT/.venv/bin/python $FHD_ROOT/XCAGI/run.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/xcmax-dr-modstore.service <<EOF
[Unit]
Description=XCMAX DR MODstore API (localhost only, no background jobs)
After=network-online.target docker.service xcmax-dr-fhd.service $tunnel_after
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$MODSTORE_ROOT
Environment=HOME=$DATA/modstore
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile=/etc/xcmax-dr-modstore.env
ExecStart=$MODSTORE_ROOT/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 19999 --workers 1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/xcmax-dr-scheduler.service <<EOF
[Unit]
Description=XCMAX DR MODstore scheduler (promotion only)
After=network-online.target docker.service xcmax-dr-modstore.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$MODSTORE_ROOT
Environment=HOME=$DATA/modstore
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile=/etc/xcmax-dr-modstore.env
Environment=MODSTORE_RUN_BACKGROUND_JOBS=1
Environment=MODSTORE_AUTOMATION_PRIMARY=self
Environment=MODSTORE_AUTOMATION_ROLE=self
ExecStart=$MODSTORE_ROOT/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 19990 --workers 1
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

if [[ -s "$payment_jar" && -x /usr/bin/java ]]; then
  cat >/etc/systemd/system/xcmax-dr-payment.service <<EOF
[Unit]
Description=XCMAX DR Java payment (promotion only)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$RUNTIME/payment
Environment=HOME=$DATA/modstore
EnvironmentFile=/etc/xcmax-dr-modstore.env
ExecStart=/usr/bin/java -jar $payment_jar
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
fi

chmod 0644 \
  /etc/systemd/system/xcmax-dr-fhd.service \
  /etc/systemd/system/xcmax-dr-modstore.service \
  /etc/systemd/system/xcmax-dr-scheduler.service
[[ ! -f /etc/systemd/system/xcmax-dr-payment.service ]] ||
  chmod 0644 /etc/systemd/system/xcmax-dr-payment.service
# /etc/cron.d/xcmax-dr is owned by xcmax_dr_install.sh.  Do not rewrite it
# here: this helper also runs after every release apply, and an older two-line
# cron block would silently remove WAL standby and exact-release schedules.
[[ -f /etc/cron.d/xcmax-dr ]] || {
  echo "缺少 /etc/cron.d/xcmax-dr，请先运行 xcmax_dr_install.sh" >&2
  exit 1
}

systemctl daemon-reload
systemctl disable --now \
  xcmax-dr-fhd.service xcmax-dr-scheduler.service xcmax-dr-payment.service \
  >/dev/null 2>&1 || true
systemctl enable xcmax-dr-modstore.service >/dev/null
if [[ "$RUNTIME_MODE" == "active-peer" ]]; then
  systemctl enable xcmax-dr-fhd.service >/dev/null
  systemctl restart xcmax-dr-fhd.service xcmax-dr-modstore.service
  deadline=$((SECONDS + 150))
  while ((SECONDS < deadline)); do
    if curl -fsS --max-time 5 http://127.0.0.1:15100/api/health >/dev/null &&
      curl -fsS --max-time 5 http://127.0.0.1:19999/api/health >/dev/null; then
      break
    fi
    systemctl is-active --quiet xcmax-dr-fhd.service
    systemctl is-active --quiet xcmax-dr-modstore.service
    sleep 2
  done
  curl -fsS --max-time 5 http://127.0.0.1:15100/api/health >/dev/null
  curl -fsS --max-time 5 http://127.0.0.1:19999/api/health >/dev/null
  echo "活动应用节点已准备：FHD/MODstore 在线，后台任务与支付保持单 Leader"
else
  systemctl restart xcmax-dr-modstore.service
  echo "温备运行环境已准备：FHD 默认停机；MODstore=127.0.0.1:19999（无后台任务）"
fi
