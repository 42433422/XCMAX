#!/usr/bin/env bash
# 服务器端：解压 FHD 发布包 → pip（如需）→ restart fhd-full → 健康检查。
# 由 fhd-push-release.sh / fhd-auto-update.sh / CI 调用。
#
# 环境变量:
#   FHD_DEPLOY_ROOT      默认 /opt/fhd-full
#   FHD_RELEASE_TARBALL  必填（除非 FHD_MANIFEST_DIR 已含 artifact）
#   FHD_SERVICE_NAME     默认 fhd-full.service
#   FHD_HEALTH_PORT      默认 5100
#   FHD_RUN_MIGRATIONS   1 时执行 alembic upgrade head
#   FHD_SKIP_PIP         1 跳过 pip install
#   FHD_SERVICE_PYTHON   服务实际使用的 Python（默认 /usr/bin/python3）
#   FHD_SKIP_LANGGRAPH_BOOTSTRAP  1 时跳过受管 LangGraph 依赖/.pth 引导
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
if [[ -f "$SCRIPT_DIR/lib/deploy_emit.sh" ]]; then
  # shellcheck source=lib/deploy_emit.sh
  . "$SCRIPT_DIR/lib/deploy_emit.sh"
else
  deploy_emit() { echo "[deploy] $*"; }
fi
if [[ -f "$SCRIPT_DIR/lib/autonomy_gate.sh" ]]; then
  # shellcheck source=lib/autonomy_gate.sh
  . "$SCRIPT_DIR/lib/autonomy_gate.sh"
else
  echo "[deploy] ERROR: autonomy gate bridge is missing" >&2
  exit 78
fi
if [[ -f "$SCRIPT_DIR/lib/verify_release_identity.sh" ]]; then
  # shellcheck source=lib/verify_release_identity.sh
  . "$SCRIPT_DIR/lib/verify_release_identity.sh"
else
  echo "[deploy] ERROR: release identity verifier is missing" >&2
  exit 78
fi
export DEPLOY_SCRIPT_ID="fhd_apply_release"

DEPLOY_ROOT="${FHD_DEPLOY_ROOT:-/opt/fhd-full}"
SERVICE="${FHD_SERVICE_NAME:-fhd-full.service}"
HEALTH_PORT="${FHD_HEALTH_PORT:-5100}"
VENV="${FHD_VENV:-$DEPLOY_ROOT/.venv}"
LOG="${FHD_DEPLOY_LOG:-/var/log/fhd-auto-update.log}"
EXPECTED_GIT_SHA="${FHD_GIT_SHA:-}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

if [[ "${FHD_REQUIRE_EXACT_IDENTITY:-1}" == "1" && -z "$EXPECTED_GIT_SHA" ]]; then
  log "ERROR: FHD_GIT_SHA is required for exact-SHA deployment"
  exit 78
fi

TARBALL="${FHD_RELEASE_TARBALL:-}"
if [[ -z "$TARBALL" || ! -f "$TARBALL" ]]; then
  log "ERROR: FHD_RELEASE_TARBALL 不存在: ${TARBALL:-<empty>}"
  deploy_emit apply failed "missing_tarball"
  exit 1
fi

TARBALL_SHA256="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

EXPECTED_SHA="${FHD_EXPECTED_SHA256:-}"
if [[ -n "$EXPECTED_SHA" && "$TARBALL_SHA256" != "$EXPECTED_SHA" ]]; then
  log "ERROR: tarball sha256 与期望不符 (file=$TARBALL_SHA256 expected=$EXPECTED_SHA)"
  deploy_emit apply failed "sha256_mismatch"
  exit 1
fi

deploy_emit apply started "tarball=$TARBALL"
log "开始应用发布包: $TARBALL sha256=${TARBALL_SHA256:0:16}..."

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="${FHD_BACKUP_ROOT:-/opt/fhd-full-backups}"
mkdir -p "$BACKUP_ROOT"
BACKUP="$BACKUP_ROOT/pre-$TS"
mkdir -p "$BACKUP"

for item in .build-identity.json app XCAGI alembic alembic.ini config mods xcagi_common resources packages requirements-langgraph-runtime.txt requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$DEPLOY_ROOT/$item" ]]; then
    rsync -a "$DEPLOY_ROOT/$item" "$BACKUP/"
  fi
