# 太阳鸟交付种子（历史）· 已退役

> **退役口径（现行）**：客户交付使用**通用 Enterprise 安装包**；太阳鸟进度走生产员工「私有交付」双轨节点（制作/测试/返工/验收），**不再打 `太阳鸟-Setup-*.exe` 定制安装包**。
>
> 本目录与 `build-sunbird-installer.ps1` / `Sunbird Installer` workflow 仅保留为历史种子与排障参考，**禁止作为新签约交付面**。

历史目录中的客户考勤模板、花名册与人员数据库已从当前源码树移除。
这不代表历史提交或已有副本被清除。真实交付数据只能保存在客户授权的私有运行目录，
不得重新提交本目录。业务解析与转换回归使用 tests/fixtures/synthetic_attendance 的全合成数据。

历史 build-sunbird-seed.py 与 publish-sunbird-delivery-seed.py 入口现已禁用，
不会重用旧本地种子、打包或登记传入 ZIP；已授权的现行私有交付 API 不受影响。
默认示例模板已替换为明确标记的虚构数据，不可作为真实客户花名册导入生产。

现行交付：

1. 安装通用 `XCAGI-Enterprise-Setup-*-x64.exe` / macOS Enterprise DMG
2. 市场账号绑定 `taiyangniao-pro`（∩ entitlement）
3. 生产员工在私有交付面板推进节点进度；管理端只读定制清单与状态
