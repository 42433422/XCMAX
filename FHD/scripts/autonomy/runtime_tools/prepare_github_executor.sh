#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$RUNNER_TEMP/para-worker"
cp scripts/autonomy/runtime_tools/*.mjs "$RUNNER_TEMP/para-worker/"
if [[ "${DEVFLEET_FORCE_OPENCODE:-0}" == 1 ]]; then
  [[ "${PARA_PLATFORM_POOL:-0}" == 1 ]] || { echo 'OpenCode GitHub execution requires platform model admission'; exit 1; }
  node --input-type=module -e "import { openCodeGatewayUrl } from './scripts/autonomy/runtime_tools/opencode_agent.mjs'; openCodeGatewayUrl(process.env)"
  npm install --prefix "$RUNNER_TEMP/para-worker" --package-lock=false "ws@8.18.0" "opencode-ai@1.19.6"
  exit 0
fi
[[ "$PARA_CODEX_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Pin the Para Codex CLI version first'; exit 1; }
npm install --prefix "$RUNNER_TEMP/para-worker" --package-lock=false "ws@8.18.0" "@openai/codex@$PARA_CODEX_VERSION"
python - <<'PY'
import json, os
from pathlib import Path
from urllib.parse import urlsplit

root = Path.home() / '.codex'
root.mkdir(mode=0o700, exist_ok=True)
if os.environ.get('PARA_PLATFORM_POOL') == '1':
    base_url = os.environ.get('PARA_PLATFORM_GATEWAY_URL', '').rstrip('/')
    url = urlsplit(base_url)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or not url.path.endswith('/v1')
            or not (os.environ.get('PARA_PLATFORM_GATEWAY_KEY', '').strip()
                    or os.environ.get('PARA_PLATFORM_GATEWAY_KEYS_JSON', '').strip())):
        raise SystemExit('Para platform Responses endpoint or virtual key is not configured')
    target = root / 'config.toml'
    target.write_text(
        'model_provider = "xcmax-platform"\n'
        '[model_providers.xcmax-platform]\n'
        'name = "XCMAX Platform"\n'
        f'base_url = {json.dumps(base_url)}\n'
        'env_key = "CODEX_API_KEY"\n'
        'wire_api = "responses"\n'
        '[model_providers.volcengine-agent-plan]\n'
        'name = "Volcengine Agent Plan"\n'
        'base_url = "https://ark.cn-beijing.volces.com/api/plan/v3"\n'
        'env_key = "CODEX_API_KEY"\n'
        'wire_api = "responses"\n'
    )
    target.chmod(0o600)
    raise SystemExit(0)

auth = os.environ.get('PARA_CODEX_AUTH_JSON', '')
if not auth and not os.environ.get('PARA_CODEX_API_KEY'):
    raise SystemExit('Para Codex authorization is not configured')
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
