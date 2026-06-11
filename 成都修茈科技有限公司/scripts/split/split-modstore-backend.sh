#!/usr/bin/env bash
# 把 MODstore_deploy 下 Python 后端相关路径抽到独立仓库 modstore-backend。
set -euo pipefail

TARGET="modstore-backend"
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

# 抽出 Python 相关路径，并去掉 MODstore_deploy/ 前缀
git filter-repo \
  --path MODstore_deploy/modstore_server/ \
  --path MODstore_deploy/modman/ \
  --path MODstore_deploy/tests/ \
  --path MODstore_deploy/pyproject.toml \
  --path MODstore_deploy/README.md \
  --path MODstore_deploy/CONTRIBUTING.md \
  --path MODstore_deploy/.gitignore \
  --path MODstore_deploy/.env.example \
  --path MODstore_deploy/.env.production.example \
  --path MODstore_deploy/alembic/ \
  --path MODstore_deploy/alembic.ini \
  --path MODstore_deploy/scripts/python-release.sh \
  --path MODstore_deploy/docs/ \
  --path MODstore_deploy/Dockerfile \
  --path-rename MODstore_deploy/:

echo
echo "[ok] ${OUT_DIR} 已就绪。下一步："
cat <<EOF
  cd ${OUT_DIR}
  git remote add origin git@github.com:<org>/${TARGET}.git
  git push -u origin main
  # 迁移 .github/workflows/ci-backend-python.yml、deploy.yml 并去掉 MODstore_deploy/ 前缀。
  # 把 market/ 与 java_payment_service/ 排除在本仓之外（见 split-modstore-frontend.sh / split-payment-java.sh）。
EOF
