#!/usr/bin/env bash
# Verify and atomically apply release payloads received from production.
# Python environments remain local to DR; code directories are versioned and
# the active runtime path is switched only after archive validation.

set -euo pipefail

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

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

verify_runtime() {
  local component="$1" manifest="$2" expected_sha="$3" url="$4"
  local wait_seconds="${OPS_DR_HEALTH_WAIT_SECONDS:-90}" payload deadline
  [[ "$wait_seconds" =~ ^[1-9][0-9]*$ && "$wait_seconds" -le 300 ]] || return 1
  deadline=$((SECONDS + wait_seconds))
  while :; do
    if payload="$(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 3 "$url")" &&
      printf '%s\n' "$payload" | "$RELEASE_ORDER" --incoming "$INCOMING/runtime-releases" \
        --state "$STATE" verify-health --component "$component" \
        --candidate "$manifest" --sha "$expected_sha"; then
      return 0
    fi
    ((SECONDS < deadline)) || return 1
    sleep 2
  done
}

atomic_link() {
  local target="$1" link="$2" temporary="${2}.switch.$$"
  ln -s -- "$target" "$temporary" && mv -Tf -- "$temporary" "$link"
}

verify_current_component() {
  local component="$1" name=source port=19999 manifest expected_sha
  [[ ! -e "$STATE/release_apply_${component}.pending" ]] || {
    log "ERROR: $component 存在待核对切换，不能确认运行验收"; return 1;
  }
  [[ "$component" == modstore ]] || { name=fhd; port=15100; }
  manifest="$RUNTIME/$name/.xcmax-release.json"
  [[ "$component" == modstore ]] || manifest="$RUNTIME/$name/fhd-manifest.json"
  expected_sha="$(cat "$STATE/release_applied_${component}_sha")" || return 1
  [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || return 1
  systemctl is-active --quiet "xcmax-dr-$component" || return 1
  verify_runtime "$component" "$manifest" "$expected_sha" "http://127.0.0.1:$port/api/health"
}

# Call only while the release lock is held. Component health is not pair evidence.
verify_applied_release_pair() {
  local aggregate component applied
  aggregate="$(cat "$STATE/release_applied_sha" 2>/dev/null)" &&
    [[ "$aggregate" =~ ^[0-9a-f]{40}$ ]] || {
    log "ERROR: 缺少有效整组发布 SHA，不能确认运行验收"; return 1;
  }
  # Independent healthy components can belong to different releases after a
  # partial apply/rollback. Require the committed pair before any live checks.
  for component in modstore fhd; do
    [[ ! -e "$STATE/release_apply_${component}.pending" ]] || {
      log "ERROR: $component 存在待核对切换，不能确认整组发布"; return 1;
    }
    applied="$(cat "$STATE/release_applied_${component}_sha" 2>/dev/null)" &&
      [[ "$applied" == "$aggregate" ]] || {
      log "ERROR: $component 发布组件 SHA 不一致，不能确认整组发布"; return 1;
    }
  done
}

verify_current_release_pair() {
  local component
  verify_applied_release_pair || return 1
  for component in modstore fhd; do
    verify_current_component "$component" || return 1
  done
  verify_applied_release_pair
}

# Restore only an original receipt, under the same release lock as activation.
# Independent component health cannot manufacture a previously absent pair.
restore_previous_release_pair() {
  local expected="$1" phase component applied temporary="$STATE/.release_applied_sha.$$"
  [[ "$expected" =~ ^[0-9a-f]{40}$ && ! -e "$STATE/release_applied_sha" ]] || return 1
  for phase in before after; do
    for component in modstore fhd; do
      [[ ! -e "$STATE/release_apply_${component}.pending" ]] || return 1
      applied="$(cat "$STATE/release_applied_${component}_sha" 2>/dev/null)" &&
        [[ "$applied" == "$expected" ]] || return 1
    done
    if [[ "$phase" == before ]]; then
      for component in modstore fhd; do
        verify_current_component "$component" || return 1
      done
    fi
  done
  if printf '%s\n' "$expected" >"$temporary" &&
    mv -f -- "$temporary" "$STATE/release_applied_sha"; then
    log "原整组发布回执已重新核验: $expected"
    return 0
  fi
  rm -f -- "$temporary"
  return 1
}

acquire_release_lock() {
  exec 9>"$LOCK"
  if ! flock -n 9; then
    [[ "$VERIFY_CURRENT" == 1 ]] || exit 0
    log "ERROR: 发布正在切换，不能确认运行验收"
    return 1
  fi
}

# This is the only activation path. Native flock serializes callers; a pending
# record survives SIGKILL and prevents blindly repeating an uncertain switch.
activate_component() (
  set -euo pipefail
  local component="$1" target="$2" manifest="$3" candidate_sha="$4" created_at="$5"
  local name=source port=19999 service="xcmax-dr-$1" previous_manifest previous_sha
  [[ "$component" == modstore ]] || { name=fhd; port=15100; }
  local current="$RUNTIME/$name" pending="$STATE/release_apply_${component}.pending"
  local previous="" was_active=0 touched=0 moved_directory=0
  [[ ! -e "$pending" ]] || { log "ERROR: 原 $component 切换尚待核对: $pending"; exit 1; }
  if [[ -L "$current" || -d "$current" ]]; then
    previous="$(readlink -f "$current")"
    previous_manifest="$previous/.xcmax-release.json"
    [[ "$component" == modstore ]] || previous_manifest="$previous/fhd-manifest.json"
    [[ -f "$previous_manifest" ]] || { log "ERROR: 原版本缺少精确身份，不能保证补偿恢复"; exit 1; }
    previous_sha="$(python3 - "$previous_manifest" <<'IDENTITY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["git_sha"])
IDENTITY
    )"
    [[ "$previous_sha" =~ ^[0-9a-f]{40}$ && "$previous" != "$target" ]] || {
      log "ERROR: 原版本身份冲突，须核对后恢复"; exit 1;
    }
    "$RELEASE_ORDER" --incoming "$INCOMING/runtime-releases" --state "$STATE" \
      verify-identity --candidate "$previous_manifest" --component "$component" --sha "$previous_sha"
  fi
  systemctl is-active --quiet "$service" && was_active=1
  [[ -n "$previous" || "$was_active" == 0 ]] || {
    log "ERROR: 运行中服务缺少原发布路径，拒绝不可恢复的切换"; exit 1;
  }
  mkdir -m 0700 "$pending"
  printf '%s\n' "$previous" "$target" "$was_active" >"$pending/targets"
  for suffix in sha created_at; do
    [[ ! -f "$STATE/release_applied_${component}_$suffix" ]] ||
      cp -- "$STATE/release_applied_${component}_$suffix" "$pending/$suffix"
  done
  [[ ! -f "$STATE/release_applied_sha" ]] ||
    cp -- "$STATE/release_applied_sha" "$pending/aggregate_sha"
  finish_activation() {
    local code="$?" restored=0 observed previous_pair_sha
    trap - EXIT
    if [[ "$code" == 0 ]]; then
      rm -rf -- "$pending"
      return
    fi
    previous_pair_sha="$(cat "$pending/aggregate_sha" 2>/dev/null || true)"
    if [[ "$touched" == 0 ]]; then
      rm -rf -- "$pending"
      restore_previous_release_pair "$previous_pair_sha" ||
        log "ERROR: 原整组发布尚未核验，保持整组验收阻断"
      return "$code"
    fi
    # A competing pointer is never overwritten by this attempt's compensation.
    observed="$(readlink -f "$current" 2>/dev/null || true)"
    if [[ "$observed" == "$target" || ( -n "$previous" && "$observed" == "$previous" ) ||
      ( "$moved_directory" == 1 && ! -e "$current" && ! -L "$current" ) ]] && systemctl stop "$service"; then
      if [[ -z "$previous" && "$was_active" == 0 ]] && rm -f -- "$current"; then
        restored=1
      elif [[ -n "$previous" ]] && atomic_link "$previous" "$current" &&
        "$PREPARE_RUNTIME" --release-update; then
        if [[ "$was_active" == 1 ]]; then
          if systemctl restart "$service" &&
            verify_runtime "$component" "$previous_manifest" "$previous_sha" "http://127.0.0.1:$port/api/health"; then
            restored=1
          fi
        else
          restored=1
        fi
      fi
    fi
    if [[ "$restored" == 1 ]]; then
      for suffix in sha created_at; do
        if [[ -f "$pending/$suffix" ]]; then
          cp -- "$pending/$suffix" "$STATE/.${component}_$suffix.$$" &&
            mv -f -- "$STATE/.${component}_$suffix.$$" "$STATE/release_applied_${component}_$suffix" || restored=0
        else
          rm -f -- "$STATE/release_applied_${component}_$suffix" || restored=0
        fi
      done
    fi
    if [[ "$restored" == 1 ]]; then
      log "ERROR: $component 候选未通过，已恢复原版本及原运行状态"
      rm -rf -- "$pending"
      restore_previous_release_pair "$previous_pair_sha" ||
        log "ERROR: 原整组发布尚未核验，保持整组验收阻断"
    else
      log "ERROR: $component 恢复结果未核实，保留原切换证据: $pending"
    fi
    return "$code"
  }
  trap finish_activation EXIT
  # A mixed or interrupted component transition must never advertise the old
  # aggregate as the currently applied release. Main rebuilds it after both.
  rm -f -- "$STATE/release_applied_sha"
  # A directory bootstrap is retained once; no previous installation is deleted.
  if [[ -d "$current" && ! -L "$current" ]]; then
    [[ ! -e "${current}.previous" ]] || exit 1
    touched=1
    systemctl stop "$service"
    mv -- "$current" "${current}.previous"
    previous="${current}.previous"
    previous_manifest="$previous/${manifest##*/}"
    moved_directory=1
    printf '%s\n' "$previous" "$target" "$was_active" >"$pending/targets"
  fi
  touched=1
  atomic_link "$target" "$current"
  "$PREPARE_RUNTIME" --release-update
  if [[ "$was_active" == 1 || "$component" == modstore ]]; then
    systemctl restart "$service"
    verify_runtime "$component" "$manifest" "$candidate_sha" "http://127.0.0.1:$port/api/health"
  else
    log "FHD standby 保持停机；代码已暂存，运行身份仍待 promotion 验证"
  fi
  printf '%s\n' "$created_at" >"$pending/new_created_at"
  printf '%s\n' "$candidate_sha" >"$pending/new_sha"
  mv -f -- "$pending/new_created_at" "$STATE/release_applied_${component}_created_at"
  mv -f -- "$pending/new_sha" "$STATE/release_applied_${component}_sha"
)

