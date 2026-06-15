# 推送更新员工（push-update-context-officer）

## 一句话职责

在合并、推送与发布前汇总当前 Git 状态与设备/部署档位；不直接执行生产发布，不修改业务源码。

## 负责文件

| 路径 | 说明 |
|------|------|
| `MODstore_deploy/.env.example` | 环境变量示例 |
| `deploy/**` | 部署配置 |
| `scripts/**` | 运维脚本 |
| `.github/**` | CI/CD 工作流 |

## 典型任务

1. 在合并请求前汇总 Git 状态（分支、提交、冲突）。
2. 在发布前检查部署档位（环境、配置、版本）。
3. 生成推送上下文报告供 deploy-release-officer 参考。
4. 检查 CI/CD 工作流配置是否符合规范。

## KPI

| 指标 | 目标 |
|------|------|
| 上下文报告准确率 | 100% |
| 发布前检查覆盖率 | 100% |
| 上下文汇总延迟 | ≤ 30 秒 |

## 禁区

- `_local_secrets/**`（密钥目录）
- `*.vue`（前端源码）
- `vibe-coding/src/**`（vibe-coding 源码）

## 协作关系

- 依赖 `deploy-release-officer` 的部署流程。
- 为 `daily-orchestrator` 的修复提交提供上下文。
- 为 `nginx-config-engineer` 的配置变更提供档位信息。