done
ADMIN_BACKUP_PRESENT=0
if [[ -d "$DEPLOY_ROOT/templates/admin-vue-dist" ]]; then
  mkdir -p "$BACKUP/templates"
  rsync -a "$DEPLOY_ROOT/templates/admin-vue-dist" "$BACKUP/templates/"
  ADMIN_BACKUP_PRESENT=1
fi
for stamp in .deploy-last.tar.gz .deploy-git-sha .deploy-sha256 .deploy-admin-console-sha256; do
  [[ -f "$DEPLOY_ROOT/$stamp" ]] && cp "$DEPLOY_ROOT/$stamp" "$BACKUP/$stamp"
done
log "已备份至 $BACKUP"

# 保留策略：cron 每 5 分钟执行一次应用，若不清理会以 ~110MB/次速度把磁盘写满
#（历史事故：/opt/fhd-full-backups 累积 318 个 pre-* 目录，占满 124G 磁盘阻塞发布）。
# 仅保留最近 FHD_BACKUP_RETAIN 个备份作为回滚窗口，超出的立即删除。
FHD_BACKUP_RETAIN="${FHD_BACKUP_RETAIN:-10}"
_retained=0
for _dir in $(ls -dt "$BACKUP_ROOT"/pre-* 2>/dev/null); do
  _retained=$((_retained + 1))
  if [[ "$_retained" -gt "$FHD_BACKUP_RETAIN" ]]; then
    log "清理旧备份: $_dir（保留最近 ${FHD_BACKUP_RETAIN} 个）"
    rm -rf "$_dir"
  fi
done
unset _dir _retained

