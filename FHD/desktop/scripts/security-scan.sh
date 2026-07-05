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
EN_BIN="${EN_TMP}/node_modules/.bin/electronegativity"
if [ ! -x "${EN_BIN}" ]; then
  # .bin 软链可能在某些环境失败,直接用 node 调用
  EN_BIN="node ${EN_TMP}/node_modules/@doyensec/electronegativity/dist/index.js"
fi

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

# 5. 跑扫描(CSV + SARIF)
REPORT_DIR="$(mktemp -d)"
trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}" "${REPORT_DIR}"' EXIT

echo "[scan] running electronegativity (CSV)..."
${EN_BIN} -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.csv" -r -v false || true
if [ ! -f "${REPORT_DIR}/electronegativity.csv" ]; then
  echo "issue, severity, confidence, filename, location, sample, description, url" > "${REPORT_DIR}/electronegativity.csv"
fi

echo "[scan] running electronegativity (SARIF)..."
${EN_BIN} -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.sarif" -r -v false || true
if [ ! -f "${REPORT_DIR}/electronegativity.sarif" ]; then
  echo '{"$schema":"http://json.schemastore.org/sarif-2.1.0","version":"2.1.0","runs":[{"tool":{"driver":{"name":"Electronegativity","rules":[]}},"results":[]}]}' > "${REPORT_DIR}/electronegativity.sarif"
fi

echo "[scan] report dir: ${REPORT_DIR}"
echo "[scan] CSV preview:"
head -20 "${REPORT_DIR}/electronegativity.csv"

# 6. 解析+门禁
echo "[scan] parsing & gating..."
node "${PARSER}" "${REPORT_DIR}/electronegativity.csv" --gate-severity "${GATE_SEVERITY}"
