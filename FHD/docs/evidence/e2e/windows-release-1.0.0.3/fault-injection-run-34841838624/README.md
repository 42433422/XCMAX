# Windows 故障注入 runner 证据（run 34841838624）

- 日期：2026-09-14（UTC 12:09 派发，12:20 完成，conclusion=success）
- 构建锚定：main HEAD `3d872b32e`（#1920 合并提交）；脚本版本含 #1923 场景（无 #1938 判定修复——本 run 场景组合不含 corrupt-main，`corrupt.evidence` 起始为 0，绝对计数与增量判定等价，判定有效）
- 安装包：testing 通道 `XCAGI-Enterprise-Setup-1.0.0.3-x64-unsigned.exe`，SHA256 `7c044bec4c87391ea86e9f445fa356ae34bfcebede6876bfc0c7a1df28889e8b`（workflow 下载后实测校验一致）
- 环境：GitHub `windows-latest` 一次性 runner，隔离安装根 `C:\XCAGI-acceptance`，数据根 `%APPDATA%\XCAGI`（runneradmin）

## 场景结果（fault-injection-receipt.json 摘要）

| 场景 | 结果 | 证据 |
|---|---|---|
| dual-process | **PASS** | 第二实例 1s 自行退出（ExitCode=0），单实例锁生效；主实例 health=degraded（无 LLM 凭据环境正常口径）；backend_count=1；主库 1445888→1445888 字节无损 |
| migration-mutex | **PASS** | 0.3s 间隔竞态双启动收敛单后端；监听 PID 唯一（8476）；corrupt_evidence=0（无损坏留证）；主库 1667072 字节 |
| disk-full | SKIP | 实体机场景（卷配额/小 VHD），CI 无法执行 |
| power-cut | SKIP | 实体机场景（拔电/断 PDU），CI 无法执行 |

FAIL=0，PARTIAL=0。

## 证据文件

- `fault-injection-receipt.json`：汇总回执（workflow artifact 原样）
- `dual-process-20260914-121952.txt`：场景 5 原始取证行
- `migration-mutex-20260914-121952.txt`：场景 6 原始取证行

## 口径说明

- health=degraded 为无 LLM 凭据环境预期值（N05 口径：/api/health 后端在 17500 监听即认通过，与 acceptance-windows.ps1 一致）。
- dual-process 取证行不含 corrupt before→after 字段（该增强在 #1938 的后续版本中）；本 run 场景隔离下判定等价。
- disk-full/power-cut 维持「待实体机人工执行」状态，审计中如实标注，不冒充通过。
