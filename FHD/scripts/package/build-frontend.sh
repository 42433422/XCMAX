#!/usr/bin/env bash
# 前端唯一构建入口：把 `frontend/` 一次性构建成 `templates/vue-dist`。
#
# 这是 Web 与桌面端「单次构建、双端共享」的 SSOT 构建点：
#   - 桌面端 build-backend.sh 默认复用这里产出的 templates/vue-dist（不再各自重建）
#   - Web 端 fhd-push-frontend-dist.sh 推送的也是这份 templates/vue-dist
# 因此同一版本发布时，网页端与桌面端内嵌的是字节级同一份前端。
#
# 用法（在 FHD 根目录）:
#   bash scripts/package/build-frontend.sh [enterprise|personal|generic]
#
# 环境变量:
#   XCAGI_PRODUCT_SKU    SKU（enterprise/personal），默认 enterprise
#   XCAGI_EDITION        edition，默认按 SKU 映射（enterprise=full, personal=minimal, 其他=generic）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

SKU="${1:-${XCAGI_PRODUCT_SKU:-enterprise}}"
case "${SKU}" in
  personal) EDITION="${XCAGI_EDITION:-minimal}" ; VITE_SKU=personal ;;
  enterprise) EDITION="${XCAGI_EDITION:-full}" ; VITE_SKU=enterprise ;;
  generic) EDITION="${XCAGI_EDITION:-generic}" ; VITE_SKU=generic ;;
  *)
    echo "[err] SKU must be personal|enterprise|generic, got: ${SKU}" >&2
    exit 1
    ;;
esac

VUE_DIST="$ROOT/templates/vue-dist"
if [[ -d "$ROOT/frontend/node_modules" ]] || [[ -z "${SKIP_FRONTEND_INSTALL:-}" ]]; then
  (cd frontend && [ -d node_modules ] || npm install)
fi

echo "========== Building frontend (sku=${SKU}, edition=${EDITION}) =========="
case "${EDITION}" in
  minimal) (cd frontend && VITE_XCAGI_PRODUCT_SKU="${VITE_SKU}" VITE_XCAGI_EDITION=minimal npm run build:minimal) ;;
  generic) (cd frontend && VITE_XCAGI_PRODUCT_SKU="${VITE_SKU}" VITE_XCAGI_EDITION=generic npm run build:generic) ;;
  *)       (cd frontend && VITE_XCAGI_PRODUCT_SKU="${VITE_SKU}" VITE_XCAGI_EDITION=full npm run build:full) ;;
esac

# 校验唯一前端产物存在且含 Vite 内容 hash（供两端共享与缓存失效判断）。
[[ -f "$VUE_DIST/index.html" ]] || {
  echo "[err] frontend build did not produce $VUE_DIST/index.html" >&2
  exit 1
}
HASH="$(grep -oE 'index-[A-Za-z0-9_-]+\.js' "$VUE_DIST/index.html" | head -1 || echo 'unknown')"
echo "[ok] templates/vue-dist ready (${HASH}) -> 桌面端 PyInstaller 内嵌 + Web 端推送共用"
printf '{"sku":"%s","edition":"%s","index":"%s"}\n' "${SKU}" "${EDITION}" "${HASH}" > "$ROOT/build/vue-dist-identity.json"