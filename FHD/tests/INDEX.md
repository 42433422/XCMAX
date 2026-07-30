# FHD 测试索引

本目录是 FHD 后端唯一活跃测试树；覆盖率口径为 `source = ["app"]` 的全量行与分支覆盖。

| 套件 | 路径 | 用途 |
|---|---|---|
| 应用服务 | `test_application/` | 工作流、工具、审批、AI 员工与服务编排 |
| 领域模型 | `domain/`, `test_domain/` | 领域约束、值对象和自治策略 |
| API / 路由 | `test_routes/`, `test_*_api.py` | 路由注册、权限和接口契约 |
| 基础设施 | `infrastructure/`, `test_infrastructure/` | 持久化、队列、外部适配器 |
| 发布门禁 | `release_gate/` | 制品身份、部署脚本和发布策略 |
| 自治与安全 | `test_autonomy/`, `security/` | 风险闸门、租户隔离和安全回归 |

本地验证：

```bash
cd FHD
uv sync --extra server-api --extra dev
uv run pytest tests/ -q
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
```

CI 权威入口为根仓 [`.github/workflows/fhd-ci-cd.yml`](../../.github/workflows/fhd-ci-cd.yml)。
历史 `test_coverage_ramp_phase*` 只做兼容保留；禁止新增此类文件。
