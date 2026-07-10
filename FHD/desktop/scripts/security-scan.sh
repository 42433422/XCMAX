#!/usr/bin/env bash
# 桌面端 electronegativity 安全扫描本地脚本(与 CI 一致)。
# 用法:
#   bash scripts/security-scan.sh                 # 默认 HIGH 门禁
#   bash scripts/security-scan.sh --gate-severity medium
#   bash scripts/security-scan.sh --no-build      # 跳过 tsc(若 dist/ 已是最新)
#
# 依赖: Node 20+, npm。脚本会自动本地安装 electronegativity 到临时目录(不污染 node_modules)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DESKTOP_DIR}/../.." && pwd)"
PARSER="${REPO_ROOT}/.github/scripts/parse-electronegativity-csv.js"
SUPPRESSIONS="${REPO_ROOT}/.github/electronegativity-suppressions.json"
SCAN_TIMEOUT_SECONDS="${ELECTRONEGATIVITY_TIMEOUT_SECONDS:-420}"

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  node - "${timeout_seconds}" "$@" <<'NODE'
const { spawn } = require('node:child_process')

const timeoutSeconds = Number(process.argv[2])
const command = process.argv.slice(3)
if (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0 || command.length === 0) {
  console.error('[scan] invalid timeout wrapper arguments')
  process.exit(2)
}

const child = spawn(command[0], command.slice(1), { stdio: 'inherit' })
let timedOut = false
const timer = setTimeout(() => {
  timedOut = true
  console.error(`[scan] command timed out after ${timeoutSeconds}s: ${command[0]}`)
  child.kill('SIGTERM')
  const killTimer = setTimeout(() => child.kill('SIGKILL'), 5_000)
  killTimer.unref()
}, timeoutSeconds * 1_000)

child.once('error', error => {
  clearTimeout(timer)
  console.error(`[scan] failed to start ${command[0]}: ${error.message}`)
  process.exit(127)
})
child.once('exit', (code, signal) => {
  clearTimeout(timer)
  if (timedOut) process.exit(124)
  if (signal) {
    console.error(`[scan] command terminated by ${signal}: ${command[0]}`)
    process.exit(1)
  }
  process.exit(code ?? 1)
})
NODE
}

GATE_SEVERITY="high"
NO_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --gate-severity)
      GATE_SEVERITY="$2"
      shift 2
      ;;
    --gate-severity=*)
      GATE_SEVERITY="${arg#*=}"
      shift
      ;;
    --no-build)
      NO_BUILD=1
      shift
      ;;
    -h|--help)
      echo "用法: bash scripts/security-scan.sh [--gate-severity high|medium|low] [--no-build]"
      exit 0
      ;;
  esac
done

echo "[scan] desktop dir: ${DESKTOP_DIR}"
echo "[scan] gate severity: ${GATE_SEVERITY}"
echo "[scan] per-format timeout: ${SCAN_TIMEOUT_SECONDS}s"

NODE_COMPATIBLE="$(node -p 'const [major, minor] = process.versions.node.split(".").map(Number); Number(major > 22 || (major === 22 && minor >= 12))')"
if [ "${NODE_COMPATIBLE}" -ne 1 ]; then
  echo "[scan] ERROR: Electron 41.10.1 toolchain requires Node 22.12+; current: $(node --version)" >&2
  echo "[scan] Switch to the CI/runtime Node version before running this release gate." >&2
  exit 2
fi

# 1. 确保依赖
if [ ! -d "${DESKTOP_DIR}/node_modules" ]; then
  echo "[scan] installing desktop deps..."
  (cd "${DESKTOP_DIR}" && npm ci)
fi

# 2. 构建 TS
if [ "${NO_BUILD}" -eq 0 ]; then
  echo "[scan] building TypeScript..."
  (cd "${DESKTOP_DIR}" && npm run build)
fi

# 3. 安装 electronegativity 到临时目录(避免污染 devDependencies)
EN_TMP="$(mktemp -d)"
trap 'rm -rf "${EN_TMP}"' EXIT
echo "[scan] installing electronegativity to ${EN_TMP}..."
(cd "${EN_TMP}" && npm init -y >/dev/null 2>&1 && npm install @doyensec/electronegativity@1.10.3 --no-audit --no-fund >/dev/null 2>&1)
EN_CMD=("${EN_TMP}/node_modules/.bin/electronegativity")
if [ ! -x "${EN_CMD[0]}" ]; then
  # .bin 软链可能在某些环境失败,直接用 node 调用
  EN_CMD=(node "${EN_TMP}/node_modules/@doyensec/electronegativity/dist/index.js")
