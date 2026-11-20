#!/usr/bin/env bash
set -euo pipefail
# Credentials are written only by the execution step, after every installer exits.
if [[ "${1:-install}" == configure ]]; then
  if [[ "${DEVFLEET_FORCE_OPENCODE:-0}" == 1 ]]; then
    node --input-type=module -e "import { assertOpenCodeHost } from './scripts/autonomy/runtime_tools/opencode_agent.mjs'; assertOpenCodeHost();"
    exit 0
  fi
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
if not auth and not os.environ.get('CODEX_API_KEY'):
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
  exit 0
fi
[[ "${1:-install}" == install ]] || { echo 'Unknown Para preparation phase'; exit 1; }
# Scrubbing only npm's child environment leaves same-user parent credentials exposed.
for name in PARA_PLATFORM_GATEWAY_KEY PARA_PLATFORM_GATEWAY_KEYS_JSON PARA_CODEX_AUTH_JSON \
  PARA_CODEX_CONFIG_TOML PARA_CODEX_API_KEY CODEX_API_KEY OPENAI_API_KEY OPENCODE_API_KEY \
  PARA_PLATFORM_APPROVED_KEYRING DEVFLEET_DEVICE_TOKEN MODSTORE_PARA_DISPATCH_TOKEN \
  GITHUB_TOKEN GH_TOKEN CI_COMMIT_TOKEN GITHUB_PERSONAL_ACCESS_TOKEN; do
  [[ -z "${!name:-}" ]] || { echo 'Dependency installation requires a credential-free step'; exit 1; }
done
dependencies=scripts/autonomy/runtime_tools/github_executor_deps/codex
if [[ "${DEVFLEET_FORCE_OPENCODE:-0}" == 1 ]]; then
  [[ "${PARA_PLATFORM_POOL:-0}" == 1 ]] || { echo 'OpenCode GitHub execution requires platform model admission'; exit 1; }
  node --input-type=module - <<'JS'
import { assertOpenCodeHost, openCodeGatewayUrl } from './scripts/autonomy/runtime_tools/opencode_agent.mjs';
assertOpenCodeHost();
openCodeGatewayUrl(process.env);
if (process.platform !== 'linux' || process.arch !== 'x64' || !process.report.getReport().header.glibcVersionRuntime) {
  throw new Error('The GitHub OpenCode lock requires the Ubuntu 22.04 x64 runner');
}
JS
  if ! command -v bwrap >/dev/null || ! command -v socat >/dev/null || ! command -v rg >/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends bubblewrap socat ripgrep
  fi
  dependencies=scripts/autonomy/runtime_tools/github_executor_deps/opencode
else
  locked_version=$(node -p "require('./$dependencies/package.json').dependencies['@openai/codex']")
  [[ "${PARA_CODEX_VERSION:-}" == "$locked_version" ]] || {
    echo "PARA_CODEX_VERSION must match the reviewed dependency lock ($locked_version); update both lock files before changing it"
    exit 1
  }
fi
mkdir -p "$RUNNER_TEMP/para-worker"
cp scripts/autonomy/runtime_tools/*.mjs "$RUNNER_TEMP/para-worker/"
cp "$dependencies/package.json" "$dependencies/package-lock.json" "$RUNNER_TEMP/para-worker/"
# No package lifecycle may execute before later steps receive model credentials.
npm ci --prefix "$RUNNER_TEMP/para-worker" --ignore-scripts --include=optional --no-audit --no-fund
node --input-type=module - <<'JS'
import { execFileSync } from 'node:child_process';
import { accessSync, constants, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const root = join(process.env.RUNNER_TEMP, 'para-worker');
const packages = join(root, 'node_modules');
const locked = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).dependencies;
let executable = join(packages, '.bin', 'codex'), expected = 'codex-cli ' + locked['@openai/codex'];
if (process.env.DEVFLEET_FORCE_OPENCODE === '1') {
  const name = 'opencode-linux-x64-baseline';
  const manifest = JSON.parse(readFileSync(join(packages, name, 'package.json'), 'utf8'));
  if (manifest.name !== name || manifest.version !== locked[name]
      || !manifest.os?.includes(process.platform) || !manifest.cpu?.includes(process.arch)) {
    throw new Error('OpenCode native package does not match the reviewed platform/version');
  }
  executable = join(packages, name, 'bin', 'opencode');
  expected = locked[name];
  const { openCodeSandboxEntry } = await import(pathToFileURL(join(root, 'opencode_agent.mjs')));
  const sandbox = openCodeSandboxEntry({});
  if (!sandbox) throw new Error('The fixed OpenCode sandbox runtime is unavailable');
  accessSync(join(dirname(sandbox), '..', 'vendor', 'seccomp', process.arch, 'apply-seccomp'), constants.X_OK);
  for (const [command, flag] of [['bwrap', '--version'], ['socat', '-V'], ['rg', '--version']]) {
    execFileSync(command, [flag], { stdio: 'ignore', timeout: 15000 });
  }
}
accessSync(executable, constants.X_OK);
if (execFileSync(executable, ['--version'], { encoding: 'utf8', timeout: 30000 }).trim() !== expected) {
  throw new Error('The installed Para executor version does not match the reviewed lock');
}
JS
