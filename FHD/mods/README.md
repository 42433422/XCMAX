# Mod SSOT（唯一编辑源）

`FHD/mods/` 是全部 Mod 的唯一编辑源（SSOT）。前端构建统一只读本目录，
后端运行时副本 `FHD/XCAGI/mods/` 由统一派发脚本按单向同步生成。

```bash
# 全量同步 SSOT → XCAGI/mods（改 Mod 后执行）
python FHD/scripts/dev/mods_ssot.py sync

# 检查漂移（CI / 发版前）
python FHD/scripts/dev/mods_ssot.py check
```

历史双副本 `mods-admin-runtime/` 已移除，冲突渠道 `sync-admin-mod-runtime.sh` /
`sync-enterprise-mod-seeds.sh` 已删除，统一由 `mods_ssot.py` 派发。