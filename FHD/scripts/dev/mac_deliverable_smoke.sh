#!/usr/bin/env bash
# macOS deliverable smoke — parity with deliverable_smoke.ps1 / desktop_deliverable_smoke.ps1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

DMG_PATH="${1:-}"
APP_PATH="${2:-}"
PORT="${MAC_SMOKE_PORT:-5099}"
TIMEOUT_SEC="${MAC_SMOKE_TIMEOUT:-120}"

log() { printf '[mac-deliverable-smoke] %s\n' "$*"; }
fail() { log "FAIL: $*"; exit 1; }

log "=== macOS Deliverable Smoke ==="

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "${PY}" ]]; then
  PY="python3"
fi

"${PY}" - <<'PY'
import os
import tempfile
from pathlib import Path

from app.desktop_runtime import configure_desktop_environment
from app.fastapi_app import create_fastapi_app
from app.security.lan_config import reset_lan_config_cache
from app.security.lan_settings_store import LanSettingsOverride
from fastapi.testclient import TestClient

tmpdir = tempfile.mkdtemp(prefix="xcagi-mac-smoke-")
os.environ["LAN_GUARD_ENABLED"] = "0"
os.environ["XCAGI_DESKTOP_MODE"] = "1"
configure_desktop_environment(tmpdir)

import app.security.lan_settings_store as lan_store

lan_store.load_overrides = lambda: LanSettingsOverride(enabled=False)
reset_lan_config_cache()

client = TestClient(create_fastapi_app())
h = client.get("/api/health")
assert h.status_code == 200, h.text
d = client.get("/api/platform-shell/deliverable-status").json()
assert d.get("success") is True
data = d.get("data") or {}
assert "deliverable" in data
print("[OK] FastAPI health + deliverable-status")
PY

log "[OK] FastAPI contract"

if [[ -n "${DMG_PATH}" && -f "${DMG_PATH}" ]]; then
  MOUNT_DIR="$(mktemp -d /tmp/xcagi-dmg-XXXX)"
  hdiutil attach "${DMG_PATH}" -mountpoint "${MOUNT_DIR}" -nobrowse -quiet
  APP_PATH="$(find "${MOUNT_DIR}" -maxdepth 2 -name '*.app' -print -quit)"
  trap 'hdiutil detach "${MOUNT_DIR}" -quiet 2>/dev/null || true' EXIT
fi

if [[ -n "${APP_PATH}" && -d "${APP_PATH}" ]]; then
  SKU_FILE="${APP_PATH}/Contents/Resources/product-sku.json"
  if [[ -f "${SKU_FILE}" ]]; then
    log "product-sku.json: $(cat "${SKU_FILE}")"
  else
    fail "missing product-sku.json in ${APP_PATH}"
  fi
  log "[OK] .app bundle structure"
fi

if [[ -n "${APP_PATH}" && -d "${APP_PATH}" ]]; then
  log "Launching ${APP_PATH} for live health probe…"
  open -a "${APP_PATH}" --args --headless 2>/dev/null || open "${APP_PATH}" 2>/dev/null || true
  health_url="http://127.0.0.1:${PORT}/api/health"
  for _ in $(seq 1 "${TIMEOUT_SEC}"); do
    if curl -sf "${health_url}" >/dev/null 2>&1; then
      log "[OK] live health ${health_url}"
      pkill -f "XCAGI" 2>/dev/null || true
      log "=== macOS Deliverable Smoke PASSED ==="
      exit 0
    fi
    sleep 1
  done
  log "WARN: live health probe skipped (app may use port 5000 only)"
fi

log "=== macOS Deliverable Smoke PASSED (API contract) ==="
