#!/usr/bin/env bash
# 服务器 cron：从 XCMAX 单仓自动更新官网静态、market/dist、MODstore 栈（非 FHD tarball 链）。
#
# 环境变量:
#   XCMAX_ROOT               单仓根，默认 /root/XCMAX
#   XCMAX_SITE_ROOT          官网逻辑根（symlink），默认 /root/成都修茈科技有限公司
#   XCMAX_MODSTORE_ROOT      MODstore 部署目录，默认 $XCMAX_SITE_ROOT/MODstore_deploy
#   XCMAX_GIT_BRANCH         默认 main
#   XCMAX_GIT_RESET_HARD     1 时 pull 失败则 reset --hard origin/<branch>
#   XCMAX_SKIP_DOCKER        1 跳过 docker compose
#   XCMAX_SKIP_JAVA_BUILD    1 跳过 Maven 支付服务构建
#   XCMAX_DEPLOY_LOG         默认 /var/log/xcmax-site-auto-update.log
#   XCMAX_AUTO_UPDATE_LOCK   默认 /tmp/xcmax-site-auto-update.lock
set -euo pipefail

XCMAX_ROOT="${XCMAX_ROOT:-/root/XCMAX}"
SITE_SUBDIR="成都修茈科技有限公司"
SITE_ROOT="${XCMAX_SITE_ROOT:-/root/${SITE_SUBDIR}}"
MODSTORE_ROOT="${XCMAX_MODSTORE_ROOT:-${SITE_ROOT}/MODstore_deploy}"
BRANCH="${XCMAX_GIT_BRANCH:-main}"
LOG="${XCMAX_DEPLOY_LOG:-/var/log/xcmax-site-auto-update.log}"
LOCK="${XCMAX_AUTO_UPDATE_LOCK:-/tmp/xcmax-site-auto-update.lock}"
STATE_DIR="${XCMAX_STATE_DIR:-/var/lib/xcmax-site-auto-update}"
MODSTORE_PREFIX="${SITE_SUBDIR}/MODstore_deploy"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$LOG"
}

exec 9>"$LOCK"
if ! flock -n 9; then
  log "另一实例运行中，跳过"
  exit 0
fi

mkdir -p "$STATE_DIR"

git_sync_repo() {
  local dir="$1"
  local label="$2"
  if [[ ! -d "$dir/.git" ]]; then
    log "WARN: $label 不是 git 仓库: $dir"
    return 1
  fi
  git -C "$dir" fetch origin "$BRANCH" >>"$LOG" 2>&1 || {
    log "ERROR: $label git fetch 失败"
    return 1
  }
  local remote_sha local_sha
  remote_sha="$(git -C "$dir" rev-parse "origin/${BRANCH}")"
  local_sha="$(git -C "$dir" rev-parse HEAD)"
  if [[ "$remote_sha" == "$local_sha" ]]; then
    log "$label 已是最新 sha=${local_sha:0:12}"
    echo "$local_sha"
    return 0
  fi
  log "$label 发现更新 ${local_sha:0:12} -> ${remote_sha:0:12}"
  if git -C "$dir" merge --ff-only "origin/${BRANCH}" >>"$LOG" 2>&1; then
    log "$label fast-forward 成功"
  elif [[ "${XCMAX_GIT_RESET_HARD:-0}" == "1" ]]; then
    log "$label ff-only 失败，执行 reset --hard origin/${BRANCH}"
    git -C "$dir" reset --hard "origin/${BRANCH}" >>"$LOG" 2>&1
  else
    log "ERROR: $label 无法 fast-forward（工作区脏？设 XCMAX_GIT_RESET_HARD=1 强制对齐）"
    return 1
  fi
  echo "$remote_sha"
}

