# XCAGI 桌面端真实机验收证据 — <版本号> — <平台：win10 / win11 / macos>

> **填写说明**（提交前删除本说明块）：
> - 复制本模板为 `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本号>-<平台>.md`，逐项填写真实值；
> - 所有 `<尖括号>` 占位必须替换；未执行的步骤标 `SKIP` + 原因，部分执行标 `PARTIAL` + 替代证据说明，**不允许留空**；
> - 截图放同目录 `assets/` 子目录，文中用相对路径引用（如 `![主窗口](assets/<版本号>-<平台>-main.png>)`）；
> - 协议见 [desktop-real-machine-acceptance-protocol.md](../../e2e/desktop-real-machine-acceptance-protocol.md)（各步判据以此为准）。
> - 结果标记只允许：PASS / FAIL / PARTIAL / SKIP / UNKNOWN；默认 UNKNOWN。PARTIAL / SKIP / UNKNOWN 与缺证据都未通过，不能授权晋级。

---

## 1. 基本信息

| 字段 | 值 |
|------|-----|
| 验收版本（四段产品版本） | `<如 1.0.0.1>` |
| 构建身份 gitSha（build-info.json） | `<40 位十六进制>` |
| 原构建 / 当前验收对象 | `<build run URL + attempt；源码 SHA 已在 main 的证据；原 manifest 路径与摘要>` |
| 证据范围 | `<源码+隔离数据 / 同一原包实机 / 客户原件与实机；不得互相替代>` |
| 平台 / 架构 | `<win10 / win11 / macos>` + `<x64 / arm64>` |
| 机器型号 | `<如 Mac16,10 / ROG Zephyrus G16 / ThinkPad X1C9>` |
| OS 版本 | `<如 macOS 26.3 (25D125) / Windows 10 22H2 (19045) / Windows 11 23H2 (22631)>` |
| 内存 / 可用磁盘 | `<如 24GB / 180GB>` |
| 执行人 | `<姓名或工号>` |
| 执行日期 | `<YYYY-MM-DD>` |
| 安装方式 | `<双击安装 / 静默 /S / 验收脚本>` |
| 安装目录 | `<macOS: /Applications/XCAGI.app 或 ~/Applications/acceptance/XCAGI.app；Windows: 安装时选择的目录>` |
| 总体结论 | `UNKNOWN — 待原包身份及必需项实际证据齐全后判定` |

---

## 2. 安装

| 字段 | 值 |
|------|-----|
| 安装包文件名 | `<如 XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg>` |
| 下载 URL | `<完整 https 地址>` |
| 文件大小（字节） | `<manifest size 字段 / 实测>` |
| 实测 SHA256 | `<shasum -a 256 / Get-FileHash 输出>` |
| manifest 期望 SHA256 | `<manifest.json 对应条目值；无则写"manifest 无该版本条目">` |
| 与 manifest 比对结果 | `<PASS 一致 / FAIL 不一致 / PARTIAL 无基准值>` |
| 签名校验结果 | `<macOS: codesign 身份 + spctl accepted；Windows: Get-AuthenticodeSignature Status=Valid + 证书 Subject + 时间戳>` |
| 安装结果 | `<PASS / FAIL + 现象>` |
| 安装后版本核对 | `<build-info 完整 SHA / 实际后端 SHA、PID、路径 / 可见 UI 身份 / sku；与原包一致>` |
| 系统拦截弹窗 | `<无 / 有 + 截图路径>` |
| **本步结论** | **`<PASS / FAIL / PARTIAL / SKIP + 原因>`** |

---

## 3. 冷启动

| 字段 | 值 |
|------|-----|
| 启动方式 | `<双击图标 / open -n / Start-Process / 验收脚本>` |
| 启动耗时（双击 → 主窗口完整出现） | `<如 12 秒（判据 ≤60s）>` |
| 主窗口截图路径 | `assets/<文件名>.png` |
| 后端健康检查结果 | `<curl/Invoke-RestMethod http://127.0.0.1:17500/api/health 的完整返回 JSON>` |
| 17500 端口监听进程 | `<如 xcagi-bac (PID xxx) / 无>` |
| 前端渲染完整性 | `<主界面/侧栏可见，无白屏>` |
| **本步结论** | **`<PASS / FAIL / PARTIAL / SKIP + 原因>`** |

