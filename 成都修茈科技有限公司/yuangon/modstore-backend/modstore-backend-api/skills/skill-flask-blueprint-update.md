# ESkill：Flask 蓝图更新（skill-flask-blueprint-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-flask-blueprint-update` |
| 所属员工 | `modstore-backend-api` |
| 业务域 | MODstore 后端 API 功能开发 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
解析需求（新增/修改路由/中间件）→ 定位目标蓝图文件
→ 生成代码 diff → 语法检查 → 单元测试验证 → 输出摘要
```

**输出 schema**：
```json
{ "status": "ok | error", "changed_files": [], "test_passed": true, "diff_summary": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 语法错误或测试失败 |
| 结果不达标 | `test_passed == false` |

## 3. 动态阶段

**预算**：5000 tokens，6 步。  
**约束**：不得跨越 `forbidden_globs`（支付/前端/密钥）。

## 4. 固化

**验收标准**：测试全绿，API 冒烟通过，前端 `api.ts` 已同步（如接口变更）。
