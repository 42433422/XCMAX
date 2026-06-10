# ESkill：安全加固审计（skill-security-harden）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-security-harden` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding 安全规则与沙箱隔离维护 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段

**触发条件**：`runtime/validator.py`、`agent/security/` 下文件变更，或定时安全巡检触发。

**执行逻辑**：

```
提取 runtime/validator.py 的 ALLOWED_IMPORT_MODULES 与 FORBIDDEN_BUILTINS
→ 与 Python 标准库最新版本的危险模块清单对比（subprocess, socket, http, ftplib, telnetlib, xml.etree 等）
→ 审计 agent/security/paths.py 的路径白名单逻辑
→ 审计 agent/security/env.py 的环境变量清洗逻辑
→ 检查 agent/sandbox/ 各 driver 的隔离边界
→ 运行 tests/agent/test_security_env.py + tests/agent/test_security_paths.py
→ 输出安全审计报告
```

**输出 schema**：
```json
{
  "status": "ok | warning | error",
  "dangerous_imports_not_blocked": [],
  "sandbox_escape_vectors": [],
  "env_leak_risks": [],
  "path_traversal_risks": [],
  "tests_passed": true,
  "audit_score": 0.0
}
```

**工具绑定**：
- `python -m pytest tests/agent/test_security_*.py` — 安全测试
- `python -c "import ast; ..."` — AST 分析危险调用
- `grep` — 搜索潜在危险模式

---

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 结果不达标 | `dangerous_imports_not_blocked` 非空 或 `audit_score < 0.9` | 即触发 |
| 安全事件 | 外部报告新安全漏洞 | 即触发 |
| 代码变更 | `validator.py` 或 `agent/security/` 变更 | 即触发 |

---

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：5000
- 最大步数：6

**允许改动的模块白名单**：
- `vibe-coding/src/vibe_coding/runtime/validator.py`
- `vibe-coding/src/vibe_coding/agent/security/**`
- `vibe-coding/tests/agent/test_security_*.py`

**LLM 任务**：分析未拦截的危险导入 → 更新 ALLOWED_IMPORT_MODULES / FORBIDDEN_BUILTINS → 补充安全测试 case → 验证沙箱隔离边界。

---

## 4. 固化

**验收标准**：
- `dangerous_imports_not_blocked` 为空
- `sandbox_escape_vectors` 为空
- `env_leak_risks` 为空
- `path_traversal_risks` 为空
- `audit_score ≥ 0.95`
- 安全测试全绿

---

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 安全审计通过率 | 100% |
| 已知危险调用拦截率 | 100% |
| 沙箱逃逸向量数 | 0 |
| 静态路径成功率 | ≥ 95% |
