# ESkill：Flask 路由健康维护（skill-flask-route-health）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-flask-route-health` |
| 所属员工 | `flask-entry-keeper` |
| 业务域 | Flask app.py 路由与表单逻辑维护 |
| 版本 | 1.0.0 |
| 父版本 | — |

---

## 1. 静态阶段

**执行逻辑**：
```
python -m py_compile app.py → 启动 Flask（测试模式）
→ 对每个路由发起 HTTP 冒烟请求 → 校验响应状态码
→ 关闭测试进程 → 输出报告
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "routes_checked": 0,
  "failed_routes": [],
  "syntax_errors": []
}
```

---

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | `py_compile` 抛出 SyntaxError；路由返回 5xx |
| 结果不达标 | `failed_routes` 非空 |

---

## 3. 动态自适应阶段

**预算**：4000 tokens，5 步。  
**允许改动**：`app.py`、`requirements.txt`。  
**LLM 任务**：分析 traceback → 生成最小修复 diff → Sandbox 验证。

---

## 4. 固化

**验收标准**：
- [x] `syntax_errors == []`
- [x] `failed_routes == []`
- [x] `pip-audit` 无新增高危漏洞
