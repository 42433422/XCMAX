# 已外置归档（M0）

| 项 | 值 |
|----|-----|
| 迁出日期 | 2026-06-05 |
| 实体路径 | `/Users/a4243342/XCMAX-archives/m0-fhd-bulk-20260605/FHD/tools/XcagiInstaller` |
| 工作区相对路径 | `FHD/tools/XcagiInstaller` |

## 恢复

```bash
rsync -a "/Users/a4243342/XCMAX-archives/m0-fhd-bulk-20260605/FHD/tools/XcagiInstaller/" "/Users/a4243342/Desktop/XCMAX/FHD/tools/XcagiInstaller/"
# 或
export XCMAX_ARCHIVE_ROOT="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}"
rsync -a "$XCMAX_ARCHIVE_ROOT/m0-fhd-bulk-20260605/FHD/tools/XcagiInstaller/" "/Users/a4243342/Desktop/XCMAX/FHD/tools/XcagiInstaller/"
```

尽调交付工作区不含大文件实体；见仓根 [`ARCHIVE_POINTER.md`](../../ARCHIVE_POINTER.md)（若位于 FHD 子树则调整相对链接）。