> SKIP 常见原因示例：本机已有正在使用的 XCAGI 实例（单实例锁 + 17500 端口冲突），
> 需另选隔离机器补测；代码评审 + CI 冒烟可附为源码证据，不能替代本机启动 PASS。

---

## 4. OTA（在线自动更新）

| 字段 | 值 |
|------|-----|
| 更新源 URL（macOS / Windows） | `<https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml 或 latest.yml>` |
| latest*.yml 中 productVersion（目标版本） | `<值>` |
| 升级前版本号 | `<值>` |
| 升级后版本号 | `<值>` |
| 升级前后完整身份 | `<两端源码 SHA、安装器 SHA256、原构建 run/attempt、原更新清单及摘要>` |
| Ed25519 签名校验 | `<本轮实际验签结果及原始日志 / 未触达；无报错不等于通过>` |
| 观察期表现 | `<正常度过（rollback-marker.json 被自动删除）/ 触发回滚 / 未触达>` |
| updater-events.jsonl | `<本轮原始完整文件路径与 SHA256，摘要片段另附>` |
| **本步结论** | **`<PASS / FAIL / PARTIAL / SKIP + 原因（如"当前已是线上最新版本，无升级目标"）>`** |

---

## 5. 回滚

| 字段 | 值 |
|------|-----|
| 验证方式 | `<A 同一原包实机故障注入 / B 手动恢复；分别判定，B 不能代替 A>` |
| 回滚前版本号 | `<值>` |
| 回滚后版本号 | `<值>` |
| rollback-applied.json 内容（路径 A） | `<文件全文；无则写"未生成">` |
| 回滚后健康状态 | `<curl/Invoke-RestMethod /api/health 返回>` |
| 用户数据保留 | `<业务记录 ID、金额、库存、附件摘要、Mod 权益前后对账；原请求重试唯一效果与另一租户不变 / 未验证>` |
| 备份 / 旧数据 / 离线 / 诊断 | `<备份路径+摘要、真实恢复回读、旧 schema→新 schema、离线动作及联网重试、失败日志与恢复步骤的原证据；缺项逐项列出>` |
| 界面提示截图（如有） | `assets/<文件名>.png` |
| **本步结论** | **`<PASS / FAIL / PARTIAL（如"以 rollback.test.ts + update-rollback.e2e.spec.ts 佐证"）/ SKIP + 原因>`** |

---

## 6. 缺陷与异常记录

| # | 当前源码 SHA / 原包 SHA256 | 步骤 / 严重度 | 描述与影响范围 | 原证据及补测入口 | 状态 |
|---|---|---|---|---|---|
| 1 | `<本轮完整身份；缺失则 UNKNOWN>` | `<步骤 / P0/P1/P2>` | `<现象、复现、未解风险>` | `<日志/截图/数据差异、负责人和补测步骤>` | `<待修 / 已修待验证 / 同包复验通过>` |

仅已完成全部必需观察且无未解风险时可写“无”；未执行写“未知/待补测”，保留历史原报告。

---

## 7. 证据文件清单

| 类型 | 路径 |
|------|------|
| 主窗口截图 | `assets/...` |
| SHA256 计算输出 | `<截图或粘贴文本>` |
| health 检查输出 | `<粘贴文本>` |
| 其他（日志/录屏） | `<路径；>50MB 的大文件不入库，注明保存位置>` |

---

## 8. 结论与签名

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 执行人 | | | |
| 测试负责人复核 | | | |

**最终结论**（须与第 1 节及原包身份一致；未选或缺证据即未通过）：

- [ ] **PASS** — 声明范围内身份、安装、业务、数据与全部恢复必需项均为同一原包实际 PASS，另按产品规则取得发布授权
- [ ] **FAIL** — 存在 FAIL 项（第 6 节 #`<编号>`），该版本 `<平台>` 验收未闭环
- [ ] **PARTIAL** — 必需项有 PARTIAL/SKIP，附原因及补测计划，保持候选，技术签字不等于通过
- [ ] **UNKNOWN** — 原包身份或原始证据不足，保持未验证，不计为通过
