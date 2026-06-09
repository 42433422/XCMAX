# 已外置归档（M0）

| 项 | 值 |
|----|-----|
| 迁出日期 | 2026-06-05 |
| 实体路径 | `~/XCMAX-archives/m0-fhd-bulk-20260605/.tools/node-v22.12.0-darwin-arm64` |
| 工作区路径 | `.tools/node-v22.12.0-darwin-arm64` |

## 恢复

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
rsync -a "$AR/.tools/node-v22.12.0-darwin-arm64/" "$(pwd)/.tools/node-v22.12.0-darwin-arm64/"
```

见仓根 [`ARCHIVE_POINTER.md`](../ARCHIVE_POINTER.md)。