copy_release_environment() {
  local current="$1" fallback="$2" destination="$3" source
  source="$(readlink -f "$current" 2>/dev/null || true)"
  [[ -x "$source/bin/python" ]] || source="$fallback"
  [[ -x "$source/bin/python" && ! -e "$destination" ]] || return 1
  # reflinks are copy-on-write; never share writable dependency inodes with the
  # rollback target. Only `python -m pip` is used with the copied environment.
  cp -a --reflink=auto -- "$source" "$destination"
}

apply_component() {
  local component="$1" rc candidate_created_at staged artifact target manifest mod_rel
  [[ -s "$incoming/$component.MANIFEST.txt" ]] || return 0
  [[ ! -e "$STATE/release_apply_${component}.pending" ]] || {
    log "ERROR: $component 存在未完成切换，拒绝自动重放"; return 1;
  }
  if [[ -z "$REQUESTED_SHA" ]]; then
    "$RELEASE_ORDER" --incoming "$INCOMING/runtime-releases" --state "$STATE" \
      should-apply --candidate "$incoming" --component "$component" || {
      rc="$?"; [[ "$rc" == 3 ]] && return 0; return "$rc";
    }
  elif [[ "$(cat "$STATE/release_applied_${component}_sha" 2>/dev/null || true)" == "$sha" ]]; then
    return 0
  fi
  candidate_created_at="$("$RELEASE_ORDER" --incoming "$INCOMING/runtime-releases" \
    --state "$STATE" created-at --candidate "$incoming" --component "$component")"
  staged="$(mktemp -d "$STATE/.release-${component}-${sha}.XXXXXX")"
  # Copy bytes to a root-owned immutable attempt before validation/extraction.
  cp -P -- "$incoming/$component.MANIFEST.txt" "$staged/"
  if [[ "$component" == modstore ]]; then
    cp -P -- "$incoming/modstore-release.json" "$incoming/modstore-source.tar.gz" \
      "$incoming/modstore-static.tar.gz" "$staged/"
  else
    cp -P -- "$incoming/fhd-manifest.json" "$staged/"
    artifact="$(python3 - "$staged/fhd-manifest.json" <<'ARTIFACT'
import json, re, sys
name = json.load(open(sys.argv[1], encoding="utf-8")).get("artifact")
if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", name):
    raise SystemExit("invalid FHD archive name")
print(name)
ARTIFACT
    )"
    cp -P -- "$incoming/$artifact" "$staged/"
  fi
  artifact="$("$RELEASE_ORDER" --incoming "$INCOMING/runtime-releases" --state "$STATE" \
    verify-input --candidate "$staged" --component "$component" --sha "$sha")"
  target="$release/source"
  [[ "$component" == modstore ]] || target="$release/fhd"
  [[ ! -e "$target" ]] || { log "ERROR: 候选目录已存在；拒绝覆写或重放: $target"; return 1; }
  install -d -o root -g "$APP_GROUP" -m 0750 "$target"
  python3 - "$staged/$artifact" "$target" "$component" "$sha" <<'EXTRACT'
