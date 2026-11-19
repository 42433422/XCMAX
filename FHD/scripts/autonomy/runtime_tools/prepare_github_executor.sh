#!/usr/bin/env bash
set -euo pipefail
[[ "$PARA_CODEX_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Pin the Para Codex CLI version first'; exit 1; }
mkdir -p "$RUNNER_TEMP/para-worker"
cp scripts/autonomy/runtime_tools/*.mjs "$RUNNER_TEMP/para-worker/"
npm install --prefix "$RUNNER_TEMP/para-worker" --package-lock=false "ws@8.18.0" "@openai/codex@$PARA_CODEX_VERSION"
python - <<'PY'
import json, os
from pathlib import Path
auth = os.environ.get('PARA_CODEX_AUTH_JSON', '')
if not auth and not os.environ.get('PARA_CODEX_API_KEY'):
    raise SystemExit('Para Codex authorization is not configured')
root = Path.home() / '.codex'
root.mkdir(mode=0o700, exist_ok=True)
if auth:
    json.loads(auth)
    target = root / 'auth.json'
    target.write_text(auth)
    target.chmod(0o600)
config = os.environ.get('PARA_CODEX_CONFIG_TOML', '')
if config:
    target = root / 'config.toml'
    target.write_text(config)
    target.chmod(0o600)
PY
