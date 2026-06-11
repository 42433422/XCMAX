#!/usr/bin/env bash
# 把根层营销官网（*.html + styles.css + main.js + assets/ + site/ + new/）抽到
# 独立仓库 xiuci-marketing-site。
set -euo pipefail

TARGET="xiuci-marketing-site"
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

# 仅保留根层静态营销页相关资源；排除 src/、MODstore_deploy/、vibe-coding/ 等
git filter-repo \
  --path-glob '*.html' \
  --path styles.css \
  --path main.js \
  --path assets/ \
  --path site/ \
  --path new/ \
  --path deploy/nginx-default.conf

echo
echo "[ok] ${OUT_DIR} 已就绪。下一步："
cat <<EOF
  cd ${OUT_DIR}
  git remote add origin git@github.com:<org>/${TARGET}.git
  git push -u origin main
  # 迁移 .github/workflows/ci-marketing-site.yml 作为新仓库唯一 CI。
EOF