import sys, tarfile
archive, target, component, sha = sys.argv[1:]
with tarfile.open(archive) as source:
    if component == "modstore" and source.pax_headers.get("comment") != sha:
        raise SystemExit("MODstore archive does not identify original commit")
    source.extractall(target, filter="data")
EXTRACT
  if [[ "$component" == modstore ]]; then
    mod_rel="成都修茈科技有限公司/MODstore_deploy"
    install -d -m 0750 "$target/$mod_rel/market"
    python3 - "$staged/modstore-static.tar.gz" "$target/$mod_rel/market" <<'STATIC'
import sys, tarfile
with tarfile.open(sys.argv[1]) as source:
    source.extractall(sys.argv[2], filter="data")
STATIC
    manifest="$target/.xcmax-release.json"
    cp -- "$staged/modstore-release.json" "$manifest"
    copy_release_environment "$RUNTIME/source/$mod_rel/.venv" "$SHARED/modstore-venv" "$target/$mod_rel/.venv"
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore \
      "$target/$mod_rel/.venv/bin/python" -m pip install --quiet --no-cache-dir \
      "$target/packages/retort_engine" "$target/packages/xcagi_common" \
      "$target/FHD/packages/xcagi_langgraph_core" \
      "$target/FHD/packages/xcagi_langgraph_checkpoint" \
      "$target/FHD/packages/xcagi_langgraph_checkpoint_backends/checkpoint-sqlite" \
      "$target/FHD/packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres" \
      "$target/FHD/packages/xcagi_langgraph_prebuilt" "$target/FHD/packages/xcagi_langgraph_sdk" \
      -e "$target/${mod_rel}[web,knowledge,evolution-metrics,governance,llm-router]"
    "$target/$mod_rel/.venv/bin/python" -m compileall -q "$target/$mod_rel/modstore_server"
  else
    manifest="$target/fhd-manifest.json"
    cp -- "$staged/fhd-manifest.json" "$manifest"
    # Reuse the existing packaged archive verifier before any running pointer moves.
    python3 "$target/scripts/deploy/lib/verify_release_archive.py" --archive "$staged/$artifact"
    copy_release_environment "$RUNTIME/fhd/.venv" "$SHARED/fhd-venv" "$target/.venv"
    bootstrap_fhd_vendored_langgraph "$target" "$target/.venv/bin/python"
    "$target/.venv/bin/python" -m compileall -q "$target/XCAGI"
  fi
  chgrp -R "$APP_GROUP" "$target"
  chmod -R g+rX "$target"
  chmod -R go-w "$target"
  activate_component "$component" "$target" "$manifest" "$sha" "$candidate_created_at"
  rm -rf -- "$staged"
  log "$component DR 代码已核验切换: $sha"
}

