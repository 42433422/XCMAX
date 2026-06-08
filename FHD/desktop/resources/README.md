# 桌面端安装资源

构建 NSIS 安装包与 Electron 壳所需文件由脚本自动生成，**无需**手工拷贝：

- `scripts/package/generate-desktop-resources.py`：生成 `installer-*.bmp`、`icon.png`、`icon.ico`；在 macOS 上还会生成 `icon.icns`。
- `electron-builder` 的 `beforePack`（`build/before-pack.cjs`）在每次打包前会执行上述脚本（并确保已安装 Pillow）。

品牌图标（推荐）：将 PNG 放在 [`desktop/branding/app-icon-source.png`](../branding/app-icon-source.png)，再执行 `npm run dist:win` 或 `scripts/package/build-installer.ps1`；`beforePack` 会调用 `generate-desktop-resources.py` 生成 `icon.ico` / `icon.png`、NSIS 侧栏与顶栏位图。

若需临时覆盖生成结果，也可直接替换 `resources/` 下同名文件后重新打包。
