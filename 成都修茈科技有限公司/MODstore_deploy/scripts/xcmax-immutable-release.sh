#!/usr/bin/env bash
# Build and atomically promote one exact XCMAX commit on the production host.
# The source checkout is only an object mirror; running services use /opt/xcmax/current.
set -euo pipefail

SOURCE_ROOT="${XCMAX_SOURCE_ROOT:-/root/XCMAX}"
RELEASE_BASE="${XCMAX_RELEASE_BASE:-/opt/xcmax}"
RELEASES_DIR="${RELEASE_BASE%/}/releases"
CURRENT_LINK="${XCMAX_CURRENT_LINK:-${RELEASE_BASE}/current}"
CLI_LAUNCHER_PATH="${XCMAX_CLI_LAUNCHER_PATH:-/usr/local/bin/xcmax-terminal}"
RUNTIME_DIR="${MODSTORE_RUNTIME_DIR:-${RELEASE_BASE}/runtime}"
SITE_LINK="${XCMAX_SITE_LINK:-/root/成都修茈科技有限公司}"
PUBLIC_SITE_STATE_DIR="${XCMAX_PUBLIC_SITE_STATE_DIR:-/var/lib/xcmax-public}"
ENV_DIR="${MODSTORE_ENV_DIR:-/etc/xcmax}"
ENV_FILE="${MODSTORE_ENV_FILE:-${ENV_DIR}/modstore.env}"
SCHEDULER_ENV_FILE="${MODSTORE_SCHEDULER_ENV_FILE:-${ENV_DIR}/modstore-scheduler.env}"
TARGET_SHA="${XCMAX_TARGET_SHA:-${1:-}}"
PRODUCT_VERSION="${XCMAX_PRODUCT_VERSION:-1.0.0.1}"
RELEASE_ID="xcagi-${PRODUCT_VERSION}-${TARGET_SHA}"
GITHUB_REPOSITORY_SLUG="${XCMAX_GITHUB_REPOSITORY:-}"
SITE_SUBDIR="成都修茈科技有限公司"
MODSTORE_SUBDIR="${SITE_SUBDIR}/MODstore_deploy"
LOCK_FILE="${XCMAX_RELEASE_LOCK:-/run/lock/xcmax-immutable-release.lock}"
HEALTH_URL="${MODSTORE_DEPLOY_HEALTH_URL:-http://127.0.0.1:9999/api/health}"
SCHEDULER_HEALTH_URL="${MODSTORE_SCHEDULER_HEALTH_URL:-http://127.0.0.1:9990/api/health}"
PUBLIC_HEALTH_URL="${MODSTORE_PUBLIC_HEALTH_URL:-https://xiu-ci.com/api/health}"
RELEASES_TO_KEEP="${XCMAX_RELEASES_TO_KEEP:-4}"

log() { printf '[xcmax-release] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

resolve_java_home() {
  local candidate=""
  local java_bin=""

  if [[ -n "${JAVA_HOME:-}" && -x "${JAVA_HOME}/bin/java" ]]; then
    export PATH="${JAVA_HOME}/bin:${PATH}"
    return 0
  fi

  for candidate in \
    /usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64 \
    /usr/lib/jvm/java-17-* \
    /usr/lib/jvm/java-17-openjdk*; do
    if [[ -x "${candidate}/bin/java" ]]; then
      export JAVA_HOME="$candidate"
      export PATH="${JAVA_HOME}/bin:${PATH}"
      log "resolved Java 17 runtime at $JAVA_HOME"
      return 0
    fi
  done

  java_bin="$(command -v java 2>/dev/null || true)"
  if [[ -n "$java_bin" ]]; then
    java_bin="$(readlink -f "$java_bin" 2>/dev/null || printf '%s' "$java_bin")"
    candidate="$(dirname "$(dirname "$java_bin")")"
    if [[ -x "${candidate}/bin/java" ]]; then
      export JAVA_HOME="$candidate"
      export PATH="${JAVA_HOME}/bin:${PATH}"
      log "resolved Java runtime from PATH at $JAVA_HOME"
      return 0
    fi
  fi

  fail "Java 17 runtime is required by the active payment service"
}

verify_runtime_mod_compiler() {
  local release_root="$1"
  local node_binary="$2"
  "$node_binary" --input-type=module - "$release_root/FHD/frontend/package.json" <<'JS'
import assert from 'node:assert/strict'
import { readFileSync, realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, relative, resolve, isAbsolute } from 'node:path'

const frontend = dirname(process.argv[2])
const require = createRequire(process.argv[2])
const resolved = realpathSync(require.resolve('esbuild'))
const inside = relative(resolve(frontend, 'node_modules'), resolved)
assert(inside && !inside.startsWith('..') && !isAbsolute(inside), 'esbuild must belong to this release')
const lock = JSON.parse(readFileSync(resolve(frontend, 'package-lock.json'), 'utf8'))
const nativePackage = `@esbuild/${process.platform}-${process.arch}`
const nativePath = realpathSync(require.resolve(`${nativePackage}/bin/esbuild`))
const nativeInside = relative(resolve(frontend, 'node_modules'), nativePath)
assert(nativeInside && !nativeInside.startsWith('..') && !isAbsolute(nativeInside), 'native esbuild must belong to this release')
delete process.env.ESBUILD_BINARY_PATH
const { buildSync, version } = require('esbuild')
assert.equal(version, lock.packages['node_modules/esbuild'].version, 'esbuild must match the frontend lock')
const result = buildSync({
  stdin: { contents: 'export const answer = 21 * 2', loader: 'js' },
  bundle: true, write: false, format: 'esm', platform: 'browser', target: 'es2022',
})
assert.equal(result.outputFiles.length, 1)
const compiled = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].contents).toString('base64'))
assert.equal(compiled.answer, 42, 'native compiler output must execute correctly')
console.log(JSON.stringify({ runtime_mod_compiler: 'ready', esbuild: version, node: process.version }))
JS
}

