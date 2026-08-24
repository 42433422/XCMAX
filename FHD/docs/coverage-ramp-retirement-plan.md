# coverage_ramp stub 转正/清退计划（2026-08-24）

> 目标：停止用 82 个 `test_coverage_ramp_*` stub 稀释真实覆盖率；对外口径统一为
> **行为覆盖率（当前 79.26% 行 / 70.87% 分支）**。

## 现状（诚实披露）

| 口径 | 行 | 分支 | 说明 |
|------|---:|---:|------|
| 全量（含 stub） | 88.19% | 81.5% | 名义值，含注水 |
| **行为（排除 stub）** | **79.26%** | **70.87%** | 真实契约覆盖，唯一硬 gate（ADR-0001） |

- stub 规模：**82 个文件 / 63,866 行**（`tests/test_coverage_ramp_phase*.py`）
- pyproject markers 自承：「断言弱、杀变体能力低；非行为契约测试」
- 测试膨胀棘轮（`metrics/test-bloat-history.jsonl`）显示 ratio 1.759 → 1.848 持续上升，
  stub 行数只增不减，正在逼近红线。

## 决策

1. **门禁口径**：行为覆盖率是唯一硬 gate（已由 ADR-0001 落地，
   `coverage_ratchet.py --check --behavior`）。全量口径仅作参考，**不再对外声称**。
2. **对外口径统一**：文档、汇报、README 一律引用「行为覆盖 79%」，
   禁止单独引用 88% 全量值。
3. **stub 冻结**：即日起**禁止新增** `test_coverage_ramp_*` 文件
   （由 guard 检查拦截，见下）。

## 转正/清退流程（按批次）

每个 stub 文件走三选一判定：

- **转正**：该文件覆盖的模块是行为契约（路由/领域服务/资金链路）→
  重写为带真实断言的行为测试，改名为 `test_<module>_behavior.py`，
  脱离 `coverage_ramp` marker。
- **清退**：该文件覆盖的模块已有真实行为测试兜底，或模块本身是死代码 →
  直接删除。
- **降级保留**：纯导入冒烟价值 → 合并进少量 `test_import_smoke.py`，
  不占独立文件。

### 批次安排

| 批次 | 范围 | 动作 |
|------|------|------|
| B1 | `phase1_p0_*`（core/routes） | 优先转正（P0 路由是行为契约） |
| B2 | `phase1_p1_*`（ai_chat/auth） | 转正或删除 |
| B3 | 其余 phase2+ | 逐文件判定，默认清退 |

每批完成后执行：

```bash
XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1 python -m pytest tests/ -q -m 'not coverage_ramp' \
  --cov --cov-branch --cov-report=json:coverage-behavior.json --cov-fail-under=0
python scripts/dev/coverage_ratchet.py --check --behavior --record
python scripts/dev/test_bloat_report.py --check
```

行为覆盖率只升不降（`--bump --behavior` 棘轮）；stub 行数只减不增。

## 完成标准

- [ ] `tests/` 下 `test_coverage_ramp_*` 文件数 = 0（或仅剩降级合并的冒烟文件）
- [ ] `metrics/test-bloat-history.jsonl` stub_lines 归零，ratio 回落至 ≤1.5
- [ ] 行为覆盖率 floor 棘轮至清退后实测值（只升不降）
- [ ] 所有对外文档口径统一为行为覆盖率

## 防复发

- 新增测试命名禁止 `test_coverage_ramp_` 前缀（conftest 自动打标 + review 拦截）。
- 覆盖率诉求一律通过补行为测试满足，禁止再造填充型 stub。
