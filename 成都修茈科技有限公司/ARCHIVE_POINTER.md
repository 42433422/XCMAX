# 姊妹栈 · MODstore_deploy

| 项 | 值 |
|----|-----|
| 日更后端实体 | `MODstore_deploy/modstore_server/`（**已在工作区内**，见 [`MODstore_deploy/README.md`](MODstore_deploy/README.md)） |
| 历史归档副本 | `~/XCMAX-archives/m0-fhd-bulk-20260605/成都修茈科技有限公司` |

## 从归档重新同步（可选）

```bash
rsync -a --exclude '__pycache__' --exclude '*.db' --exclude 'backups/' \
  "${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605/成都修茈科技有限公司/MODstore_deploy/" \
  "成都修茈科技有限公司/MODstore_deploy/"
```

本地日更栈默认读工作区 `MODstore_deploy`（`FHD/scripts/dev/run_modstore_daily_local.sh`）。
