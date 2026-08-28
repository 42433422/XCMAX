#!/usr/bin/env bash
# Verify and atomically apply release payloads received from production.
# Python environments remain local to DR; code directories are versioned and
# the active runtime path is switched only after archive validation.

set -euo pipefail

[[ "${EUID}" == "0" ]] || {
  echo "请以 root 运行" >&2
  exit 2
}

DR_ROOT="${OPS_DR_ROOT:-/srv/xcmax-dr}"
INCOMING="${OPS_DR_INCOMING:-$DR_ROOT/incoming}"
RELEASES="${OPS_DR_RELEASES:-$DR_ROOT/releases}"
RUNTIME="$DR_ROOT/runtime"
SHARED="$DR_ROOT/runtime-shared"
STATE="${OPS_DR_STATE:-/var/lib/xcmax-dr}"
LOG="${OPS_DR_RELEASE_LOG:-/var/log/xcmax-dr/release-apply.log}"
APP_GROUP="${OPS_DR_APP_GROUP:-xcmaxapp}"
LOCK="/run/lock/xcmax-dr-release-apply.lock"
RELEASE_ORDER="/usr/local/sbin/xcmax-release-order"
REQUESTED_SHA=""
if [[ "${1:-}" == "--sha" ]]; then
  REQUESTED_SHA="${2:-}"
  [[ "$REQUESTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
    echo "--sha 非法" >&2
    exit 2
  }
fi

[[ "$DR_ROOT" == /srv/xcmax-dr ]] || {
  echo "拒绝非标准 DR 根目录: $DR_ROOT" >&2
  exit 2
}
getent group "$APP_GROUP" >/dev/null || {
  echo "缺少 DR 应用组: $APP_GROUP" >&2
  exit 1
}
install -d -o root -g "$APP_GROUP" -m 0750 "$RELEASES"
install -d -o root -g "$APP_GROUP" -m 0750 "$SHARED"
install -d -m 0700 "$STATE" "$(dirname "$LOG")"
touch "$LOG"
exec 9>"$LOCK"
flock -n 9 || exit 0
[[ -x "$RELEASE_ORDER" ]] || {
  echo "缺少发布顺序选择器: $RELEASE_ORDER" >&2
  exit 1
}

bootstrap_applied_timestamp() {
  local component="$1" current_sha timestamp state_file temp_file
  state_file="$STATE/release_applied_${component}_created_at"
  if [[ -s "$state_file" ]] && [[ "$(cat "$state_file")" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  current_sha="$(
    cat "$STATE/release_applied_${component}_sha" 2>/dev/null || true
  )"
  [[ "$current_sha" =~ ^[0-9a-f]{40}$ ]] || return 0
  timestamp="$(
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" created-at \
      --candidate "$INCOMING/runtime-releases/$current_sha" \
      --component "$component" 2>/dev/null
  )" || return 0
  temp_file="$STATE/.release_applied_${component}_created_at.$$"
  printf '%s\n' "$timestamp" >"$temp_file"
  mv "$temp_file" "$state_file"
}

bootstrap_applied_timestamp modstore
bootstrap_applied_timestamp fhd

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

wait_http() {
  local url="$1" deadline=$((SECONDS + 90))
  while ((SECONDS < deadline)); do
    if curl -fsS --max-time 3 "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  curl -fsS --max-time 3 "$url" >/dev/null
}

if [[ -n "$REQUESTED_SHA" ]]; then
  incoming="$INCOMING/runtime-releases/$REQUESTED_SHA"
else
  incoming="$(
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" select
  )"
fi
[[ -n "${incoming:-}" && -d "$incoming" ]] || exit 0
sha="$(basename "$incoming")"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || {
  log "忽略非法发布目录: $incoming"
  exit 1
}

release="$RELEASES/$sha"
install -d -o root -g "$APP_GROUP" -m 0750 "$release"

prepare_shared_venv() {
  local current="$1" shared="$2"
  if [[ ! -e "$shared" && -d "$current" && ! -L "$current" ]]; then
    mv "$current" "$shared"
  fi
  if [[ -d "$shared" ]]; then
    chgrp -R "$APP_GROUP" "$shared"
    chmod -R g+rX "$shared"
  fi
}

