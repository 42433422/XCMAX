# Mac 独立实机验收（2026-10-10）

本轮只在 Mac 安装包上取证。源码测试、Windows 验收记录不计入本报告结论。

机器：macOS 26.3（25D125），arm64。截图命令被系统拒绝（`screencapture` 无法从窗口或矩形取图），主窗口在退出前由系统事件确认标题为「智能对话 - XCAGI」。

## 总判

客户下载闭环 **未通过**。公网最新 Mac 安装包是 `1.0.0.5` / `8d50fe9d`，Developer ID 签名且已公证，但不包含其后合入 main 的 Mac 修复。含这些修复的最新已公证包是本机 `1faec8e5`，没有公网下载地址，且 main 在它之后还有未打包提交。

## 1. 安装包身份、签名、公证、下载地址

| 包 | 身份 | 签名 / 公证 | 下载 |
|---|---|---|---|
| 公网最新 | `1.0.0.5`，`gitSha=8d50fe9d043391d5ba8857094a366a59a34ae43f`，`builtAt=2026-09-21T08:46:12.138Z`，`release_ready=false` | 挂载本机与公网 SHA256 一致的 DMG：`spctl` accepted / Notarized Developer ID；`stapler validate` worked；Team `G26WSH472M`，证书 `Developer ID Application: jialong Li` | `https://xiu-ci.com/xcagi-v1.0.0.5/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg`（301,669,921 字节，SHA256 `55a873779aa316fe1e2393ff043978187911b3e052b9762deaefdd6d4817e32f`）。更新说明 `https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml`（`productVersion=1.0.0.5`，`buildSha` 同上，`releaseDate=2026-09-21T08:55:08.454Z`） |
| 本机已公证候选 | `1.0.0.5`，`gitSha=1faec8e5c569925eef35b0bea657755b6b3f832a`，`builtAt=2026-10-08T23:27:09.955Z` | `spctl` accepted / Notarized Developer ID；`stapler validate` worked；时间戳 2026-10-09 07:36:57 | 无公网地址。路径：`…/mac-main1fa-final-acceptance-20261009/Applications/XCAGI.app` |
| `/Applications/XCAGI.app` | `3ab4874b17974fae2b52dcabc033f07092206771`，`builtAt=2026-10-04T20:42:54.309Z` | Developer ID 签名，`spctl` rejected / Unnotarized Developer ID，未装订公证票据 | 不是本轮验收包 |

公网包的祖先检查：`393ab31687`（商品关联、审批对话、恢复任务）、`1faec8e5`、`cfd6587610`、`b1f2d0a6` 都不在 `8d50fe9d` 内。`1faec8e5` 含 `393ab31687` 及更早的 Mac 修复，不含其后的 `cfd6587610`、`b1f2d0a6`（`origin/main` 尖端）。

## 2. 登录与承诺 Mod

在 `1faec8e5` 已有会话上请求 `GET /api/auth/me`：200，用户 `SUNBIRD`，`user_id=2`，权限 16 项，含 `shipment.edit`。退出重开后同一接口仍为 200。

会话承诺的 Mod 为 `attendance-industry`、`sunbird-attendance-custom`、`taiyangniao-pro`。`GET /api/mods` 返回 24 个，其中只有 `attendance-industry` 在列，其 status 为 200。`sunbird-attendance-custom` 为 404。`taiyangniao-pro` 考勤规则接口 403，原文 `mod_not_entitled` / 「当前企业账号未开通该定制能力」。承诺 Mod **未齐**。

## 3. 已修问题在安装包内的复验

以下均打在 `1faec8e5` 进程 `127.0.0.1:17514`，不是源码测试。公网 `8d50fe9d` 不含这些修复，不能把下面的通过写成客户下载包已通过。

- 商品关联：订单 `SO20261009083703` 明细 `product_id=1`、名称「Mac1fa验收包装盒」、单价 12.5，与 `products` 第 1 行及 `GET /api/mod/xcagi-erp-domain-bridge/products/list` 一致。客户「Mac1fa验收客户-20261009」同时出现在订单和客户列表。
- 审批：审批 1 为 rejected，聊天写「审批已拒绝，业务任务已取消，未继续执行」。审批 2 为 approved，聊天写记录 ID 1、客户 ID 1。库里只有这一张确认态销售订单，合计 25。
- 聊天状态：`GET /api/conversations/mv088mnx6rn3tjl24d` 200，3 条消息与上述审批结果一致。备份审批 3 仍是 `pending`，聊天没有把它写成成功。
- 备份恢复：恢复审批 4 为 approved，聊天写「数据库恢复成功」。启动目录里有自动备份 `xcagi-1.0.0.5-20261009002749.db`。手动备份审批没有执行完，不能记成备份审批已完成。

## 4. 本轮新业务与读回

`POST /api/mod/xcagi-erp-domain-bridge/shipment/generate` 200，「发货单生成成功」，文件 `发货单_26-1000001A_20261010_000039.xlsx`。下载 200，4809 字节，ZIP/XLSX 魔数正确，SHA256 `74c253b3ccdfe6826109a79bf22ac239e235e3b6fb1f3b8c59014746f852390b`。

## 5. 退出重开与旧版升级

退出 `com.xcagi.desktop.enterprise` 后 17514 释放，再用同一用户目录和端口拉起 `1faec8e5`。健康检查 200，`status=healthy`，`git_sha=1faec8e5c569`。登录、订单 `SO20261009083703`、3 条聊天、上述发货单下载（4809 字节、魔数正确）和 `PRAGMA quick_check=ok` 都还在。

旧版升级用的是另一份隔离数据，没有动上面这份库。公证的 `1.0.0.1` / `88aecef492e6` 先打开该库：健康检查版本 `1.0.0.1`，登录 `SUNBIRD`，能读到「Mac旧版升级包装盒 / MAC-OLD1-20261008」。退出后同一库改由 `1faec8e5` 打开：健康检查 `1.0.0.5` / `1faec8e5c569` / healthy，两件商品（`MAC-OLD1-20261008`、`MAC-UPG-20261007`）仍在，`quick_check=ok`。这不是从公网 feed 自动更新；公网 feed 仍指向更旧的 `8d50fe9d`。

## 6. 证据文件

同目录：`live-readback.json`、`chat-readback.json`、`reopen-readback.json`、`reopen-health.json`、`old-1.0.0.1-health.json`、`upgraded-1fa-health.json`、`upgrade-readback.json`。
