# XCAGI 桌面端真实机验收证据 — <版本号> — <平台：win10 / win11 / macos>

> **填写说明**（提交前删除本说明块）：
> - 复制本模板为 `FHD/docs/evidence/e2e/desktop-real-machine-acceptance-<版本号>-<平台>.md`，逐项填写真实值；
> - 所有 `<尖括号>` 占位必须替换；未执行的步骤标 `SKIP` + 原因，部分执行标 `PARTIAL` + 替代证据说明，**不允许留空**；
> - 截图放同目录 `assets/` 子目录，文中用相对路径引用（如 `![主窗口](assets/<版本号>-<平台>-main.png>)`）；
> - 协议见 [desktop-real-machine-acceptance-protocol.md](../../e2e/desktop-real-machine-acceptance-protocol.md)（各步判据以此为准）。
> - 结果标记只允许：PASS / FAIL / PARTIAL / SKIP。

---

## 1. 基本信息

| 字段 | 值 |
|------|-----|
| 验收版本（四段产品版本） | `<如 1.0.0.1>` |
| 构建身份 gitSha（build-info.json） | `<40 位十六进制>` |
| 平台 / 架构 | `<win10 / win11 / macos>` + `<x64 / arm64>` |
| 机器型号 | `<如 Mac16,10 / ROG Zephyrus G16 / ThinkPad X1C9>` |
| OS 版本 | `<如 macOS 26.3 (25D125) / Windows 10 22H2 (19045) / Windows 11 23H2 (22631)>` |
| 内存 / 可用磁盘 | `<如 24GB / 180GB>` |
| 执行人 | `<姓名或工号>` |
| 执行日期 | `<YYYY-MM-DD>` |
| 安装方式 | `<双击安装 / 静默 /S / 验收脚本>` |
| 安装目录 | `<macOS: /Applications/XCAGI.app 或 ~/Applications/acceptance/XCAGI.app；Windows: 安装时选择的目录>` |
| 总体结论 | `<PASS / FAIL / PARTIAL（一句话说明）>` |

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
| 安装后版本核对 | `<build-info.json version / Info.plist 或 ProductVersion / product-sku.json sku>` |
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
> 启动步骤以代码评审 + CI 冒烟（desktop.e2e / desktop-macos-smoke）替代，需在此注明。

---

## 4. OTA（在线自动更新）

| 字段 | 值 |
|------|-----|
| 更新源 URL（macOS / Windows） | `<https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml 或 latest.yml>` |
| latest*.yml 中 productVersion（目标版本） | `<值>` |
| 升级前版本号 | `<值>` |
| 升级后版本号 | `<值>` |
| Ed25519 签名校验 | `<通过（更新过程无验签失败提示）/ 未触达>` |
| 观察期表现 | `<正常度过（rollback-marker.json 被自动删除）/ 触发回滚 / 未触达>` |
| updater-events.jsonl 摘录 | `<最后 3–5 行粘贴于此>` |
| **本步结论** | **`<PASS / FAIL / PARTIAL / SKIP + 原因（如"当前已是线上最新版本，无升级目标"）>`** |

---

## 5. 回滚

| 字段 | 值 |
|------|-----|
| 验证方式 | `<A 观察期自动回滚（注入坏更新）/ B 降级安装上一版本 / 替代证据>` |
| 回滚前版本号 | `<值>` |
| 回滚后版本号 | `<值>` |
| rollback-applied.json 内容（路径 A） | `<文件全文；无则写"未生成">` |
| 回滚后健康状态 | `<curl/Invoke-RestMethod /api/health 返回>` |
| 用户数据保留 | `<登录正常 + 历史数据可见 / 未验证>` |
| 界面提示截图（如有） | `assets/<文件名>.png` |
| **本步结论** | **`<PASS / FAIL / PARTIAL（如"以 rollback.test.ts + update-rollback.e2e.spec.ts 佐证"）/ SKIP + 原因>`** |

---

## 6. 缺陷与异常记录

| # | 步骤 | 严重度（P0/P1/P2） | 描述 | 证据（截图/日志路径） | 状态 |
|---|------|--------------------|------|----------------------|------|
| 1 | `<安装/冷启动/OTA/回滚>` | `<P0/P1/P2>` | `<现象与复现步骤>` | `<路径>` | `<待修/已修/已验证>` |

（无缺陷则写"无"。）

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

**最终结论**（三选一，须与第 1 节一致）：

- [ ] **PASS** — 本机安装/冷启动 PASS，OTA/回滚无 FAIL，可作为该版本 `<平台>` 验收记录
- [ ] **FAIL** — 存在 FAIL 项（第 6 节 #`<编号>`），该版本 `<平台>` 验收未闭环
- [ ] **PARTIAL** — 部分 PASS + 替代证据（第 2–5 节各 PARTIAL/SKIP 项均附说明），允许技术签字，不阻塞但需补测计划