[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "XCMAX_TARGET_SHA must be a full 40-character commit SHA"
[[ "$PRODUCT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] \
  || fail "XCMAX_PRODUCT_VERSION must be a numeric product version"
[[ -d "$SOURCE_ROOT/.git" ]] || fail "source Git mirror not found: $SOURCE_ROOT"
[[ "$RELEASE_BASE" == /opt/xcmax || "${XCMAX_ALLOW_CUSTOM_RELEASE_BASE:-0}" == 1 ]] \
  || fail "custom release base requires XCMAX_ALLOW_CUSTOM_RELEASE_BASE=1"
[[ "$RELEASE_BASE" == /* ]] || fail "XCMAX_RELEASE_BASE must be an absolute path"
[[ "$CLI_LAUNCHER_PATH" == /* ]] || fail "XCMAX_CLI_LAUNCHER_PATH must be an absolute path"
[[ "$RUNTIME_DIR" == /* ]] || fail "MODSTORE_RUNTIME_DIR must be an absolute path"
[[ "$RELEASES_TO_KEEP" =~ ^[0-9]+$ ]] && (( RELEASES_TO_KEEP >= 2 )) \
  || fail "XCMAX_RELEASES_TO_KEEP must be an integer greater than or equal to 2"
if [[ -n "$GITHUB_REPOSITORY_SLUG" ]] \
  && ! [[ "$GITHUB_REPOSITORY_SLUG" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  fail "XCMAX_GITHUB_REPOSITORY must be an owner/repository slug when set"
fi

install -d -m 755 "$RELEASES_DIR"
install -d -m 700 "$RUNTIME_DIR"
install -d -m 700 "$ENV_DIR"
install -d -m 755 "$PUBLIC_SITE_STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another immutable release is active"

canonical_path() {
  python3 - "$1" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
}

release_manifest_matches_directory() {
  local release_root="$1"
  local expected_sha="$2"
  python3 - "$release_root/.xcmax-release.json" "$expected_sha" <<'PY'
import json
import sys

path, expected_sha = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if payload.get("git_sha") == expected_sha else 1)
PY
}

prune_releases() {
  local releases_root=""
  local candidate=""
  local candidate_root=""
  local candidate_sha=""
  local protected_root=""
  local is_protected=0
  local kept=0
  local removed=0
  local -a ordered_releases=()
  local -a protected_releases=("$@")

  releases_root="$(canonical_path "$RELEASES_DIR")"
  while IFS= read -r -d '' candidate; do
    ordered_releases+=("$candidate")
  done < <(
    python3 - "$RELEASES_DIR" <<'PY'
import os
import re
import sys

root = sys.argv[1]
items = []
for name in os.listdir(root):
    if not re.fullmatch(r"[0-9a-f]{40}", name):
        continue
    path = os.path.join(root, name)
    if os.path.isdir(path) and not os.path.islink(path):
        items.append((os.stat(path).st_mtime_ns, path))
for _, path in sorted(items, reverse=True):
    sys.stdout.buffer.write(os.fsencode(path) + b"\0")
PY
  )

  # Reserve retention slots for rollback-critical releases before choosing the
  # newest unprotected releases. This keeps the configured limit meaningful
  # even when the current or target release is older than recent candidates.
  for candidate in "${ordered_releases[@]}"; do
    candidate_sha="${candidate##*/}"
    candidate_root="$(canonical_path "$candidate")"
    if [[ "${candidate_root%/*}" != "$releases_root" ]] \
        || [[ ! "$candidate_sha" =~ ^[0-9a-f]{40}$ ]] \
        || [[ -L "$candidate" ]] \
        || ! release_manifest_matches_directory "$candidate_root" "$candidate_sha"; then
      continue
    fi
    for protected_root in "${protected_releases[@]}"; do
      [[ -n "$protected_root" ]] || continue
      if [[ "$candidate_root" == "$(canonical_path "$protected_root")" ]]; then
        (( kept += 1 ))
        break
      fi
    done
  done

  for candidate in "${ordered_releases[@]}"; do
    candidate_sha="${candidate##*/}"
    candidate_root="$(canonical_path "$candidate")"
    if [[ "${candidate_root%/*}" != "$releases_root" ]] \
        || [[ ! "$candidate_sha" =~ ^[0-9a-f]{40}$ ]] \
        || [[ -L "$candidate" ]] \
        || ! release_manifest_matches_directory "$candidate_root" "$candidate_sha"; then
      log "skipping unverified release directory $candidate_sha"
      continue
    fi

    is_protected=0
    for protected_root in "${protected_releases[@]}"; do
      [[ -n "$protected_root" ]] || continue
      if [[ "$candidate_root" == "$(canonical_path "$protected_root")" ]]; then
        is_protected=1
        break
      fi
    done
    if [[ "$is_protected" == 1 ]]; then
      continue
    fi
    if (( kept < RELEASES_TO_KEEP )); then
      (( kept += 1 ))
      continue
    fi

    chmod -R u+w "$candidate_root"
    rm -rf -- "$candidate_root"
    [[ ! -e "$candidate_root" ]] || fail "failed to prune old release $candidate_sha"
    (( removed += 1 ))
    log "pruned old verified release $candidate_sha"
  done
  log "release retention complete kept=$kept removed=$removed limit=$RELEASES_TO_KEEP"
}

CURRENT_ROOT_BEFORE_BUILD=""
if [[ -L "$CURRENT_LINK" ]]; then
  CURRENT_ROOT_BEFORE_BUILD="$(canonical_path "$CURRENT_LINK")"
fi
prune_releases "$CURRENT_ROOT_BEFORE_BUILD" "$RELEASES_DIR/$TARGET_SHA"
if [[ "${XCMAX_RELEASE_PRUNE_ONLY:-0}" == 1 ]]; then
  log "release prune-only maintenance completed"
  exit 0
fi

git -C "$SOURCE_ROOT" fetch --quiet origin main
git -C "$SOURCE_ROOT" cat-file -e "${TARGET_SHA}^{commit}" \
  || fail "target commit is unavailable after fetch: $TARGET_SHA"
REMOTE_MAIN_SHA="$(git -C "$SOURCE_ROOT" rev-parse origin/main)"
if [[ "$TARGET_SHA" != "$REMOTE_MAIN_SHA" && "${XCMAX_ALLOW_NON_HEAD_SHA:-0}" != 1 ]]; then
  fail "target SHA is not current origin/main (target=$TARGET_SHA origin_main=$REMOTE_MAIN_SHA)"
fi

migrate_env_file() {
  local destination="$1"
  shift
  [[ -f "$destination" ]] && return 0
  local candidate
  for candidate in "$@"; do
    if [[ -f "$candidate" ]]; then
      install -m 600 "$candidate" "$destination"
      log "migrated protected runtime environment to $destination"
      return 0
    fi
  done
  return 1
}

read_env_value() {
  local source="$1"
  local key="$2"
  python3 - "$source" "$key" <<'PY'
import shlex
import sys

path, expected_key = sys.argv[1:]
for raw in open(path, encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != expected_key:
        continue
    parsed = shlex.split(value.strip(), comments=False, posix=True)
    print(" ".join(parsed))
    break
PY
}

# The build imports the production app before promotion. Load only the required
# secret from the protected environment so fail-closed startup validation is real
# without sourcing arbitrary EnvironmentFile content into the deployment shell.
migrate_env_file "$ENV_FILE" \
  "$SOURCE_ROOT/$MODSTORE_SUBDIR/.env" \
  "$SITE_LINK/MODstore_deploy/.env" \
  || fail "no production environment file was found"
migrate_env_file "$SCHEDULER_ENV_FILE" \
  "$SOURCE_ROOT/$MODSTORE_SUBDIR/.env.scheduler" \
  "$SITE_LINK/MODstore_deploy/.env.scheduler" \
  || install -m 600 /dev/null "$SCHEDULER_ENV_FILE"
BUILD_JWT_SECRET="$(read_env_value "$ENV_FILE" MODSTORE_JWT_SECRET)"
[[ -n "$BUILD_JWT_SECRET" ]] || fail "protected production env is missing MODSTORE_JWT_SECRET"
[[ ${#BUILD_JWT_SECRET} -ge 32 ]] || fail "protected production MODSTORE_JWT_SECRET is shorter than 32 characters"
BUILD_DATABASE_URL="$(read_env_value "$ENV_FILE" MODSTORE_DATABASE_URL)"
if [[ -z "$BUILD_DATABASE_URL" ]]; then
  BUILD_DATABASE_URL="$(read_env_value "$ENV_FILE" DATABASE_URL)"
fi
[[ -n "$BUILD_DATABASE_URL" ]] || fail "protected production env is missing MODSTORE_DATABASE_URL or DATABASE_URL"
BUILD_AUTO_PUBLISH_TOKEN="$(read_env_value "$ENV_FILE" MODSTORE_AUTO_PUBLISH_TOKEN)"
[[ -n "$BUILD_AUTO_PUBLISH_TOKEN" ]] || fail "protected production env is missing MODSTORE_AUTO_PUBLISH_TOKEN"
[[ ${#BUILD_AUTO_PUBLISH_TOKEN} -ge 32 ]] || fail "protected production MODSTORE_AUTO_PUBLISH_TOKEN is shorter than 32 characters"
unset BUILD_AUTO_PUBLISH_TOKEN

PAYMENT_SERVICE_PRESENT=0
PAYMENT_JAVA_BIN=/usr/bin/java
if systemctl cat modstore-payment.service >/dev/null 2>&1; then
  PAYMENT_SERVICE_PRESENT=1
  resolve_java_home
  PAYMENT_JAVA_BIN="${JAVA_HOME}/bin/java"
fi

RUNTIME_NODE_BIN="$(command -v node)" || fail "Node.js is required by the private Mod compiler"
RUNTIME_NODE_BIN="$(readlink -f "$RUNTIME_NODE_BIN")"
[[ "$RUNTIME_NODE_BIN" == /* && -x "$RUNTIME_NODE_BIN" ]] \
  || fail "private Mod compiler requires an executable absolute Node.js path"

FINAL_ROOT="${RELEASES_DIR}/${TARGET_SHA}"
if [[ -f "$FINAL_ROOT/.xcmax-release.json" ]]; then
  EXISTING_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_sha"])' "$FINAL_ROOT/.xcmax-release.json")"
  [[ "$EXISTING_SHA" == "$TARGET_SHA" ]] || fail "existing release identity mismatch"
  log "reusing prepared release $TARGET_SHA"
else
  BUILD_ROOT="$(mktemp -d "${RELEASES_DIR}/.${TARGET_SHA}.build.XXXXXX")"
  SOURCE_ARCHIVE="$(mktemp "${RELEASES_DIR}/.${TARGET_SHA}.source.XXXXXX.tar")"
  cleanup_build() { rm -rf -- "$BUILD_ROOT"; rm -f -- "$SOURCE_ARCHIVE"; }
  trap cleanup_build EXIT
  log "extracting exact Git archive $TARGET_SHA"
  git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA" > "$SOURCE_ARCHIVE"
  ARTIFACT_SHA="$(sha256sum "$SOURCE_ARCHIVE" | awk '{print $1}')"
  tar -xf "$SOURCE_ARCHIVE" -C "$BUILD_ROOT"
  rm -f -- "$SOURCE_ARCHIVE"
  DEPLOY_DIR="$BUILD_ROOT/$MODSTORE_SUBDIR"
  [[ -f "$DEPLOY_DIR/pyproject.toml" ]] || fail "MODstore pyproject missing from release"

  log "creating release-specific Python environment"
  python3 -m venv "$DEPLOY_DIR/.venv"
  "$DEPLOY_DIR/.venv/bin/python" -m pip install -q --upgrade pip
  (cd "$DEPLOY_DIR" && .venv/bin/pip install -q -e '.[web,knowledge,evolution-metrics]')
  mkdir -p "$BUILD_ROOT/.runtime-build"
  MODSTORE_ENV=production \
    MODSTORE_JWT_SECRET="$BUILD_JWT_SECRET" \
    MODSTORE_RUNTIME_DIR="$BUILD_ROOT/.runtime-build" \
    "$DEPLOY_DIR/.venv/bin/python" -c 'import fastapi, pytest, pytest_cov, uvicorn, modstore_server.app'
  rm -rf -- "$BUILD_ROOT/.runtime-build"

  log "installing the locked private Mod compiler inside the release"
  command -v npm >/dev/null 2>&1 || fail "npm is required by the private Mod compiler"
  (
    export PATH="$(dirname "$RUNTIME_NODE_BIN"):$PATH"
    npm ci --prefix "$BUILD_ROOT/FHD/frontend" --include=dev --include=optional \
      --ignore-scripts --no-audit --no-fund
  )
  # The real native esbuild binary must work without lifecycle downloads.
  verify_runtime_mod_compiler "$BUILD_ROOT" "$RUNTIME_NODE_BIN" \
    || fail "private Mod compiler is unavailable in the prepared release"

  if [[ -f "$DEPLOY_DIR/market/package-lock.json" ]]; then
    command -v npm >/dev/null 2>&1 || fail "npm is required to build the market"
    log "building market assets inside the release"
    # The browser bundle uses onnxruntime-web.  @huggingface/transformers also
    # declares onnxruntime-node, whose install hook downloads a native release
    # index and fails behind the production network's redirecting proxy.  Keep
    # the immutable build deterministic by skipping dependency lifecycle hooks,
    # then install only the native bindings required by Vite/Rollup/esbuild.
    (
      cd "$DEPLOY_DIR/market"
      npm ci --no-audit --legacy-peer-deps --ignore-scripts
      node scripts/install-native-bindings.mjs
      VITE_PUBLIC_BASE=/market/ npm run build
    )
    [[ -f "$DEPLOY_DIR/market/dist/index.html" ]] || fail "market build produced no index.html"
  fi

  if [[ "$PAYMENT_SERVICE_PRESENT" == 1 ]]; then
    command -v mvn >/dev/null 2>&1 || fail "mvn is required by the active payment service"
    log "packaging the CI-tested Java payment service"
    (cd "$DEPLOY_DIR/java_payment_service" && mvn -B -q -DskipTests package)
    [[ -f "$DEPLOY_DIR/java_payment_service/target/payment-service-1.0.0.jar" ]] \
      || fail "payment service jar missing after build"
  fi

  TREE_SHA="$(git -C "$SOURCE_ROOT" rev-parse "${TARGET_SHA}^{tree}")"
  python3 - "$BUILD_ROOT/.xcmax-release.json" "$TARGET_SHA" "$TREE_SHA" "$ARTIFACT_SHA" "$PRODUCT_VERSION" "$RELEASE_ID" <<'PY'
import datetime
import json
import sys

path, git_sha, tree_sha, artifact_sha, product_version, release_id = sys.argv[1:]
payload = {
    "artifact_sha256": artifact_sha,
    "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "git_sha": git_sha,
    "git_tree": tree_sha,
    "product_version": product_version,
    "release_id": release_id,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
  chmod -R a-w "$BUILD_ROOT"
  mv "$BUILD_ROOT" "$FINAL_ROOT"
  trap - EXIT
fi
unset BUILD_JWT_SECRET

# mktemp creates the build root with mode 0700. The release stays immutable,
# but the public-site symlink is served by an unprivileged nginx worker, so the
# release root itself must remain traversable after both build and reuse paths.
chmod 0555 "$FINAL_ROOT"

DEPLOY_DIR="$FINAL_ROOT/$MODSTORE_SUBDIR"
verify_runtime_mod_compiler "$FINAL_ROOT" "$RUNTIME_NODE_BIN" \
  || fail "private Mod compiler verification failed before promotion"
EXPECTED_ARTIFACT_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact_sha256"])' "$FINAL_ROOT/.xcmax-release.json")"
[[ "$EXPECTED_ARTIFACT_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "release artifact SHA256 is invalid"

# Apply the exact release's schema before switching the public/runtime symlinks.
# The helper verifies and stamps the last known pre-Alembic production baseline
# before applying newer revisions, then proves every declared head is recorded.
# A migration failure therefore leaves the currently served release untouched.
log "applying database migrations for $TARGET_SHA"
(
  cd "$DEPLOY_DIR"
  MODSTORE_DATABASE_URL="$BUILD_DATABASE_URL" .venv/bin/python scripts/upgrade_database.py
)
unset BUILD_DATABASE_URL

# Move the legacy inline SECRET_KEY into the protected environment without logging it.
LEGACY_SECRET_DROPIN="/etc/systemd/system/modstore.service.d/zz-secret-key.conf"
if [[ -f "$LEGACY_SECRET_DROPIN" ]]; then
  python3 - "$LEGACY_SECRET_DROPIN" "$ENV_FILE" <<'PY'
import os
import shlex
import sys

source, destination = sys.argv[1:]
values = {}
for raw in open(source, encoding="utf-8"):
    raw = raw.strip()
    if not raw.startswith("Environment="):
        continue
    for token in shlex.split(raw.removeprefix("Environment=")):
        if "=" in token:
            key, value = token.split("=", 1)
            if key == "SECRET_KEY":
                values[key] = value
if values:
    lines = open(destination, encoding="utf-8").read().splitlines()
    lines = [line for line in lines if not line.startswith("SECRET_KEY=")]
    lines.append("SECRET_KEY=" + values["SECRET_KEY"])
    temporary = destination + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
PY
  install -m 600 "$LEGACY_SECRET_DROPIN" "${ENV_DIR}/legacy-zz-secret-key.conf.backup"
  rm -f -- "$LEGACY_SECRET_DROPIN"
  log "migrated legacy inline service secret into protected env"
fi

if [[ ! -L "$CURRENT_LINK" ]]; then
  [[ ! -e "$CURRENT_LINK" ]] || fail "$CURRENT_LINK exists and is not a symlink"
  ln -s "$SOURCE_ROOT" "$CURRENT_LINK"
fi
PREVIOUS_ROOT="$(readlink -f "$CURRENT_LINK")"
[[ -d "$PREVIOUS_ROOT" ]] || fail "current release target is invalid: $PREVIOUS_ROOT"

# Public runtime projections must survive immutable release promotion.  Seed
# the persistent nginx root once from the previous release when available;
# subsequent authenticated founder snapshots update this same external file.
PUBLIC_PROJECTION_PATH="${PUBLIC_SITE_STATE_DIR}/download-founder-autonomy.json"
if [[ ! -f "$PUBLIC_PROJECTION_PATH" ]]; then
  for candidate in \
    "${PREVIOUS_ROOT}/${SITE_SUBDIR}/download-founder-autonomy.json" \
    "${PREVIOUS_ROOT}/${MODSTORE_SUBDIR}/market/public/download-founder-autonomy.json"; do
    if [[ -f "$candidate" ]]; then
      install -m 644 "$candidate" "$PUBLIC_PROJECTION_PATH"
      log "seeded persistent public founder projection"
      break
    fi
  done
fi

if [[ -e "$SITE_LINK" && ! -L "$SITE_LINK" ]]; then
  fail "$SITE_LINK must be a symlink for atomic public-site promotion"
fi

write_service_units() {
  local release_env="${ENV_DIR}/modstore-release.env"
  local release_root=""
  local release_manifest=""
  local release_artifact_sha=""
  release_root="$(readlink -f "$CURRENT_LINK")"
  release_manifest="${release_root}/.xcmax-release.json"
  if [[ -f "$release_manifest" ]]; then
    release_artifact_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("artifact_sha256", ""))' "$release_manifest")"
  fi
  printf 'MODSTORE_GIT_SHA=%s\nMODSTORE_EXPECTED_GIT_SHA=%s\nMODSTORE_DEPLOY_TIER=production\nMODSTORE_RELEASE_MANIFEST=%s/.xcmax-release.json\nMODSTORE_RELEASE_ARTIFACT_SHA256=%s\nMODSTORE_RUNTIME_DIR=%s\nMODSTORE_REPO_ROOT=%s\nXCMAX_MONOREPO_ROOT=%s\nMODSTORE_CAPABILITY_PROPOSAL_REPO=%s\nXCMAX_RELEASE_SHA=%s\nXCMAX_PRODUCT_VERSION=%s\nJAVA_PAYMENT_SERVICE_URL=http://127.0.0.1:8080\n' \
    "$TARGET_SHA" "$TARGET_SHA" "$CURRENT_LINK" "$release_artifact_sha" \
    "$RUNTIME_DIR" "$CURRENT_LINK" "$CURRENT_LINK" "$GITHUB_REPOSITORY_SLUG" \
    "$TARGET_SHA" "$PRODUCT_VERSION" > "${release_env}.tmp"
  printf 'MODSTORE_NODE_EXECUTABLE=%s\n' "$RUNTIME_NODE_BIN" >> "${release_env}.tmp"
  chmod 644 "${release_env}.tmp"
  mv -f "${release_env}.tmp" "$release_env"

  install -d -m 755 /etc/systemd/system/modstore.service.d /etc/systemd/system/modstore-scheduler.service.d
  cat > /etc/systemd/system/modstore.service <<EOF
[Unit]
Description=MODstore FastAPI immutable release
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=${CURRENT_LINK}/${MODSTORE_SUBDIR}
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${release_env}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=MODSTORE_RUN_BACKGROUND_JOBS=0
ExecStart=${CURRENT_LINK}/${MODSTORE_SUBDIR}/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 9999 --workers 4
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/modstore.service.d/99-modstore-deploy-dir.conf <<EOF
[Service]
WorkingDirectory=${CURRENT_LINK}/${MODSTORE_SUBDIR}
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${release_env}
ExecStart=
ExecStart=${CURRENT_LINK}/${MODSTORE_SUBDIR}/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 9999 --workers 4
EOF
  cat > /etc/systemd/system/modstore-scheduler.service <<EOF
[Unit]
Description=MODstore background jobs immutable release
After=network.target modstore.service
[Service]
Type=simple
User=root
WorkingDirectory=${CURRENT_LINK}/${MODSTORE_SUBDIR}
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${SCHEDULER_ENV_FILE}
EnvironmentFile=-${release_env}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=MODSTORE_RUN_BACKGROUND_JOBS=1
ExecStart=${CURRENT_LINK}/${MODSTORE_SUBDIR}/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 9990 --workers 1
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/modstore-scheduler.service.d/99-modstore-deploy-dir.conf <<EOF
[Service]
WorkingDirectory=${CURRENT_LINK}/${MODSTORE_SUBDIR}
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${SCHEDULER_ENV_FILE}
EnvironmentFile=-${release_env}
ExecStart=
ExecStart=${CURRENT_LINK}/${MODSTORE_SUBDIR}/.venv/bin/python -m uvicorn modstore_server.app:app --host 127.0.0.1 --port 9990 --workers 1
EOF

  if [[ "$PAYMENT_SERVICE_PRESENT" == 1 ]]; then
    cat > /etc/systemd/system/modstore-payment.service <<EOF
[Unit]
Description=MODstore Java Payment immutable release
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service
[Service]
Type=simple
WorkingDirectory=${CURRENT_LINK}/${MODSTORE_SUBDIR}/java_payment_service
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${release_env}
ExecStart=${PAYMENT_JAVA_BIN} -jar ${CURRENT_LINK}/${MODSTORE_SUBDIR}/java_payment_service/target/payment-service-1.0.0.jar
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
    install -d -m 755 /etc/systemd/system/modstore-payment.service.d
    cat > /etc/systemd/system/modstore-payment.service.d/10-envfile.conf <<EOF
[Service]
EnvironmentFile=
EnvironmentFile=-${ENV_FILE}
EnvironmentFile=-${release_env}
EOF
  fi
}

install_cli_launcher() {
  local launcher_dir=""
  local launcher_tmp=""
  launcher_dir="$(dirname "$CLI_LAUNCHER_PATH")"
  launcher_tmp="${CLI_LAUNCHER_PATH}.tmp.$$"
  install -d -m 755 "$launcher_dir"
  cat > "$launcher_tmp" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${CURRENT_LINK}/${MODSTORE_SUBDIR}/.venv/bin/python" \
  "${CURRENT_LINK}/${MODSTORE_SUBDIR}/scripts/xcmax_terminal.py" "\$@"
EOF
  chmod 755 "$launcher_tmp"
  mv -f "$launcher_tmp" "$CLI_LAUNCHER_PATH"
}

verify_cli_identity() {
  local cli_payload=""
  cli_payload="$("$CLI_LAUNCHER_PATH" version --json)" || return 1
  CLI_PAYLOAD="$cli_payload" python3 - "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA" <<'PY'
import json
import os
import sys

expected_sha, expected_artifact = sys.argv[1:]
payload = json.loads(os.environ["CLI_PAYLOAD"])
metrics = payload.get("metrics") or {}
assert payload.get("ok") is True
assert payload.get("read_only") is True
assert metrics.get("git_sha") == expected_sha
assert metrics.get("artifact_sha256") == expected_artifact
PY
}

verify_health_identity() {
  local url="$1"
  local expected_sha="$2"
  local expected_artifact="$3"
  local payload
  payload="$(curl --noproxy '*' -fsS --max-time 10 "$url")" || return 1
  HEALTH_PAYLOAD="$payload" EXPECTED_SHA="$expected_sha" \
    EXPECTED_RELEASE_ID="xcagi-${PRODUCT_VERSION}-${expected_sha}" \
    EXPECTED_ARTIFACT="$expected_artifact" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["HEALTH_PAYLOAD"])
expected = os.environ["EXPECTED_SHA"]
expected_release_id = os.environ["EXPECTED_RELEASE_ID"]
expected_artifact = os.environ["EXPECTED_ARTIFACT"]
assert payload.get("ok") is True
assert payload.get("deploy_tier") == "production"
assert payload.get("git_sha") == expected
assert payload.get("release_id") == expected_release_id
assert payload.get("artifact_sha256") == expected_artifact
PY
}

verify_payment_identity() {
  local expected_sha="$1"
  local expected_artifact="$2"
  local payload
  payload="$(curl --noproxy '*' -fsS --max-time 10 http://127.0.0.1:8080/actuator/info)" || return 1
  PAYMENT_INFO_PAYLOAD="$payload" EXPECTED_SHA="$expected_sha" EXPECTED_ARTIFACT="$expected_artifact" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["PAYMENT_INFO_PAYLOAD"])
identity = payload.get("xcmax") if isinstance(payload.get("xcmax"), dict) else {}
assert identity.get("git-sha") == os.environ["EXPECTED_SHA"]
assert identity.get("release-id") == os.environ["EXPECTED_SHA"]
assert identity.get("artifact-sha256") == os.environ["EXPECTED_ARTIFACT"]
PY
}

verify_customer_value_reconciler() {
  local payload
  payload="$(curl --noproxy '*' -fsS --max-time 10 "${SCHEDULER_HEALTH_URL%/api/health}/api/scheduler/runtime?stale_after_seconds=900")" || return 1
  SCHEDULER_RUNTIME_PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["SCHEDULER_RUNTIME_PAYLOAD"])
# This deployment gate owns one authoritative job.  The runtime endpoint's
# global ok/status is intentionally allowed to be degraded by unrelated jobs;
# coupling promotion to it would turn a truthful scheduler warning into a
# release-wide outage even when customer-value reconciliation succeeded.
assert isinstance(payload.get("jobs"), list)
jobs = {
    str(item.get("job_id")): item
    for item in payload.get("jobs") or []
    if isinstance(item, dict)
}
job = jobs.get("customer_value_reconciler") or {}
assert job.get("state") == "healthy"
assert job.get("last_status") == "success"
assert int(job.get("consecutive_failures") or 0) == 0
PY
}

PREVIOUS_SHA=""
PREVIOUS_ARTIFACT_SHA=""
if [[ -f "$PREVIOUS_ROOT/.xcmax-release.json" ]]; then
  PREVIOUS_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("git_sha", ""))' "$PREVIOUS_ROOT/.xcmax-release.json")"
  PREVIOUS_ARTIFACT_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("artifact_sha256", ""))' "$PREVIOUS_ROOT/.xcmax-release.json")"
elif [[ -d "$PREVIOUS_ROOT/.git" ]]; then
  PREVIOUS_SHA="$(git -C "$PREVIOUS_ROOT" rev-parse HEAD 2>/dev/null || true)"
fi
[[ -z "$PREVIOUS_SHA" || "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "previous runtime Git SHA is invalid"

rollback() {
  log "promotion failed; rolling current back to $PREVIOUS_ROOT"
  ln -s "$PREVIOUS_ROOT" "${CURRENT_LINK}.rollback"
  mv -Tf "${CURRENT_LINK}.rollback" "$CURRENT_LINK"
  if [[ -L "$SITE_LINK" ]]; then
    ln -s "${CURRENT_LINK}/${SITE_SUBDIR}" "${SITE_LINK}.rollback"
    mv -Tf "${SITE_LINK}.rollback" "$SITE_LINK"
  fi
  if [[ "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    TARGET_SHA="$PREVIOUS_SHA" write_service_units
  fi
  systemctl daemon-reload
  systemctl restart modstore-payment.service 2>/dev/null || true
  systemctl restart modstore.service modstore-scheduler.service || true
  if [[ "$PREVIOUS_ARTIFACT_SHA" =~ ^[0-9a-f]{64}$ ]]; then
    for _ in $(seq 1 30); do
      verify_health_identity "$HEALTH_URL" "$PREVIOUS_SHA" "$PREVIOUS_ARTIFACT_SHA" && return 0
      sleep 2
    done
    log "ERROR: rollback exact identity verification failed" >&2
    return 1
  fi
  systemctl is-active --quiet modstore.service modstore-scheduler.service
}

ln -s "$FINAL_ROOT" "${CURRENT_LINK}.next"
mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"
ln -s "${CURRENT_LINK}/${SITE_SUBDIR}" "${SITE_LINK}.next"
mv -Tf "${SITE_LINK}.next" "$SITE_LINK"
install_cli_launcher
write_service_units
systemctl daemon-reload
systemctl enable modstore.service modstore-scheduler.service >/dev/null

if [[ "$PAYMENT_SERVICE_PRESENT" == 1 ]]; then
  if ! systemctl restart modstore-payment.service; then
    rollback
    fail "payment service failed to restart"
  fi
  PAYMENT_READY=0
  for _ in $(seq 1 60); do
    if systemctl is-active --quiet modstore-payment.service \
        && curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8080/actuator/health >/dev/null \
        && verify_payment_identity "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA"; then
      PAYMENT_READY=1
      break
    fi
    sleep 2
  done
  if [[ "$PAYMENT_READY" != 1 ]]; then
    rollback
    fail "payment exact-SHA identity verification failed"
  fi
fi

if ! systemctl restart modstore.service modstore-scheduler.service; then
  rollback
  fail "MODstore services failed to restart"
fi

READY=0
for _ in $(seq 1 60); do
  if systemctl is-active --quiet modstore.service modstore-scheduler.service \
      && verify_health_identity "$HEALTH_URL" "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA" \
      && verify_health_identity "$SCHEDULER_HEALTH_URL" "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA"; then
    READY=1
    break
  fi
  sleep 2
done
if [[ "$READY" != 1 ]]; then
  rollback
  fail "exact-SHA local health verification failed"
fi

RECONCILER_READY=0
for _ in $(seq 1 30); do
  if verify_customer_value_reconciler; then
    RECONCILER_READY=1
    break
  fi
  sleep 2
done
if [[ "$RECONCILER_READY" != 1 ]]; then
  rollback
  fail "customer value reconciler did not prove a successful authoritative run"
fi

if ! verify_cli_identity; then
  rollback
  fail "xcmax-terminal exact-SHA identity verification failed"
fi

if [[ -n "$PUBLIC_HEALTH_URL" ]] \
    && ! verify_health_identity "$PUBLIC_HEALTH_URL" "$TARGET_SHA" "$EXPECTED_ARTIFACT_SHA"; then
  rollback
  fail "exact-SHA public health verification failed"
fi
log "release promoted and verified git_sha=$TARGET_SHA root=$FINAL_ROOT"
prune_releases "$FINAL_ROOT" "$PREVIOUS_ROOT" "$(canonical_path "$CURRENT_LINK")"
