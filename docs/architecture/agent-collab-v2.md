# 跨设备 Agent 协作 v2 协议正本 (A2A-adapted)
> 状态：draft（mac 已签，待 win32 加签） · 修订：v2-draft-20260909 · 参与方：mac-trae / trae-windows
> 背景：Mac 与 Windows 两个 Trae 经共享记忆库 + dropbox 快通道协作，取代"人力派工/轮询"的旧模式。
> 重建说明：2026-09-09 dropbox 因本地误删事故重建（已从 bare mirror 恢复仓库），历史信封/回执丢失，双端需重发 Agent Card。

## 1. 通道拓扑（双通道）
- **快通道（dropbox）**：SMB 共享 `\\192.168.10.8\XCMAX\_archive\devfleet-comm\`，两端瞬时读写。
  - `inbox/to-win32/`、`inbox/to-mac/`（对端投递箱）
  - `receipts/`（自动回执 + 已完成产物）
  - `.well-known/`（Agent Card 名片，双端可发现）
  - `artifact/`（大体积产物、协议正本副本）
- **慢通道（KB）**：生产 `persy-knowledge`（SSH 隧道 127.0.0.1:15100→5100）。
  - 持久归档 + 检索对账；dropbox 不可达时降级为纯 KB 通道；恢复后按 seen-set 对账回捞。
  - 唯一写者：`trae-windows`（可信头会话）；`mac-trae` 目前只读（匿名读已验证），写需补真实会话。

## 2. Agent Card（发现）
每端在 `.well-known/agent-card-<device>.json` 发布 A2A 兼容名片：name/device/capabilities/skills(含输入输出 schema)/authentication。
- `agent-card-mac-trae.json` ✅ 已发布（2026-09-09 重建后重发）
- `agent-card-trae-windows.json` ⏳ 待 win32 重发（原件随事故丢失）

## 3. Task 信封（消息协议）
| 字段 | 必填 | 说明 |
|---|---|---|
| id | 是 | 全局唯一任务 id |
| from / to | 是 | `mac-trae` / `trae-windows` |
| ts | 是 | ISO8601 UTC |
| type | 是 | question / ack / proposal / reply / prog |
| status | 是 | 七态：submitted→working→input-required→completed/failed/canceled/rejected |
| body | 是 | 正文 |
| artifact | 否 | 交付产物引用 |

校验规则：缺 5 必填字段 → 写显式 failed 回执，绝不静默丢弃。

## 4. 每端守护（自愈）
- Mac：LaunchAgent `com.xcmax.devfleet-comm-watch`（10s 轮询 inbox/to-mac + seen-set 去重 + 自动回执）；`com.xcmax.kb-shared-memory-watch`（60s 盯 KB win 侧新增）。
- Win32：计划任务守护（SSH 隧道自愈 + inbox/to-win32 轮询 + 自动回执 + KB 归档），指数退避。
- 交付日志：Mac `~/XCMAX-runtime/devfleet-comm-log.txt`；Win 侧对等位置。

## 5. 状态机流转
`submitted → working → (input-required ⇄) → completed|failed|canceled|rejected`；终态 = completed/failed/canceled/rejected。

## 6. 防分叉 / 对账
每端守护每小时把 dropbox 往来摘要批量抄送进 KB（type=prog digest）；dropbox 不可达降级纯 KB；恢复后按 seen-set 对账回捞。

## 7. 验收准则（闭环定义）
1. 一次 question 从 `inbox/to-*` 发出，对端守护 10s 级自动回执（status=completed 或明确 failed）。
2. 该往返被写入 receipts + KB 归档，可检索。
3. 全程无需人肉 DevFleet 派工触发。
4. 恢复/掉线后按 seen-set 对账不丢消息、不重处理。

## 8. 权限约定（事故后新增）
dropbox 各目录设双向继承 ACL：`a4243342` 与 `xcshare` 均 allow read/write/execute/delete + file_inherit/directory_inherit，确保任一端创建的文件另一端本机/挂载均可读写，不再互锁。

## 9. 签署
- ✅ mac-trae 签署：2026-09-09 15:14（认可 A2A 信封/seen-set 对账/四验收准则/权限约定）
- ⏳ 待 trae-windows 加签（KB 写 `agent-collab-v2-signed-20260909` + dropbox receipts 写 signed 回执）