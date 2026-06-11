# ESkill：TypeScript 类型检查守卫（skill-typecheck-guard）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-typecheck-guard` |
| 所属员工 | `test-qa-runner` |
| 业务域 | Market 前端 TypeScript 类型安全检查 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
cd MODstore_deploy/market
npx vue-tsc --noEmit -p tsconfig.strict-baseline.json
→ 解析类型错误输出
→ 按文件/错误类型分类
→ 输出报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "total_errors": 0,
  "errors_by_file": {
    "path/to/file.ts": [
      {
        "line": 0,
        "column": 0,
        "code": "TS0000",
        "message": ""
      }
    ]
  },
  "errors_by_code": {}
}
```

**约束**：不修改 `market/src/**` 源码；只报告问题，由 `market-frontend-dev` 修复。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 类型错误 | `total_errors > 0` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。
**LLM 任务**：分析类型错误 → 按严重程度分类（P0：编译阻断 / P1：类型不安全 / P2：any 推断）→ 生成修复建议 → 通知 `market-frontend-dev` 修复。

## 4. 固化

**验收标准**：`total_errors == 0`，TypeScript 类型检查零错误。
