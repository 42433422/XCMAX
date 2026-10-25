# Vendored LangGraph components

2026-10-25 Asia/Shanghai

仓库内为**同一上游生态**的 vendored 组件（core / checkpoint / sqlite|postgres / prebuilt / SDK），
**不是**六份完整框架分叉复制。

## 治理

| 项 | 要求 |
|----|------|
| 上游来源 | 记录于各包 metadata / 仓库 vendoring 说明 |
| 升级策略 | 锁定版本；升级需校验 + 回归；禁止静默覆盖 |
| 供应链 | 保留 checksum / 来源字段；CI 可挂 `scripts/ci/verify_vendored_langgraph.py` |
| 风险 | 长期维护成本；安全补丁需重放 |

本轮提供校验脚本钩子（缺失 metadata 时 WARN）。

## debt19

`pregel/main.py` split into `main_mod*` / mixins to drop >100KB singleton.