bootstrap_fhd_vendored_langgraph() {
  local target="$1" service_python="$2"
  local requirements="$target/requirements-langgraph-runtime.txt"
  local purelib="" pth_tmp="$STATE/.xcagi_vendored_langgraph.pth.$$"
  local package_dirs=(
    "$target/packages/xcagi_langgraph_core"
    "$target/packages/xcagi_langgraph_checkpoint"
    "$target/packages/xcagi_langgraph_checkpoint_backends/checkpoint-sqlite"
    "$target/packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres"
    "$target/packages/xcagi_langgraph_prebuilt"
    "$target/packages/xcagi_langgraph_sdk"
  )

  [[ -x "$service_python" && -f "$requirements" ]] || {
    log "ERROR: DR FHD LangGraph 运行依赖或 Python 不可用"
    return 1
  }
  local package_dir
  for package_dir in "${package_dirs[@]}"; do
    [[ -f "$package_dir/PROVENANCE.json" ]] || {
      log "ERROR: DR FHD 缺少受管 LangGraph provenance: $package_dir"
      return 1
    }
  done

  PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore \
    "$service_python" -m pip install --quiet --no-cache-dir -r "$requirements"
  purelib="$(
    "$service_python" -c \
      'import sysconfig; print(sysconfig.get_paths()["purelib"])'
  )"
  [[ -d "$purelib" ]] || {
    log "ERROR: DR FHD Python purelib 不存在: $purelib"
    return 1
  }
  "$service_python" - "$pth_tmp" "${package_dirs[@]}" <<'PY'
import sys

target, *paths = sys.argv[1:]
line = (
    "import sys; _xcagi_vendored_paths="
    + repr(paths)
    + "; sys.path[:0]=[p for p in _xcagi_vendored_paths if p not in sys.path]\n"
)
with open(target, "w", encoding="utf-8") as handle:
    handle.write(line)
PY
  install -m 0644 "$pth_tmp" "$purelib/xcagi_vendored_langgraph.pth"
  rm -f -- "$pth_tmp"
  PYTHONPATH="$target" "$service_python" - <<'PY'
from app.infrastructure.workflow.langgraph_assert import assert_vendored_sources

assert_vendored_sources()
PY
  chgrp -R "$APP_GROUP" "$(dirname "$(dirname "$service_python")")"
  chmod -R g+rX "$(dirname "$(dirname "$service_python")")"
  log "FHD DR vendored LangGraph 运行依赖已校验"
}

apply_modstore() {
  local candidate_created_at rc
  [[ -s "$incoming/modstore.MANIFEST.txt" ]] || return 0
  if [[ -z "$REQUESTED_SHA" ]]; then
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" should-apply \
      --candidate "$incoming" --component modstore || {
        rc="$?"
        [[ "$rc" == "3" ]] && return 0
        return "$rc"
      }
  elif [[ -f "$STATE/release_applied_modstore_sha" ]] &&
    [[ "$(cat "$STATE/release_applied_modstore_sha")" == "$sha" ]]; then
    return 0
  fi
  candidate_created_at="$(
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" created-at \
      --candidate "$incoming" --component modstore
  )"
  (cd "$incoming" && sha256sum -c modstore.MANIFEST.txt)
  target="$release/source"
  systemctl stop xcmax-dr-modstore 2>/dev/null || true
  rm -rf -- "$target"
  install -d -m 0750 "$target"
  tar -xzf "$incoming/modstore-source.tar.gz" -C "$target"
  mod_rel="成都修茈科技有限公司/MODstore_deploy"
  [[ -s "$incoming/modstore-static.tar.gz" ]] || {
    log "ERROR: MODstore DR 前端制品缺失"
    return 1
  }
  install -d -m 0750 "$target/$mod_rel/market"
  tar -xzf "$incoming/modstore-static.tar.gz" \
    -C "$target/$mod_rel/market"
  cp "$incoming/modstore-release.json" "$target/.xcmax-release.json"

  prepare_shared_venv \
    "$RUNTIME/source/$mod_rel/.venv" "$SHARED/modstore-venv"
  [[ -x "$SHARED/modstore-venv/bin/python" ]] || {
    log "ERROR: DR MODstore Python 环境不存在"
    return 1
  }
  ln -s "$SHARED/modstore-venv" "$target/$mod_rel/.venv"
  chgrp -R "$APP_GROUP" "$target"
  chmod -R g+rX "$target"
  "$target/$mod_rel/.venv/bin/python" -m compileall -q \
    "$target/$mod_rel/modstore_server"

  if [[ -e "$RUNTIME/source" && ! -L "$RUNTIME/source" ]]; then
    rm -rf -- "$RUNTIME/source.previous"
    mv "$RUNTIME/source" "$RUNTIME/source.previous"
  fi
  ln -sfn "$target" "$RUNTIME/source"
  /usr/local/sbin/xcmax-dr-prepare-runtime
  systemctl restart xcmax-dr-modstore
  wait_http http://127.0.0.1:19999/api/health
  printf '%s\n' "$sha" >"$STATE/release_applied_modstore_sha"
  printf '%s\n' "$candidate_created_at" \
    >"$STATE/release_applied_modstore_created_at"
  log "MODstore DR 代码已切换: $sha"
}

