#!/usr/bin/env bash
# Shared immutable-release service, pointer and rollback operations.
# Sourcing this file has no external effects.

log() { printf '[xcmax-release] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

verify_public_pointers() {
  python3 "$POINTER_SYNC" --check --site-root "$1/$SITE_SUBDIR" \
    --published-site-root "$SITE_LINK" \
    --published-hotfix "/var/www/update/releases/stable/enterprise/download-windows-hotfix.json"
}

acquire_publication_lock() {
  mkdir -p "$(dirname "$PUBLICATION_LOCK")"
  exec 8>"$PUBLICATION_LOCK"
  flock -w 60 8 || fail "another public-site publication is active"
}

clear_corp_download_marker() {
  local site="$1/$SITE_SUBDIR" parent
  [[ -d "$site" && "$(readlink -f "$site")" == "$site" ]] || return 1
  for parent in "$site/site" "$site/site/data"; do
    [[ ! -L "$parent" && ( ! -e "$parent" || -d "$parent" ) ]] || return 1
  done
  rm -f -- "$site/site/data/corp-download-deployment.json"
}

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
  printf 'MODSTORE_GIT_SHA=%s\nMODSTORE_EXPECTED_GIT_SHA=%s\nMODSTORE_DEPLOY_TIER=production\nMODSTORE_RELEASE_MANIFEST=%s/.xcmax-release.json\nMODSTORE_RELEASE_ARTIFACT_SHA256=%s\nMODSTORE_RUNTIME_DIR=%s\nMODSTORE_CATALOG_DIR=%s\nMODSTORE_REPO_ROOT=%s\nXCMAX_MONOREPO_ROOT=%s\nMODSTORE_CAPABILITY_PROPOSAL_REPO=%s\nXCMAX_RELEASE_SHA=%s\nXCMAX_PRODUCT_VERSION=%s\nJAVA_PAYMENT_SERVICE_URL=http://127.0.0.1:8080\n' \
    "$TARGET_SHA" "$TARGET_SHA" "$CURRENT_LINK" "$release_artifact_sha" \
    "$RUNTIME_DIR" "$CATALOG_DIR" "$CURRENT_LINK" "$CURRENT_LINK" "$GITHUB_REPOSITORY_SLUG" \
    "$TARGET_SHA" "$PRODUCT_VERSION" > "${release_env}.tmp"
  printf 'MODSTORE_NODE_EXECUTABLE=%s\n' "$RUNTIME_NODE_BIN" >> "${release_env}.tmp"
  printf 'MODMAN_LIBRARY=%s\n' "$LIBRARY_DIR" >> "${release_env}.tmp"
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

verify_health_identity() {
  local url="$1"
  local expected_sha="$2"
  local expected_artifact="$3"
  local expected_release_id="${4:-xcagi-${PRODUCT_VERSION}-${expected_sha}}"
  local payload
  payload="$(curl --noproxy '*' -fsS --max-time 10 "$url")" || return 1
  HEALTH_PAYLOAD="$payload" EXPECTED_SHA="$expected_sha" \
    EXPECTED_RELEASE_ID="$expected_release_id" \
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

rollback() {
  local rollback_link="${CURRENT_LINK}.rollback.$$"
  local site_rollback_link="${SITE_LINK}.rollback.$$"
  if ! verify_public_pointers "$PREVIOUS_ROOT"; then
    log "ERROR: rollback blocked by changed public desktop pointers; operator reconciliation required"
    return 1
  fi
  if ! clear_corp_download_marker "$PREVIOUS_ROOT"; then
    log "ERROR: rollback blocked by an unsafe deployment marker path"
    return 1
  fi
  log "rolling current back to $PREVIOUS_ROOT"
  ln -s "$PREVIOUS_ROOT" "$rollback_link" || return 1
  mv -Tf "$rollback_link" "$CURRENT_LINK" || { rm -f -- "$rollback_link"; return 1; }
  if [[ -L "$SITE_LINK" ]]; then
    ln -s "${CURRENT_LINK}/${SITE_SUBDIR}" "$site_rollback_link" || return 1
    mv -Tf "$site_rollback_link" "$SITE_LINK" || { rm -f -- "$site_rollback_link"; return 1; }
  fi
  if [[ "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    TARGET_SHA="$PREVIOUS_SHA" PRODUCT_VERSION="$PREVIOUS_VERSION" \
      LIBRARY_DIR="$PREVIOUS_LIBRARY_DIR" write_service_units
  fi
  systemctl daemon-reload
  systemctl restart modstore-payment.service 2>/dev/null || true
  systemctl restart modstore.service modstore-scheduler.service || true
  if [[ "$PREVIOUS_ARTIFACT_SHA" =~ ^[0-9a-f]{64}$ ]]; then
    for _ in $(seq 1 30); do
      if verify_health_identity "$HEALTH_URL" "$PREVIOUS_SHA" "$PREVIOUS_ARTIFACT_SHA" \
          "$PREVIOUS_RELEASE_ID" \
          && verify_health_identity "$SCHEDULER_HEALTH_URL" "$PREVIOUS_SHA" "$PREVIOUS_ARTIFACT_SHA" \
          "$PREVIOUS_RELEASE_ID"; then
        if [[ -z "$PUBLIC_HEALTH_URL" ]] || verify_health_identity "$PUBLIC_HEALTH_URL" \
            "$PREVIOUS_SHA" "$PREVIOUS_ARTIFACT_SHA" "$PREVIOUS_RELEASE_ID"; then
          return 0
        fi
      fi
      sleep 2
    done
    log "ERROR: rollback exact identity verification failed" >&2
    return 1
  fi
  systemctl is-active --quiet modstore.service modstore-scheduler.service
}
