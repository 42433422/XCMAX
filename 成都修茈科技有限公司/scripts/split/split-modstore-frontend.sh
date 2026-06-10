#!/usr/bin/env bash
# 把 MODstore_deploy/market/ 抽到独立仓库 modstore-frontend。
set -euo pipefail

TARGET="modstore-frontend"
SRC_PATH="MODstore_deploy/market"
OUT_DIR=".split-out/${TARGET}"

if ! command -v git-filter-repo >/dev/null 2>&1 && ! python3 -c "import git_filter_repo" >/dev/null 2>&1; then
  echo "[err] 未安装 git-filter-repo。请先：pip install git-filter-repo" >&2
  exit 1
fi

if [ -d "${OUT_DIR}" ]; then
  echo "[warn] ${OUT_DIR} 已存在；请先清理"
  exit 2
fi

mkdir -p .split-out
git clone --no-local . "${OUT_DIR}"
cd "${OUT_DIR}"

git filter-repo \
  --path "${SRC_PATH}/" \
  --path-rename "${SRC_PATH}/:"

echo
echo "[ok] ${OUT_DIR} 已就绪。下一步："
cat <<EOF
  cd ${OUT_DIR}
  git remote add origin git@github.com:<org>/${TARGET}.git
  git push -u origin main
  # 迁移 .github/workflows/ci-market.yml、market-live-deploy.yml 并去掉 MODstore_deploy/market/ 前缀。
EOF