fi

# Electronegativity 1.10.3 的 Electron release 元数据请求没有 timeout；GitHub
# CDN 半开连接会让扫描永久挂起。对锁定版本的临时依赖补上请求超时，仍保留
# release 安全修复检查；离线时该检查按上游设计降级，其余静态检查继续执行。
EN_RELEASE_CHECK="${EN_TMP}/node_modules/@doyensec/electronegativity/dist/finder/checks/GlobalChecks/AvailableSecurityFixesGlobalCheck.js"
node - "${EN_RELEASE_CHECK}" <<'NODE'
const fs = require('node:fs')
const file = process.argv[2]
let source = fs.readFileSync(file, 'utf8')
const replacements = [
  [
    "_got2.default.head('https://raw.githubusercontent.com/electron/releases/master/index.json')",
    "_got2.default.head('https://raw.githubusercontent.com/electron/releases/master/index.json', { timeout: { request: 15000 } })"
  ],
  [
    "(0, _got2.default)('https://raw.githubusercontent.com/electron/releases/master/index.json', { responseType: 'json' })",
    "(0, _got2.default)('https://raw.githubusercontent.com/electron/releases/master/index.json', { responseType: 'json', timeout: { request: 15000 } })"
  ]
]
for (const [needle, replacement] of replacements) {
  if (!source.includes(needle)) {
    console.error(`[scan] unsupported Electronegativity release-check shape: ${needle}`)
    process.exit(2)
  }
  source = source.replace(needle, replacement)
}
fs.writeFileSync(file, source)
NODE

# 4. 准备干净扫描目录
SCAN_DIR="$(mktemp -d)"
trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}"' EXIT
echo "[scan] preparing clean scan target: ${SCAN_DIR}"
rsync -a --delete \
  --exclude='node_modules' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='coverage' \
  --exclude='.vitest-cache' \
  --exclude='*.log' \
  --exclude='release/' \
  "${DESKTOP_DIR}/" "${SCAN_DIR}/"

# 把 dist 复制回去(AST 检查需要 .js)
if [ -d "${DESKTOP_DIR}/dist" ]; then
  mkdir -p "${SCAN_DIR}/dist"
  cp -r "${DESKTOP_DIR}/dist/." "${SCAN_DIR}/dist/"
fi

# 5. 跑扫描(CSV + SARIF)。CI 可指定持久目录供 artifact/SARIF 上传；
# 本地默认仍使用临时目录并在退出时清理。
if [ -n "${ELECTRONEGATIVITY_REPORT_DIR:-}" ]; then
  REPORT_DIR="${ELECTRONEGATIVITY_REPORT_DIR}"
  mkdir -p "${REPORT_DIR}"
  rm -f "${REPORT_DIR}/electronegativity.csv" "${REPORT_DIR}/electronegativity.sarif"
  trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}"' EXIT
else
  REPORT_DIR="$(mktemp -d)"
  trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}" "${REPORT_DIR}"' EXIT
fi

echo "[scan] running electronegativity (CSV)..."
if ! run_with_timeout "${SCAN_TIMEOUT_SECONDS}" "${EN_CMD[@]}" -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.csv" -r -v false; then
  echo "[scan] ERROR: Electronegativity CSV scan failed; refusing an empty false-green report." >&2
  exit 3
fi
if [ ! -s "${REPORT_DIR}/electronegativity.csv" ]; then
  echo "[scan] ERROR: Electronegativity produced no CSV report." >&2
  exit 3
fi

echo "[scan] running electronegativity (SARIF)..."
if ! run_with_timeout "${SCAN_TIMEOUT_SECONDS}" "${EN_CMD[@]}" -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.sarif" -r -v false; then
  echo "[scan] ERROR: Electronegativity SARIF scan failed." >&2
  exit 3
fi
if [ ! -s "${REPORT_DIR}/electronegativity.sarif" ]; then
  echo "[scan] ERROR: Electronegativity produced no SARIF report." >&2
  exit 3
fi

echo "[scan] report dir: ${REPORT_DIR}"
echo "[scan] CSV preview:"
head -20 "${REPORT_DIR}/electronegativity.csv"

# 6. 解析+门禁
echo "[scan] parsing & gating..."
if [ -f "${SUPPRESSIONS}" ]; then
  node "${PARSER}" "${REPORT_DIR}/electronegativity.csv" \
    --gate-severity "${GATE_SEVERITY}" \
    --suppressions "${SUPPRESSIONS}"
else
  node "${PARSER}" "${REPORT_DIR}/electronegativity.csv" \
    --gate-severity "${GATE_SEVERITY}"
fi
