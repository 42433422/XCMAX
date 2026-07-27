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
  for f in styles.css main.js contact-intake.js contact-channels.js visualization.js; do
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
  # Build from the Git worktree. MODSTORE_ROOT may point at the immutable live
  # release, which is published only after this function completes.
  local repo_market_root="${XCMAX_ROOT}/${MODSTORE_PREFIX}/market"
  local logo_src="${repo_market_root}/public/brand-xc-logo.jpg"
  local force_rebuild=false
  mkdir -p "$corp_dir"
  if [[ -f "$logo_src" ]]; then
    cp -af "$logo_src" "${corp_dir}/brand-xc-logo.jpg"
    log "corp-butler brand-xc-logo.jpg 已同步"
  else
    log "WARN: 缺少 ${logo_src}，AI 管家浮球 Logo 将 404"
  fi
  if [[ -f "${MODSTORE_ROOT}/market/public/download-release.json" ]]; then
    cp -af "${MODSTORE_ROOT}/market/public/download-release.json" "${corp_dir}/download-release.json"
  fi
  if [[ -f "${MODSTORE_ROOT}/market/public/download-action-board.json" ]]; then
    cp -af "${MODSTORE_ROOT}/market/public/download-action-board.json" "${corp_dir}/download-action-board.json"
  fi

  # 官网悬浮助手通过 /corp-butler/ 静态目录提供，不能只靠 market/dist。
  # 每次都同步头像，避免旧产物继续引用已不存在或过期的头像文件。
  local avatar_asset
  for avatar_asset in ai-butler-female-avatar-v1.png ai-butler-male-avatar-v1.jpg; do
    if [[ -f "${repo_market_root}/public/${avatar_asset}" ]]; then
      cp -af "${repo_market_root}/public/${avatar_asset}" "${corp_dir}/${avatar_asset}"
      log "corp-butler ${avatar_asset} 已同步"
    else
      log "WARN: 缺少 market/public/${avatar_asset}，官网悬浮助手头像可能 404"
    fi
  done

  if [[ "${XCMAX_FORCE_SITE_PUBLISH:-0}" == "1" ]]; then
    force_rebuild=true
  elif [[ "${REPO_CHANGED:-false}" == true ]] && \
    paths_changed_since "$XCMAX_ROOT" "$OLD_XCMAX_SHA" "$NEW_XCMAX_SHA" \
      "^${MODSTORE_PREFIX}/market/(src/corp-butler/|src/components/floating-agent/|public/(brand-xc-logo|ai-butler-(female|male)-avatar-v1))"; then
    force_rebuild=true
  fi

  if [[ "$force_rebuild" != true && -f "${corp_dir}/corp-butler.js" && -f "${corp_dir}/corp-butler.css" ]]; then
    log "corp-butler 产物已存在（js+css）"
    return 0
  fi
  if [[ "$force_rebuild" == true ]]; then
    log "corp-butler 源码或官网发布已更新，强制重建静态产物"
  fi
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [[ -s "${NVM_DIR}/nvm.sh" ]] && . "${NVM_DIR}/nvm.sh"
  if command -v npm >/dev/null 2>&1; then
    if [[ ! -d "${repo_market_root}/node_modules" ]]; then
      if ! (cd "${repo_market_root}" && npm ci >>"$LOG" 2>&1); then
        log "ERROR: corp-butler 依赖安装失败，终止发布以避免保留旧悬浮助手"
        return 1
      fi
    fi
    if (cd "${repo_market_root}" && npm run build:corp-butler >>"$LOG" 2>&1) && \
       [[ -s "${corp_dir}/corp-butler.js" && -s "${corp_dir}/corp-butler.css" ]]; then
      log "corp-butler 构建完成"
    else
      log "ERROR: corp-butler 构建失败或产物缺失，终止发布以避免保留旧悬浮助手"
      return 1
    fi
  else
    log "ERROR: 缺少 npm，终止发布以避免保留旧悬浮助手"
    return 1
  fi
}

ensure_market_dist() {
  local dist="${MODSTORE_ROOT}/market/dist"
  local idx="${dist}/index.html"
  if [[ -f "$idx" ]]; then
    return 0
  fi
  log "WARN: market/dist 缺失，尝试 npm build"
  if build_market; then
    return 0
  fi
  local bak
  bak="$(ls -dt /root/成都修茈科技有限公司.bak.*/MODstore_deploy/market/dist 2>/dev/null | head -1 || true)"
  if [[ -n "$bak" && -f "${bak}/index.html" ]]; then
    mkdir -p "$(dirname "$dist")"
    rm -rf "$dist"
    cp -a "$bak" "$dist"
    log "已从备份恢复 market/dist: ${bak}"
    return 0
  fi
  log "ERROR: market/dist 仍缺失，/market/ 将 404"
  return 1
}