rollback_from_backup() {
  autonomy_evaluate_action "rollback_release" "rollback:${TARBALL_SHA256:0:16}"
  log "执行回滚: $BACKUP"
  for item in .build-identity.json app XCAGI alembic alembic.ini config mods xcagi_common packages requirements-langgraph-runtime.txt requirements-base.txt requirements.txt pyproject.toml; do
    if [[ -e "$BACKUP/$item" ]]; then
      rsync -a --delete "$BACKUP/$item" "$DEPLOY_ROOT/"
    fi
  done
  if [[ -d "$BACKUP/resources" ]]; then
    mkdir -p "$DEPLOY_ROOT/resources"
    rsync -a --delete \
      --exclude 'routing_policies/routing_decisions.jsonl' \
      --exclude 'routing_policies/.online_update_state.json' \
      "$BACKUP/resources/" "$DEPLOY_ROOT/resources/"
  fi
  if [[ "$ADMIN_BACKUP_PRESENT" == "1" ]]; then
    mkdir -p "$DEPLOY_ROOT/templates/admin-vue-dist"
    rsync -a --delete "$BACKUP/templates/admin-vue-dist/" "$DEPLOY_ROOT/templates/admin-vue-dist/"
  else
    rm -rf -- "$DEPLOY_ROOT/templates/admin-vue-dist"
  fi
  for stamp in .deploy-last.tar.gz .deploy-git-sha .deploy-sha256 .deploy-admin-console-sha256; do
    if [[ -f "$BACKUP/$stamp" ]]; then
      cp "$BACKUP/$stamp" "$DEPLOY_ROOT/$stamp"
    else
      rm -f "$DEPLOY_ROOT/$stamp"
    fi
  done
  autonomy_evaluate_action "restart_service" "restart:rollback:${TARBALL_SHA256:0:16}"
  systemctl restart "$SERVICE" || true
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/fhd-apply.XXXXXX")"
MUTATION_STARTED=0
ROLLBACK_DONE=0
cleanup_apply() {
  local status=$?
  trap - EXIT
  if [[ "$status" != "0" && "$MUTATION_STARTED" == "1" && "$ROLLBACK_DONE" == "0" ]]; then
    ROLLBACK_DONE=1
    set +e
    rollback_from_backup
    set -e
  fi
  rm -rf -- "$TMP"
  exit "$status"
}
trap cleanup_apply EXIT
tar -xzf "$TARBALL" -C "$TMP"

ADMIN_VERIFY="$TMP/scripts/deploy/lib/verify_admin_console.py"
EXPECTED_ADMIN_CONSOLE_SHA256="$(
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("admin_console_sha256", ""))' "$TMP/.build-identity.json"
)"
[[ "$EXPECTED_ADMIN_CONSOLE_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  log "ERROR: release is missing the immutable admin console identity"
  exit 1
}
python3 "$ADMIN_VERIFY" \
  --root "$TMP/templates/admin-vue-dist" \
  --expected-git-sha "$EXPECTED_GIT_SHA" \
  --expected-sha256 "$EXPECTED_ADMIN_CONSOLE_SHA256"

MUTATION_STARTED=1
for item in .build-identity.json app XCAGI alembic alembic.ini config mods xcagi_common packages requirements-langgraph-runtime.txt requirements-base.txt requirements.txt pyproject.toml; do
  if [[ -e "$TMP/$item" ]]; then
    rsync -a --delete "$TMP/$item" "$DEPLOY_ROOT/"
  fi
done
if [[ -d "$TMP/resources" ]]; then
  mkdir -p "$DEPLOY_ROOT/resources"
  rsync -a --delete \
    --exclude 'routing_policies/routing_decisions.jsonl' \
    --exclude 'routing_policies/.online_update_state.json' \
    "$TMP/resources/" "$DEPLOY_ROOT/resources/"
fi
mkdir -p "$DEPLOY_ROOT/templates/admin-vue-dist"
rsync -a --delete "$TMP/templates/admin-vue-dist/" "$DEPLOY_ROOT/templates/admin-vue-dist/"
if [[ -d "$TMP/scripts/deploy" ]]; then
  mkdir -p "$DEPLOY_ROOT/scripts"
  rsync -a --delete "$TMP/scripts/deploy/" "$DEPLOY_ROOT/scripts/deploy/"
fi
if [[ -d "$TMP/docker" ]]; then
  mkdir -p "$DEPLOY_ROOT/docker"
  rsync -a "$TMP/docker/" "$DEPLOY_ROOT/docker/"
fi
log "代码已同步至 $DEPLOY_ROOT"

bootstrap_vendored_langgraph() {
  local service_python="${FHD_SERVICE_PYTHON:-/usr/bin/python3}"
  local requirements="$DEPLOY_ROOT/requirements-langgraph-runtime.txt"
  local package_dirs=(
    "$DEPLOY_ROOT/packages/xcagi_langgraph_core"
    "$DEPLOY_ROOT/packages/xcagi_langgraph_checkpoint"
    "$DEPLOY_ROOT/packages/xcagi_langgraph_checkpoint_backends/checkpoint-sqlite"
    "$DEPLOY_ROOT/packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres"
    "$DEPLOY_ROOT/packages/xcagi_langgraph_prebuilt"
    "$DEPLOY_ROOT/packages/xcagi_langgraph_sdk"
  )

  [[ -x "$service_python" ]] || {
    log "ERROR: service Python 不可执行: $service_python"
    return 1
  }
  [[ -f "$requirements" ]] || {
    log "ERROR: 缺少 LangGraph 运行时依赖清单: $requirements"
    return 1
  }
  local package_dir
  for package_dir in "${package_dirs[@]}"; do
    [[ -f "$package_dir/PROVENANCE.json" ]] || {
      log "ERROR: 缺少受管 LangGraph provenance: $package_dir/PROVENANCE.json"
      return 1
    }
  done

  deploy_emit pip started "scope=vendored_langgraph python=$service_python"
  PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore \
    "$service_python" -m pip install --quiet --no-cache-dir -r "$requirements"

  local purelib
  purelib="$($service_python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  [[ -d "$purelib" ]] || {
    log "ERROR: Python purelib 目录不存在: $purelib"
    return 1
  }
  local pth_tmp="$TMP/xcagi_vendored_langgraph.pth"
  "$service_python" - "$pth_tmp" "${package_dirs[@]}" <<'PY'
import sys

target, *paths = sys.argv[1:]
line = (
    "import sys; _xcagi_vendored_paths="
    + repr(paths)
    + "; sys.path[:0]=[p for p in _xcagi_vendored_paths if p not in sys.path]\n"
)
with open(target, "w", encoding="utf-8") as fh:
    fh.write(line)
PY
  install -m 0644 "$pth_tmp" "$purelib/xcagi_vendored_langgraph.pth"

  PYTHONPATH="$DEPLOY_ROOT" "$service_python" - <<'PY'
from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources

assert_vendored_sources()
PY
  deploy_emit pip ok "scope=vendored_langgraph"
}

