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

## 目录分层

编辑源按平台三层组织（Mod id 仍是目录名，运行时导出到 `XCAGI/mods/<id>` 保持平铺）：

| 目录 | 层 | 成员 |
|---|---|---|
| `industry/` | 行业包（manifest 含 `industry` 块）与客户定制 | `accessories-packaging-industry`、`coating-industry`、`sz-qsm-pro`、`taiyangniao-pro`、`sunbird-attendance-custom` |
| `bridge/` | 宿主能力桥接（见 `app/mod_sdk/host_profile_defaults.py`） | `xcagi-approval-bridge`、`xcagi-lan-license-bridge`、`xcagi-model-payment-bridge`、`xcagi-planner-bridge`、`xcagi-neuro-bus-bridge`、`xcagi-erp-domain-bridge`、`xcagi-office-employee-pack-bridge`、`xcagi-customer-service-bridge`、`xcagi-workflow-visualization-bridge` |
| `employees/` | 员工房子（承载工作流员工） | `xcagi-core-workflow-employees`、4 个 `xcagi-workflow-employee-*`、`lan-gate-ai-employee` |
| `tools/` | 工具 Mod | `xcagi-planner-excel-tools` |
| `_employees/` | 员工家具（employee pack，非 Mod） | 各员工包 |

发现逻辑同时兼容平铺（旧安装目录）与分层两种布局；新增 Mod 请放入对应层。