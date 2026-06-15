#!/usr/bin/env bash
# 把 MODstore_deploy/java_payment_service/ 抽到独立仓库 modstore-payment-java。
# 抽出产物：.split-out/modstore-payment-java（干净历史）。
# 仅 P0 风险组件先拆；Python/Market/Java 三条链在生产中版本漂移的风险最大。
set -euo pipefail

TARGET="modstore-payment-java"
SRC_PATH="MODstore_deploy/java_payment_service"
OUT_DIR=".split-out/${TARGET}"

if ! command -v git-filter-repo >/dev/null 2>&1 && ! python3 -c "import git_filter_repo" >/dev/null 2>&1; then
  echo "[err] 未安装 git-filter-repo。请先：pip install git-filter-repo" >&2
  exit 1
fi

echo "[info] 准备抽出 ${SRC_PATH} → ${OUT_DIR}"
if [ -d "${OUT_DIR}" ]; then
  echo "[warn] ${OUT_DIR} 已存在；请先清理或用其他目录"
  exit 2
fi

mkdir -p .split-out
git clone --no-local . "${OUT_DIR}"
cd "${OUT_DIR}"

# 保留历史中所有涉及目标路径的提交，并把路径前缀剥掉
git filter-repo \
  --path "${SRC_PATH}/" \
  --path-rename "${SRC_PATH}/:"

echo
echo "[ok] ${OUT_DIR} 已就绪。下一步："
cat <<EOF
  cd ${OUT_DIR}
  # 1) 在 GitHub 新建空仓库 ${TARGET}
  git remote add origin git@github.com:<org>/${TARGET}.git
  git push -u origin main
  # 2) 把本仓库 .github/workflows/ci-payment-java.yml 与 deploy-payment-java.yml
  #    复制到新仓库 .github/workflows/，并删除 paths 过滤中的 MODstore_deploy 前缀。
  # 3) 在新仓库 Settings 配置 Secrets/Variables（参照 release-contracts.md）。
EOF