if [[ "${FHD_SKIP_LANGGRAPH_BOOTSTRAP:-0}" != "1" ]]; then
  bootstrap_vendored_langgraph
fi

if [[ "${FHD_SKIP_PIP:-0}" != "1" ]]; then
  deploy_emit pip started
  if [[ ! -x "$VENV/bin/pip" ]]; then
    python3 -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  . "$VENV/bin/activate"
  pip install -q -U pip
  if [[ -f "$DEPLOY_ROOT/requirements-base.txt" ]]; then
    pip install -q -r "$DEPLOY_ROOT/requirements-base.txt"
  elif [[ -f "$DEPLOY_ROOT/requirements.txt" ]]; then
    pip install -q -r "$DEPLOY_ROOT/requirements.txt"
  fi
  deploy_emit pip ok
fi

if [[ "${FHD_RUN_MIGRATIONS:-0}" == "1" && -f "$DEPLOY_ROOT/alembic.ini" ]]; then
  log "ERROR: autonomous db migration requested; autonomy boundary must block it"
  if autonomy_evaluate_action "db_migration" "migration:${TARBALL_SHA256:0:16}"; then
    log "ERROR: prohibited db_migration unexpectedly passed autonomy_guard"
  fi
  deploy_emit migrate failed "prohibited_by_autonomy_boundary"
  exit 77
fi

deploy_emit restart started "service=$SERVICE"
autonomy_evaluate_action "restart_service" "restart:release:${TARBALL_SHA256:0:16}"
echo "$TARBALL_SHA256" > "$DEPLOY_ROOT/.deploy-sha256"
echo "$EXPECTED_GIT_SHA" > "$DEPLOY_ROOT/.deploy-git-sha"
echo "$EXPECTED_ADMIN_CONSOLE_SHA256" > "$DEPLOY_ROOT/.deploy-admin-console-sha256"
systemctl restart "$SERVICE"
sleep "${FHD_HEALTH_INITIAL_SLEEP:-15}"

API_CODE=000
HEALTH_PATH="${FHD_HEALTH_PATH:-/api/health}"
HEALTH_RETRIES="${FHD_HEALTH_RETRIES:-90}"
HEALTH_INTERVAL="${FHD_HEALTH_INTERVAL:-3}"
for _ in $(seq 1 "$HEALTH_RETRIES"); do
  if verify_release_health_identity \
      "http://127.0.0.1:${HEALTH_PORT}${HEALTH_PATH}?lite=true" \
      "$EXPECTED_GIT_SHA" \
      "" \
      "$TARBALL_SHA256" \
      "$EXPECTED_ADMIN_CONSOLE_SHA256"; then
    API_CODE=200
    break
  fi
  sleep "$HEALTH_INTERVAL"
done

if [[ "$API_CODE" == "200" ]] && ! python3 "$DEPLOY_ROOT/scripts/deploy/lib/verify_admin_console.py" \
    --base-url "http://127.0.0.1:${HEALTH_PORT}/admin/" \
    --expected-git-sha "$EXPECTED_GIT_SHA" \
    --expected-sha256 "$EXPECTED_ADMIN_CONSOLE_SHA256"; then
  API_CODE=admin_identity_mismatch
fi

if [[ "$API_CODE" != "200" ]]; then
  log "ERROR: /api/health 未就绪 (code=$API_CODE)，尝试回滚"
  ROLLBACK_DONE=1
  rollback_from_backup
  deploy_emit apply failed "health_check rollback"
  exit 1
fi

cp "$TARBALL" "${DEPLOY_ROOT}/.deploy-last.tar.gz" 2>/dev/null || true

MUTATION_STARTED=0
log "发布成功 health=200 sha256=${TARBALL_SHA256:0:16}..."
deploy_emit apply ok "port=$HEALTH_PORT"
