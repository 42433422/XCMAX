#!/usr/bin/env bash
# 把 vibe-coding/ 抽到独立仓库 vibe-coding。
set -euo pipefail

TARGET="vibe-coding"
SRC_PATH="vibe-coding"
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
  # 迁移 .github/workflows/ci-vibe-coding.yml 到新仓库；路径过滤去掉 vibe-coding/ 前缀。
  # 同步注意：vibe-coding/scripts/sync_from_eskill.py 需要处理 eskill-prototype 源路径。
EOF
