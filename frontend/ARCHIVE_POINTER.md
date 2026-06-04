# frontend/node_modules（M0 外置）

实体：`~/XCMAX-archives/m0-venv-20260605/FHD/frontend/node_modules-20260605-rebuild`

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-venv-20260605"
cd "$(dirname "$0")"
rm -rf .nm-e2e node_modules
rsync -a "$AR/FHD/frontend/node_modules-20260605-rebuild/" ./.nm-e2e/
ln -sfn .nm-e2e node_modules
```

勿在 `frontend/` 直接 `npm install`（易破坏 Playwright）。
