# DORA 四指标数据来源

> 与 `scripts/dora_metrics.py`、`scripts/dora_metrics_collect_events.py` 及 CI `dora-metrics-collect.yml` 配套。

| 指标 | 字段 | 数据来源 | 备注 |
|------|------|----------|------|
| **部署频率** | `deployment_frequency_per_day` | GitHub Actions：`Deploy`、`CI/CD Pipeline` 工作流运行（`exclude_pull_requests=true`） | 30 天窗口内运行次数 ÷ 30 |
| **变更前置时长** | `lead_time_hours_median` | 每次运行的 `head_sha` → Commits API 的 `commit.author.date`，与 run `updated_at` 之差（小时） | 缺 commit 时间则不计入中位数 |
| **变更失败率** | `change_failure_rate` | 同上工作流 run 的 `conclusion`：`failure` / `cancelled` 记为 failed | 分母为窗口内全部计入 run |
| **MTTR** | `mttr_hours_median` | 失败 run 的 `deployed_at` 至**下一次成功** run 的 `deployed_at`（收集脚本 `_assign_mttr`） | 无失败则无 MTTR 样本 |

## 落盘文件

| 路径 | 说明 |
|------|------|
| `metrics/deploy_events.jsonl` | 原始部署事件（JSONL，可被 `dora_metrics.py --events` 消费） |
| `metrics/dora-YYYYMMDD.json` | 每日快照（含 `report` + `data_sources`） |
| `metrics/dora-monthly-YYYYMM.md` | 月报（`scripts/dora_metrics_render.py`） |

## 本地 / CI 命令

```bash
# 需 GITHUB_TOKEN 或 Actions 默认权限
python3 scripts/dora_metrics_collect_events.py --out metrics/deploy_events.jsonl

python3 scripts/dora_metrics.py --events metrics/deploy_events.jsonl --window-days 30

python3 scripts/dora_metrics_render.py --month 202606 --events metrics/deploy_events.jsonl
```

种子数据（无 token 时跑单测 / 月报）：`metrics/deploy_events.seed.jsonl`。
