# ESkill：API 健康检查（skill-api-health-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-api-health-check` |
| 所属员工 | `modstore-backend-api` |
| 业务域 | MODstore 后端 API 健康维护 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
py_compile 全部蓝图文件 → 启动测试服务器 → curl 每个注册路由
→ 解析响应状态码 → 关闭测试服务器 → 输出报告
```

**输出 schema**：
```json
{ "status": "ok | error", "routes_ok": 0, "routes_fail": [], "syntax_errors": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | `py_compile` SyntaxError；路由 5xx |
| 结果不达标 | `routes_fail` 非空 |

## 3. 动态阶段

**预算**：5000 tokens，6 步。  
**LLM 任务**：分析 traceback → 生成最小修复 diff → Sandbox 重试。

## 4. 固化

**验收标准**：`syntax_errors == []` 且 `routes_fail == []` 且测试全绿。
