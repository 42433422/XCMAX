# frontend/node_modules（M0 外置）

实体目录：`~/XCMAX-archives/m0-venv-20260605/FHD/frontend/node_modules-20260605-rebuild`

## 恢复（E2E / vitest）

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-venv-20260605"
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/frontend"
rm -rf .nm-e2e node_modules
rsync -a "$AR/FHD/frontend/node_modules-20260605-rebuild/" ./.nm-e2e/
ln -sfn .nm-e2e node_modules
```

**勿**在 `frontend/` 直接 `npm install`（易破坏 Playwright 树）。缺 `zod` 时向归档副本补 pack 后再链。

## E2E 全栈

```bash
# 终端 A
E2E_VITE_MOCK_API=1 npm run dev -- --port 5001 --host 127.0.0.1
# 终端 B
E2E_VITE_MOCK_API=1 E2E_FULL_STACK=1 npm run test:e2e:p0
```
