# 任务提示词：执行 CI 测试套件

## 使用场景

每次代码合并前、发布前或定期巡检时，执行完整测试套件并生成报告。

## 输入格式

```
任务：执行 CI 测试套件
范围：all | modstore | vibe-coding | e2e（默认 all）
覆盖率要求：<如 80%（modstore）; 85%（vibe-coding）>
失败处理：block（阻断）| report（只报告）
```

## 执行步骤

1. **MODstore pytest**
   ```bash
   cd MODstore_deploy
   python -m pytest tests/ -q --tb=short --json-report --json-report-file=/tmp/modstore_result.json
   python -m pytest tests/ --cov=modstore_server --cov-report=json --cov-report=term-missing -q
   ```

2. **vibe-coding pytest**
   ```bash
   cd vibe-coding
   python -m pytest tests/ -q --tb=short
   python -m pytest tests/ --cov=src/vibe_coding --cov-report=term-missing -q
   ```

3. **Playwright E2E**（`范围 == all` 或 `e2e` 时执行）
   ```bash
   npx playwright test --reporter=json > /tmp/e2e_result.json
   ```

4. 汇总结果，按 P0/P1/P2 分级失败 case。

5. 输出 JSON 摘要，推送给 `log-monitor-incident`。

## 输出格式

```json
{
  "run_id": "<timestamp>",
  "modstore": { "passed": 0, "failed": 0, "coverage": 0.0 },
  "vibe_coding": { "passed": 0, "failed": 0, "coverage": 0.0 },
  "e2e": { "passed": 0, "failed": 0, "flaky": 0 },
  "p0_failures": [],
  "p1_failures": [],
  "overall_status": "green | yellow | red"
}
```

## 约束检查

- [ ] 不修改任何 `src/**` 源码
- [ ] 不修改 `market/src/**`
- [ ] 覆盖率低于阈值时标记 `overall_status = yellow`
- [ ] 有 P0 失败时标记 `overall_status = red` 并立即通知 `log-monitor-incident`