# Vite build 会把 public/ 根文件复制到 dist/；服务器常无法 npm build，需手动同步避免 SPA 回退 index.html
sync_market_public_assets() {
  local pub="${MODSTORE_ROOT}/market/public"
  local dist="${MODSTORE_ROOT}/market/dist"
  if [[ ! -d "$pub" || ! -d "$dist" ]]; then
    return 0
  fi
  local n=0
  while IFS= read -r -d '' f; do
    cp -af "$f" "$dist/"
    n=$((n + 1))
  done < <(find "$pub" -maxdepth 1 -type f -print0)
  if [[ "$n" -gt 0 ]]; then
    log "market public 根资源已同步到 dist（${n} 个文件）"
  fi
}

# 误将 market/dist 作整站 root 时，把官网 *.html 同步进 dist（跳过 index.html，保留 Vue 入口）
sync_corp_pages_to_dist_fallback() {
  local corp="${SITE_ROOT}"
  local dist="${MODSTORE_ROOT}/market/dist"
  if [[ ! -d "$corp" || ! -d "$dist" ]]; then
    return 0
  fi
  local n=0
  for f in "$corp"/*.html; do
    [[ -f "$f" ]] || continue
    local base
    base="$(basename "$f")"
    if [[ "$base" == "index.html" ]]; then
      continue
    fi
    cp -af "$f" "${dist}/"
    n=$((n + 1))
  done
  for f in styles.css main.js contact-intake.js; do
    if [[ -f "${corp}/${f}" ]]; then
      cp -af "${corp}/${f}" "${dist}/"
      n=$((n + 1))
    fi
  done
  for f in sunbird-logo.png partner-emblem-logo.png xiu-ci-logo.png; do
    if [[ -f "${corp}/assets/${f}" ]]; then
      cp -af "${corp}/assets/${f}" "${dist}/assets/"
      n=$((n + 1))
    fi
  done
  if [[ -d "${corp}/assets" ]]; then
    mkdir -p "${dist}/assets"
    cp -af "${corp}/assets/." "${dist}/assets/"
    n=$((n + 1))
  fi
  if [[ "$n" -gt 0 ]]; then
    log "官网静态已镜像到 market/dist（${n} 项，developer.html 等；勿长期依赖此路径）"
  fi
}

# 官网 widget：nginx alias /corp-butler/ → 成都修茈科技有限公司/corp-butler/
sync_corp_butler_assets() {
  local corp_dir="${XCMAX_ROOT}/${SITE_SUBDIR}/corp-butler"
  local logo_src="${MODSTORE_ROOT}/market/public/brand-xc-logo.jpg"
  mkdir -p "$corp_dir"
  if [[ -f "$logo_src" ]]; then
    cp -af "$logo_src" "${corp_dir}/brand-xc-logo.jpg"
  fi
  if [[ -f "${MODSTORE_ROOT}/market/public/download-release.json" ]]; then
    cp -af "${MODSTORE_ROOT}/market/public/download-release.json" "${corp_dir}/download-release.json"
  fi
  if [[ -f "${corp_dir}/corp-butler.js" ]]; then
    log "corp-butler 产物已存在"
    return 0
  fi
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [[ -s "${NVM_DIR}/nvm.sh" ]] && . "${NVM_DIR}/nvm.sh"
  if command -v npm >/dev/null 2>&1 && [[ -d "${MODSTORE_ROOT}/market/node_modules" ]]; then
    if (cd "${MODSTORE_ROOT}/market" && npm run build:corp-butler >>"$LOG" 2>&1); then
      log "corp-butler 构建完成"
    else
      log "WARN: corp-butler 构建失败，官网 AI 管家可能 404"
    fi
  else
    log "WARN: 缺少 node_modules，跳过 corp-butler 构建（需本机 build 后 scp）"
  fi
}

build_market() {
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [[ -s "${NVM_DIR}/nvm.sh" ]] && . "${NVM_DIR}/nvm.sh"
  if ! command -v npm >/dev/null 2>&1; then
    log "ERROR: 未找到 npm，跳过 market build"
    return 1
  fi
  (
    cd "${MODSTORE_ROOT}/market"
    export VITE_PUBLIC_BASE=/market/
    if [[ -f package-lock.json ]]; then
      npm ci >>"$LOG" 2>&1 || npm install >>"$LOG" 2>&1
    else
      npm install >>"$LOG" 2>&1
    fi
    npm run build >>"$LOG" 2>&1
  )
  log "market dist 构建完成"
}

paths_changed_since() {
  local repo="$1"
  local old_sha="$2"
  local new_sha="$3"
  local pattern="$4"
  if [[ -z "$old_sha" || "$old_sha" == "$new_sha" ]]; then
    return 0
  fi
  git -C "$repo" diff --name-only "$old_sha" "$new_sha" | grep -qE "$pattern"
}

sync_site_static() {
  local old_sha="$1"
  local new_sha="$2"
  if [[ -z "$old_sha" || "$old_sha" == "$new_sha" ]]; then
    return 0
  fi
  local changed
  changed="$(git -C "$XCMAX_ROOT" diff --name-only "$old_sha" "$new_sha" \
    | grep "^${SITE_SUBDIR}/" | grep -v "^${MODSTORE_PREFIX}/" || true)"
  if [[ -z "$changed" ]]; then
    log "官网静态无变更"
    return 0
  fi
  local paths=(
    '*.html' 'styles.css' 'main.js' 'contact-intake.js'
    'sitemap.xml' 'baidu_urls.txt' 'download-release.json'
    'images' 'site' 'assets' 'corp-butler'
  )
  for p in "${paths[@]}"; do
    git -C "$XCMAX_ROOT" checkout "origin/${BRANCH}" -- "${SITE_SUBDIR}/${p}" >>"$LOG" 2>&1 || true
  done
  log "官网静态文件已同步"
}

pip_sync() {
  local venv="${MODSTORE_ROOT}/.venv"
  if [[ ! -x "${venv}/bin/pip" ]]; then
    python3 -m venv "$venv"
  fi
  # shellcheck disable=SC1091
  source "${venv}/bin/activate"
  pip install -q -U pip
  pip install -q -e "${MODSTORE_ROOT}[web,knowledge]" >>"$LOG" 2>&1
  log "Python 依赖已同步"
}

java_payment_build() {
  if [[ "${XCMAX_SKIP_JAVA_BUILD:-0}" == "1" ]]; then
    return 0
  fi
  local jdir="${MODSTORE_ROOT}/java_payment_service"
  if [[ ! -f "${jdir}/pom.xml" ]]; then
    return 0
  fi
  if ! command -v mvn >/dev/null 2>&1; then
    log "WARN: 未找到 mvn，跳过 Java 支付构建"
    return 0
  fi
  (cd "$jdir" && mvn -q -DskipTests package >>"$LOG" 2>&1)
  log "Java payment-service 已构建"
}

docker_stack_up() {
  if [[ "${XCMAX_SKIP_DOCKER:-0}" == "1" ]]; then
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    log "WARN: 未找到 docker，跳过 compose"
    return 0
  fi
  (
    cd "$MODSTORE_ROOT"
    docker compose --profile app up -d --build postgres redis rabbitmq payment-service >>"$LOG" 2>&1 || \
      docker compose up -d postgres redis rabbitmq >>"$LOG" 2>&1 || true
  )
  log "docker compose 基础设施已 up"
}

restart_app_services() {
  local units=(modstore modstore-payment modstore-scheduler fhd-sandbox)
  for u in "${units[@]}"; do
    if systemctl is-enabled "$u" >/dev/null 2>&1 || systemctl list-unit-files "$u.service" --no-legend 2>/dev/null | grep -q .; then
      if systemctl restart "$u" >>"$LOG" 2>&1; then
        log "systemctl restart $u ok"
      else
        log "WARN: systemctl restart $u 失败"
      fi
    fi
  done
}

OLD_XCMAX_SHA=""
if [[ -f "${STATE_DIR}/xcmax.sha" ]]; then
  OLD_XCMAX_SHA="$(tr -d '[:space:]' <"${STATE_DIR}/xcmax.sha")"
elif [[ -f "${STATE_DIR}/modstore.sha" ]]; then
  # 迁移前双仓 state：首次单仓运行视为有更新
  OLD_XCMAX_SHA=""
fi

NEW_XCMAX_SHA=""
if NEW_XCMAX_SHA="$(git_sync_repo "$XCMAX_ROOT" "XCMAX")"; then
  :
else
  log "XCMAX git 同步失败，终止"
  exit 1
fi

REPO_CHANGED=false
if [[ -z "$OLD_XCMAX_SHA" || "$OLD_XCMAX_SHA" != "$NEW_XCMAX_SHA" ]]; then
  REPO_CHANGED=true
fi

if [[ "$REPO_CHANGED" == true && -n "$OLD_XCMAX_SHA" ]]; then
  sync_site_static "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA"
elif [[ "$REPO_CHANGED" == true && -z "$OLD_XCMAX_SHA" ]]; then
  log "首次单仓 state，跳过增量官网 checkout"
fi

if [[ "$REPO_CHANGED" != true ]]; then
  sync_market_public_assets
  sync_corp_pages_to_dist_fallback
  sync_corp_butler_assets
  log "XCMAX 无新提交，已检查 public→dist / corp-butler 静态资源"
  exit 0
fi

if paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" "^${MODSTORE_PREFIX}/market/"; then
  if build_market; then
    :
  else
    log "WARN: market build 失败，回退 public→dist 同步"
    sync_market_public_assets
  fi
else
  sync_market_public_assets
fi

if paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" "^${MODSTORE_PREFIX}/(modstore_server/|pyproject\\.toml|requirements)"; then
  pip_sync || log "WARN: pip sync 失败"
fi

if paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" "^${MODSTORE_PREFIX}/java_payment_service/"; then
  java_payment_build || log "WARN: java build 失败"
fi

if paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" "^${MODSTORE_PREFIX}/(docker-compose\\.yml|Dockerfile)"; then
  docker_stack_up
fi

# 首次迁移或空 old sha：确保依赖与服务就绪
if [[ -z "$OLD_XCMAX_SHA" ]]; then
  pip_sync || log "WARN: pip sync 失败"
  if [[ -d "${MODSTORE_ROOT}/market" ]]; then
    if build_market; then
      :
    else
      sync_market_public_assets
    fi
  fi
fi

sync_market_public_assets
sync_corp_pages_to_dist_fallback
sync_corp_butler_assets

restart_app_services

sync_nginx_corp_root() {
  local conf_src="${SITE_ROOT}/nginx-xiu-ci-root.conf"
  if [[ ! -f "$conf_src" ]]; then
    return 0
  fi
  if ! command -v nginx >/dev/null 2>&1; then
    log "WARN: 未找到 nginx，跳过 corp root 配置"
    return 0
  fi
  install -m 644 "$conf_src" /etc/nginx/conf.d/xiu-ci-corp-root.conf
  if nginx -t >>"$LOG" 2>&1; then
    systemctl reload nginx >>"$LOG" 2>&1 || true
    log "nginx xiu-ci-corp-root.conf 已安装并重载"
  else
    log "WARN: nginx -t 失败，未 reload"
  fi
}

if paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" \
  '^'"${SITE_SUBDIR}"'/nginx-xiu-ci.*\.conf$'; then
  sync_nginx_corp_root
fi

echo "$NEW_XCMAX_SHA" >"${STATE_DIR}/xcmax.sha"
# 兼容旧监控
echo "$NEW_XCMAX_SHA" >"${STATE_DIR}/modstore.sha"
echo "$NEW_XCMAX_SHA" >"${STATE_DIR}/site.sha"
log "xcmax-site 自动更新完成 xcmax_sha=${NEW_XCMAX_SHA:0:12}"