main() {
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
  PREPARE_RUNTIME="/usr/local/sbin/xcmax-dr-prepare-runtime"
  REQUESTED_SHA=""
  VERIFY_CURRENT=0
  if [[ "${1:-}" == "--verify-current" && $# == 1 ]]; then
    VERIFY_CURRENT=1
  elif [[ "${1:-}" == "--sha" && $# == 2 ]]; then
    REQUESTED_SHA="${2:-}"
    [[ "$REQUESTED_SHA" =~ ^[0-9a-f]{40}$ ]] || {
      echo "--sha 非法" >&2
      exit 2
    }
  elif (( $# != 0 )); then
    echo "usage: $0 [--sha <40-hex-sha> | --verify-current]" >&2
    exit 2
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
  acquire_release_lock
  [[ -x "$RELEASE_ORDER" ]] || {
    echo "缺少发布顺序选择器: $RELEASE_ORDER" >&2
    exit 1
  }

  if [[ "$VERIFY_CURRENT" == 1 ]]; then
    verify_current_release_pair
    log "FHD/MODstore 运行身份与已应用发布完全一致"
    exit 0
  fi

  bootstrap_applied_timestamp modstore
  bootstrap_applied_timestamp fhd
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
  apply_component modstore
  apply_component fhd
  if [[ -f "$STATE/release_applied_modstore_sha" &&
    -f "$STATE/release_applied_fhd_sha" ]] &&
    [[ "$(cat "$STATE/release_applied_modstore_sha")" == "$sha" ]] &&
    [[ "$(cat "$STATE/release_applied_fhd_sha")" == "$sha" ]]; then
    printf '%s\n' "$sha" >"$STATE/release_applied_sha"
  else
    rm -f "$STATE/release_applied_sha"
  fi
  date -u +%s >"$STATE/release_apply_last_success"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