market_dist_identity_ok() {
  local idx="${MODSTORE_ROOT}/market/dist/index.html"
  [[ -f "$idx" ]] || return 1
  grep -q '<title>XC AGI 市场</title>' "$idx" || return 1
  ! grep -qE 'CEED \| 聚合型视频生成平台|聚合型视频生成平台|index-CeJsc-Ly' "$idx"
}

validate_market_dist_identity() {
  local idx="${MODSTORE_ROOT}/market/dist/index.html"
  [[ -f "$idx" ]] || return 0
  if market_dist_identity_ok; then
    return 0
  fi
  local title
  title="$(sed -n 's/.*<title>\(.*\)<\/title>.*/\1/p' "$idx" | head -1)"
  log "ERROR: market/dist index 身份异常 title=${title:-unknown}，尝试重建市场前端"
  if build_market && market_dist_identity_ok; then
    log "market/dist index 身份已恢复为 XC AGI 市场"
    return 0
  fi
  log "ERROR: market/dist index 身份仍异常，请人工检查是否被外部项目覆盖"
  return 1
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
  # Keep non-ASCII paths literal: quoted C-style paths cannot match the
  # Chinese repository prefixes used by the market and corporate site.
  git -C "$repo" -c core.quotePath=false diff --name-only "$old_sha" "$new_sha" | grep -qE "$pattern"
}

sync_site_static() {
  local old_sha="$1"
  local new_sha="$2"
  if [[ -z "$old_sha" || "$old_sha" == "$new_sha" ]]; then
    return 0
  fi
  local changed
  changed="$(git -C "$XCMAX_ROOT" -c core.quotePath=false diff --name-only "$old_sha" "$new_sha" \
    | grep "^${SITE_SUBDIR}/" | grep -v "^${MODSTORE_PREFIX}/" || true)"
  if [[ -z "$changed" ]]; then
    log "官网静态无变更"
    return 0
  fi
  # 注意：download-action-board.json / download-company-hall.json 由运行时 DB 投影写出，
  # 不要从 git 快照覆盖 live，否则官网会冻在旧业务日。
  local paths=(
    '*.html' 'styles.css' 'main.js' 'contact-intake.js' 'contact-channels.js' 'visualization.js' 'world-will.js'
    'sitemap.xml' 'baidu_urls.txt' 'download-release.json' 'download-action-board.js'
    'images' 'site' 'assets' 'corp-butler' 'partials'
  )
  for p in "${paths[@]}"; do
    git -C "$XCMAX_ROOT" checkout "origin/${BRANCH}" -- "${SITE_SUBDIR}/${p}" >>"$LOG" 2>&1 || true
  done
  publish_site_static_to_live
  log "官网静态文件已同步"
}