apply_fhd() {
  local candidate_created_at rc
  [[ -s "$incoming/fhd.MANIFEST.txt" ]] || return 0
  if [[ -z "$REQUESTED_SHA" ]]; then
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" should-apply \
      --candidate "$incoming" --component fhd || {
        rc="$?"
        [[ "$rc" == "3" ]] && return 0
        return "$rc"
      }
  elif [[ -f "$STATE/release_applied_fhd_sha" ]] &&
    [[ "$(cat "$STATE/release_applied_fhd_sha")" == "$sha" ]]; then
    return 0
  fi
  candidate_created_at="$(
    "$RELEASE_ORDER" \
      --incoming "$INCOMING/runtime-releases" \
      --state "$STATE" created-at \
      --candidate "$incoming" --component fhd
  )"
  (cd "$incoming" && sha256sum -c fhd.MANIFEST.txt)
  artifact="$(
    python3 - "$incoming/fhd-manifest.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("artifact", ""))
PY
  )"
  [[ -n "$artifact" && -s "$incoming/$artifact" ]] || {
    log "ERROR: FHD DR 制品缺失"
    return 1
  }
  target="$release/fhd"
  was_active=0
  systemctl is-active --quiet xcmax-dr-fhd && was_active=1
  systemctl stop xcmax-dr-fhd 2>/dev/null || true
  rm -rf -- "$target"
  install -d -m 0750 "$target"
  tar -xzf "$incoming/$artifact" -C "$target"

  prepare_shared_venv "$RUNTIME/fhd/.venv" "$SHARED/fhd-venv"
  [[ -x "$SHARED/fhd-venv/bin/python" ]] || {
    log "ERROR: DR FHD Python 环境不存在"
    return 1
  }
  ln -s "$SHARED/fhd-venv" "$target/.venv"
  bootstrap_fhd_vendored_langgraph "$target" "$target/.venv/bin/python"
  chgrp -R "$APP_GROUP" "$target"
  chmod -R g+rX "$target"
  "$target/.venv/bin/python" -m compileall -q "$target/XCAGI"

  if [[ -e "$RUNTIME/fhd" && ! -L "$RUNTIME/fhd" ]]; then
    rm -rf -- "$RUNTIME/fhd.previous"
    mv "$RUNTIME/fhd" "$RUNTIME/fhd.previous"
  fi
  ln -sfn "$target" "$RUNTIME/fhd"
  /usr/local/sbin/xcmax-dr-prepare-runtime
  if [[ "$was_active" == "1" ]]; then
    systemctl restart xcmax-dr-fhd
    wait_http http://127.0.0.1:15100/api/health
  fi
  printf '%s\n' "$sha" >"$STATE/release_applied_fhd_sha"
  printf '%s\n' "$candidate_created_at" \
    >"$STATE/release_applied_fhd_created_at"
  log "FHD DR 代码已切换: $sha"
}

apply_modstore
apply_fhd
if [[ -f "$STATE/release_applied_modstore_sha" &&
  -f "$STATE/release_applied_fhd_sha" ]] &&
  [[ "$(cat "$STATE/release_applied_modstore_sha")" == "$sha" ]] &&
  [[ "$(cat "$STATE/release_applied_fhd_sha")" == "$sha" ]]; then
  printf '%s\n' "$sha" >"$STATE/release_applied_sha"
else
  rm -f "$STATE/release_applied_sha"
fi
date -u +%s >"$STATE/release_apply_last_success"
