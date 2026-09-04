#!/usr/bin/env bash
# 桌面端 electronegativity 安全扫描本地脚本(与 CI 一致)。
# 用法:
#   bash scripts/security-scan.sh                 # 默认 HIGH 门禁
#   bash scripts/security-scan.sh --gate-severity medium
#   bash scripts/security-scan.sh --no-build      # 跳过 tsc(若 dist/ 已是最新)
#
# 依赖: Node 22.12+, npm。脚本会自动本地安装 electronegativity 到临时目录(不污染 node_modules)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DESKTOP_DIR}/../.." && pwd)"
PARSER="${REPO_ROOT}/.github/scripts/parse-electronegativity-csv.js"
SUPPRESSIONS="${REPO_ROOT}/.github/electronegativity-suppressions.json"

GATE_SEVERITY="high"
NO_BUILD=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --gate-severity)
      if [ "$#" -lt 2 ]; then
        echo "[err] --gate-severity requires high|medium|low" >&2
        exit 2
      fi
      GATE_SEVERITY="$2"
      shift 2
      ;;
    --gate-severity=*)
      GATE_SEVERITY="${1#*=}"
      shift 1
      ;;
    --no-build)
      NO_BUILD=1
      shift 1
      ;;
    -h|--help)
      echo "用法: bash scripts/security-scan.sh [--gate-severity high|medium|low] [--no-build]"
      exit 0
      ;;
    *)
      echo "[err] unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "${GATE_SEVERITY}" in
  high|medium|low) ;;
  *) echo "[err] invalid gate severity: ${GATE_SEVERITY}" >&2; exit 2 ;;
esac

NODE_SUPPORTED="$(node -p 'const [a,b]=process.versions.node.split(".").map(Number); Number(a>22 || (a===22 && b>=12))' 2>/dev/null || true)"
if [ "${NODE_SUPPORTED}" != "1" ]; then
  echo "[err] Node.js 22.12+ is required; found: $(node --version 2>/dev/null || echo unavailable)" >&2
  exit 2
fi

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
  EN_COMMAND=(node "${EN_TMP}/node_modules/@doyensec/electronegativity/dist/index.js")
else
  EN_COMMAND=("${EN_BIN}")
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
REPORT_DIR="${ELECTRONEGATIVITY_REPORT_DIR:-$(mktemp -d)}"
mkdir -p "${REPORT_DIR}"
if [ -n "${ELECTRONEGATIVITY_REPORT_DIR:-}" ]; then
  trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}"' EXIT
else
  trap 'rm -rf "${EN_TMP}" "${SCAN_DIR}" "${REPORT_DIR}"' EXIT
fi

echo "[scan] running electronegativity (CSV)..."
if ! "${EN_COMMAND[@]}" -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.csv" -r -v false; then
  echo "[err] Electronegativity CSV scan failed; refusing a synthetic green report" >&2
  exit 1
fi
if [ ! -s "${REPORT_DIR}/electronegativity.csv" ]; then
  echo "[err] Electronegativity CSV report is missing or empty" >&2
  exit 1
fi

echo "[scan] running electronegativity (SARIF)..."
if ! "${EN_COMMAND[@]}" -i "${SCAN_DIR}" -o "${REPORT_DIR}/electronegativity.sarif" -r -v false; then
  echo "[err] Electronegativity SARIF scan failed; refusing a synthetic green report" >&2
  exit 1
fi
if [ ! -s "${REPORT_DIR}/electronegativity.sarif" ] || \
   ! node -e 'const fs=require("node:fs"); const p=process.argv[1]; const r=JSON.parse(fs.readFileSync(p,"utf8")); if(r.version!=="2.1.0"||!Array.isArray(r.runs)) process.exit(1)' "${REPORT_DIR}/electronegativity.sarif"; then
  echo "[err] Electronegativity SARIF report is missing or invalid" >&2
  exit 1
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