# Git checkout updates $XCMAX_ROOT/... only. Production nginx root is usually the
# immutable-release symlink at $SITE_ROOT (/root/成都修茈科技有限公司). Without this
# publish step, homepage/nav fixes never become visible on xiu-ci.com.
publish_site_static_to_live() {
  local git_site="${XCMAX_ROOT}/${SITE_SUBDIR}"
  local live_site
  live_site="$(readlink -f "$SITE_ROOT" 2>/dev/null || printf '%s' "$SITE_ROOT")"
  local git_real
  git_real="$(readlink -f "$git_site" 2>/dev/null || printf '%s' "$git_site")"
  if [[ ! -d "$git_site" ]]; then
    log "WARN: git site tree missing: $git_site"
    return 0
  fi
  if [[ -z "$live_site" || ! -d "$live_site" ]]; then
    log "WARN: live site root missing: $SITE_ROOT"
    return 0
  fi
  if [[ "$live_site" == "$git_real" ]]; then
    log "live site root == git tree，无需二次发布"
    return 0
  fi
  log "发布官网静态到 live root: $live_site"
  chmod u+w "$live_site" 2>/dev/null || true
  mkdir -p "$live_site/partials" "$live_site/assets" "$live_site/corp-butler"
  chmod u+w "$live_site/partials" "$live_site/assets" 2>/dev/null || true
  local f base
  shopt -s nullglob
  for f in "$git_site"/*.html "$git_site"/styles.css "$git_site"/main.js "$git_site"/contact-intake.js \
           "$git_site"/contact-channels.js \
           "$git_site"/visualization.js "$git_site"/world-will.js \
           "$git_site"/sitemap.xml "$git_site"/baidu_urls.txt "$git_site"/download-release.json \
           "$git_site"/download-action-board.js; do
    [[ -e "$f" ]] || continue
    base="$(basename "$f")"
    chmod u+w "$live_site/$base" 2>/dev/null || true
    cp -f "$f" "$live_site/$base"
  done
  shopt -u nullglob
  if [[ -d "$git_site/partials" ]]; then
    cp -af "$git_site/partials/." "$live_site/partials/"
  fi
  if [[ -d "$git_site/assets" ]]; then
    cp -af "$git_site/assets/." "$live_site/assets/"
  fi
  if [[ -d "$git_site/corp-butler" ]]; then
    cp -af "$git_site/corp-butler/." "$live_site/corp-butler/"
  fi
  # Keep release root traversable for unprivileged nginx after chmod u+w above.
  chmod a+rx "$live_site" 2>/dev/null || true
  log "live root 静态发布完成"
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

ensure_scheduler_unit() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  local unit="/etc/systemd/system/modstore-scheduler.service"
  local tmpl="${MODSTORE_ROOT}/systemd/modstore-scheduler.service.example"
  if systemctl is-enabled modstore-scheduler >/dev/null 2>&1 && [[ -f "$unit" ]]; then
    return 0
  fi
  if [[ ! -f "$tmpl" ]]; then
    log "WARN: 缺少 scheduler 模板 ${tmpl}，无法自愈安装"
    return 1
  fi
  log "scheduler unit 缺失/未启用，从模板安装并 enable"
  sed "s#/root/modstore-git/MODstore_deploy#${MODSTORE_ROOT}#g" "$tmpl" >"$unit"
  systemctl daemon-reload >>"$LOG" 2>&1 || true
  if systemctl enable --now modstore-scheduler >>"$LOG" 2>&1; then
    log "modstore-scheduler 已 enable --now"
  else
    log "ERROR: modstore-scheduler enable --now 失败"
    return 1
  fi
}

restart_app_services() {
  ensure_scheduler_unit || log "WARN: scheduler 自愈未完成"
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

# Hotfix hold: when production release is pinned to a SHA that is not current
# origin/main (e.g. PR-not-yet-merged restore), do not overwrite live static /
# market dist from the older git tip every cron tick.
live_release_sha=""
if [[ -f /etc/xcmax/modstore-release.env ]]; then
  live_release_sha="$(
    awk -F= '$1=="MODSTORE_GIT_SHA" || $1=="MODSTORE_EXPECTED_GIT_SHA" {print $2; exit}'       /etc/xcmax/modstore-release.env | tr -d " \r"
  )"
fi
if [[ -n "${live_release_sha}" ]]; then
  remote_main_sha="$(git -C "$XCMAX_ROOT" rev-parse "origin/${BRANCH}" 2>/dev/null || true)"
  if [[ -n "${remote_main_sha}" && "${live_release_sha}" != "${remote_main_sha}"       && "${XCMAX_FORCE_AUTO_UPDATE:-0}" != "1" ]]; then
    log "hotfix hold: live release ${live_release_sha:0:12} != origin/${BRANCH} ${remote_main_sha:0:12}; skip overwrite"
    exit 0
  fi
fi

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
  log "首次单仓 state，强制发布当前官网静态到 live root"
  publish_site_static_to_live
else
  # Branch deploys / manual reruns may leave SHA unchanged while live root is stale.
  if [[ "${XCMAX_FORCE_SITE_PUBLISH:-0}" == "1" ]]; then
    log "XCMAX_FORCE_SITE_PUBLISH=1，强制发布官网静态到 live root"
    publish_site_static_to_live
  fi
fi

if [[ "$REPO_CHANGED" != true ]]; then
  sync_market_public_assets
  sync_corp_pages_to_dist_fallback
  sync_corp_butler_assets
  publish_site_static_to_live
  ensure_market_dist || true
  validate_market_dist_identity || true
  log "XCMAX 无新提交，已检查 public→dist / corp-butler / market/dist"
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
# corp-butler is built into the Git worktree; publish it after the build so
# nginx's immutable live root never keeps a stale bundle.
publish_site_static_to_live
ensure_market_dist || true
validate_market_dist_identity || true

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
  if [[ -f /etc/nginx/conf.d/xiu-ci.com.conf ]]; then
    log "canonical xiu-ci.com.conf 已存在，跳过会产生 server_name 冲突的 standalone corp root vhost"
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
