# XCMAX 历史与大文件归档指针

尽调 **工作区**（`Desktop/XCMAX`）不含下列实体目录；仅保留 `ARCHIVE_POINTER.md` 占位与恢复说明。

## 离线包（本机默认）

| 包 | 路径 | 说明 |
|----|------|------|
| 历史 `_archive` | `~/XCMAX-archives/xcmax-archive-202606/` | 根级历史快照（约 40GB） |
| M0 仓根卫生 | `~/XCMAX-archives/m0-20260605/` | 部署 zip、成都业务包等（~1.7GB） |
| **M0 FHD 大文件** | `~/XCMAX-archives/m0-fhd-bulk-20260605/` | models / installer / XcagiInstaller 等 |
| **M0 FHD 可重建依赖** | `~/XCMAX-archives/m0-venv-20260605/` | `.venv` / `.venv-mypy` / `frontend/node_modules`（~1.6GB） |
| **子仓 `.git` 备份（2026-06-08）** | `~/XCMAX-archives/nested-git-backup-20260608/` | 迁根仓 SSOT 前的 `FHD.git` / `MODstore_deploy.git` / `WechatDecrypt.git` |

### M0 已外置（工作区内为指针）

| 工作区路径 | 归档实体 |
|------------|----------|
| `FHD/XCAGI/models` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/models` |
| `FHD/XCAGI/installer` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/installer` |
| `FHD/XCAGI/distillation` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/distillation` |
| `FHD/tools/XcagiInstaller` | `.../m0-fhd-bulk-20260605/FHD/tools/XcagiInstaller` |
| `FHD/tools/XcagiDownloader` | `.../m0-fhd-bulk-20260605/FHD/tools/XcagiDownloader` |
| `FHD/.venv` | `.../m0-venv-20260605/FHD/.venv-20260605-rebuild` |
| `FHD/.venv-mypy` | `.../m0-venv-20260605/FHD/.venv-mypy` |
| `FHD/frontend/node_modules` | `.../m0-venv-20260605/FHD/frontend/node_modules-20260605-rebuild` |

## 恢复示例

```bash
export VR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-venv-20260605"
rsync -a "$VR/FHD/.venv-20260605-rebuild/" "$(pwd)/FHD/.venv/"
rsync -a "$VR/FHD/.venv-mypy/" "$(pwd)/FHD/.venv-mypy/"
rsync -a "$VR/FHD/frontend/node_modules-20260605-rebuild/" "$(pwd)/FHD/frontend/node_modules/"
```

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
rsync -a "$AR/FHD/XCAGI/models/" "$(pwd)/FHD/XCAGI/models/"
```

## 运维脚本

```bash
bash FHD/scripts/move_archive_off_workspace.sh   # 根 _archive → xcmax-archive-202606
```

校验和：`~/XCMAX-archives/MANIFEST.txt`

**体积说明**（2026-06-05）：`du -sh Desktop/XCMAX` 约 **9.7G**（清 frontend 与归档重复的 `node_modules` 残留 ~2.6G 后；`FHD/.venv` **ln -s** `m0-venv-20260605`；含 `FHD/.git` ~**9.4G**）；尽调交付树（不含 `.git`）约 **~0.3G**。可重建依赖在 `m0-venv-20260605`（`npm ci` / rsync 恢复）。详见 `FHD/docs/CLAIMED_VS_ACTUAL.md`。
