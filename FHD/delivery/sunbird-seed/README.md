# 太阳鸟交付种子（历史）· 已退役

> **退役口径（现行）**：客户交付使用**通用 Enterprise 安装包**；太阳鸟进度走生产员工「私有交付」双轨节点（制作/测试/返工/验收），**不再打 `太阳鸟-Setup-*.exe` 定制安装包**。
>
> 本目录与 `build-sunbird-installer.ps1` / `Sunbird Installer` workflow 仅保留为历史种子与排障参考，**禁止作为新签约交付面**。

由 `scripts/package/build-sunbird-seed.py` 生成/刷新的业务数据快照（考勤模板、花名册、Mod 侧库）。历史定制安装包曾用 `build-sunbird-installer.ps1` 嵌入 WPF 安装程序。

| 路径 | 内容 |
|------|------|
| `424/考勤-2026-3月份考勤统计表.xlsx` | 固定考勤模板 |
| `data/mod_dbs/taiyangniao_pro.db` | Mod 侧库（含人员镜像） |
| `config/sunbird-roster.json` | 主库花名册种子 |
| `mods/` | 历史打包脚本从 `mods/taiyangniao-pro`、`mods/attendance-industry` 拷贝 |

现行交付：

1. 安装通用 `XCAGI-Enterprise-Setup-*-x64.exe` / macOS Enterprise DMG
2. 市场账号绑定 `taiyangniao-pro`（∩ entitlement）
3. 生产员工在私有交付面板推进节点进度；管理端只读定制清单与状态
