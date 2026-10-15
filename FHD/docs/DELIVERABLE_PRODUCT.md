# XCAGI 企业版可交付产品说明

客户安装由共享 `main` 构建的宿主。客户定制通过版本化 Mod、账号权益与数据归属隔离交付；供应商不代运营客户业务库，不维护客户分叉安装包。

## 交付身份与验收

产品版本与工具链映射以 [VERSION.md](../VERSION.md) 为准；正式构建目标是 `enterprise`，`personal` 仅保留历史兼容代码。安装包必须包含对应平台的后端，不能以 Electron 空壳交付。

交付包来自明确的主线 SHA；包内 `build-info`、运行后台、可见界面和业务证据身份一致。分支测试、健康检查和旧包结论不证明新包通过。

| 平台 / 路径 | 事实源 |
|---|---|
| Mac 构建、签名公证、双架构与实机验证 | [MACOS_RELEASE_SSOT](MACOS_RELEASE_SSOT.md) |
| Windows 构建、签名与实机验证 | [WINDOWS_RELEASE_SSOT](WINDOWS_RELEASE_SSOT.md) |
| 同版双端和放行原则 | [desktop_platform_parity_ssot](desktop_platform_parity_ssot.md) |
| 原工单处理、结果回流与客户确认 | [CUSTOMER_TICKET_BUS_SSOT](architecture/CUSTOMER_TICKET_BUS_SSOT.md) |

正式下载指针及 stable 通道在既有门禁与客户闭环通过后推进；构建候选不代表已经发布。

## 宿主与 Mod

| 层 | 交付方式 |
|---|---|
| L1 通用 bridge | 安装包内 `mods/` 种子；首次启动复制到用户目录 |
| L2 中性行业种子 | 企业包的 `industry-seeds/` 只读池；选择行业后安装对应项，不全量激活 |
| L3 账号定制 | 不放入共享安装包；通过 entitlement 和 Catalog 安装、更新 |

Manifest、SDK、打包过滤与 Mod 发布规范见 [MOD_AUTHORING_GUIDE](guides/MOD_AUTHORING_GUIDE.md)。共享宿主升级须保留客户数据及已授权 Mod，并验证仍可更新。

## 客户标准路径

1. 从已核验身份的客户入口下载并安装；数据保留、备份和回滚约定见 [LOCAL_DATA_POLICY](security/LOCAL_DATA_POLICY.md)。
2. 首次设置按公司名称 → 行业 → 配置功能进行。名称和行业保存后重新读回；失败留在当前步骤。匿名用户可先填写，再登录继续。
3. 行业选择不授予定制权益。根据最新功能准备结果补齐本行业所需项；演示数据和 AI 第一单是可选体验。
4. 所需功能就绪且工作区完成状态保存成功，才完成设置。日常通过智能对话、业务 Mod 菜单和扩展市场使用；升级、重启后核对原数据和权益。
5. 出现问题从安装版提交原工单，保留内容及附件。处理结果回到原单，由客户复验并明确关闭；重开、租户隔离和异常恢复按工单总账验证。

## 功能准备检查

`GET /api/platform-shell/deliverable-status` 中的 `deliverable` 表示宿主所需功能准备就绪；`blockers` 与 `next_actions` 说明缺失项及补齐动作。它不代表安装、业务、安全或发布验收通过。

开发运行与设置操作见 [QUICK_START](QUICK_START.md)；启动配置、版本自检和发布脚本按上述发布规范执行。
