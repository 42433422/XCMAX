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
  current_modstore_sha="$(cat "$STATE/release_applied_modstore_sha" 2>/dev/null || true)"
  current_fhd_sha="$(cat "$STATE/release_applied_fhd_sha" 2>/dev/null || true)"
  incoming="$(
    while IFS= read -r candidate; do
      candidate="${candidate#* }"
      candidate_sha="$(basename "$candidate")"
      if [[ -s "$candidate/modstore.MANIFEST.txt" &&
        "$candidate_sha" != "$current_modstore_sha" ]] ||
        [[ -s "$candidate/fhd.MANIFEST.txt" &&
          "$candidate_sha" != "$current_fhd_sha" ]]; then
        printf '%s\n' "$candidate"
        break
      fi
    done < <(
      find "$INCOMING/runtime-releases" -mindepth 1 -maxdepth 1 -type d \
        -printf '%T@ %p\n' 2>/dev/null | sort -nr
    )
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

apply_modstore() {
  [[ -s "$incoming/modstore.MANIFEST.txt" ]] || return 0
  if [[ -f "$STATE/release_applied_modstore_sha" ]] &&
    [[ "$(cat "$STATE/release_applied_modstore_sha")" == "$sha" ]]; then
    return 0
  fi
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
  log "MODstore DR 代码已切换: $sha"
}

apply_fhd() {
  [[ -s "$incoming/fhd.MANIFEST.txt" ]] || return 0
  if [[ -f "$STATE/release_applied_fhd_sha" ]] &&
    [[ "$(cat "$STATE/release_applied_fhd_sha")" == "$sha" ]]; then
    return 0
  fi
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
