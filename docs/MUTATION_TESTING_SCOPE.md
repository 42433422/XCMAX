# Mutation testing scope

2026-10-25 Asia/Shanghai

## 已证实

PR #2629 关联提交的 GitHub Actions 日志：

- killed 255 / survived 13 → **95.15%**
- CI 阈值 ≥ 80%
- 范围：**限定** mutmut 目标（DI、Contexts 等），**不是**全仓

## 禁止的表述

- ❌「全仓变异得分 95%」
- ✅「限定模块变异得分 95.15%（CI≥80%）」

## 扩大路线

1. 先覆盖 application 核心服务与 domain 策略。
2. 再纳入 MODstore 关键路径与 Agent orchestrator。
3. 每扩一域单独留日志产物，禁止用旧 95.15% 冒充新域。
