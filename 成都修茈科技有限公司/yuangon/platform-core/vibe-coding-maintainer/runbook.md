# Runbook — Vibe-Coding 维护员

| 字段 | 值 |
|------|----|
| 员工 ID | `vibe-coding-maintainer` |
| 版本 | 2.0.0 |
| 最后更新 | 2026-05-07 |
| 应急联系 | admin |

## 日常巡检

```bash
cd vibe-coding

# 语法检查
python -m py_compile src/vibe_coding/code_factory.py
python -m py_compile src/vibe_coding/workflow_factory.py
python -m py_compile src/vibe_coding/nl/parsing.py
python -m py_compile src/vibe_coding/runtime/validator.py
python -m py_compile src/vibe_coding/workflow_engine.py
python -m py_compile src/vibe_coding/workflow_conditions.py

# 完整测试套件
python -m pytest tests/ -q --tb=short

# 覆盖率检查
python -m pytest tests/ --cov=src/vibe_coding --cov-report=term-missing -q

# Agent 层专项测试
python -m pytest tests/agent/ -q --tb=short
python -m pytest tests/agent/ --cov=src/vibe_coding/agent --cov-report=term-missing -q

# 安全测试
python -m pytest tests/agent/test_security_env.py tests/agent/test_security_paths.py -q

# 工作流引擎测试
python -m pytest tests/test_workflow_*.py tests/agent/test_advanced_workflow.py -q

# 文档一致性检查（手动触发 skill-doc-sync-vibe）
# 扫描 docs/ 与 src/ 的 API 签名对应关系

# 适配器兼容性检查（手动触发 skill-adapter-compat-check）
# 对比 facade.py 与 vibe_adapter.py 的调用点
```

## 异常处置

### 异常 1：NL 解析失败

**排查**：`tests/nl/test_parsing.py` 失败 case；查看 `nl/parsing.py` 正则或 LLM prompt。  
**修复**：更新解析规则或 prompt；补充对应测试 case。

### 异常 2：接口向后不兼容（`vibe_eskill_adapter` 报错）

**排查**：`integrations/vibe_adapter.py` 调用的 `facade.py` 接口签名是否变化。  
**修复**：保持旧接口兼容性（新增参数用 default 值）；通知 `employee-pack-curator`。

### 异常 3：覆盖率下降 > 5%

**排查**：新增代码是否缺少对应测试。  
**修复**：补充测试 case，确保分支覆盖。

### 异常 4：Agent 层测试失败

**排查**：`tests/agent/` 失败 case；查看 traceback 定位具体 agent 子模块。  
**修复**：分析失败原因 → 生成最小修复 diff → 补充测试 case。

### 异常 5：安全规则绕过

**排查**：`runtime/validator.py` 的 ALLOWED_IMPORT_MODULES / FORBIDDEN_BUILTINS 是否遗漏危险模块。  
**修复**：更新拦截规则 → 补充安全测试 case → 通报 `security-secrets-guard`。

### 异常 6：Workflow 引擎性能回归

**排查**：`vibe-coding` 包内看 `workflow_engine.py` / `workflow_factory.py`；**MODstore 平台运行时**看 `MODstore_deploy/modstore_server/workflow_engine.py`（由 `modstore-backend-api` 维护，非本员工职责范围）。  
**修复**：定位瓶颈 → 优化图构建/执行逻辑 → 验证性能基准。

## 工作流引擎职责边界（vibe-coding vs MODstore）

| 引擎 | 路径 | 维护员工 | 可观测性/测试说明 |
|------|------|----------|-------------------|
| Standalone（画布/NL 工厂用） | `vibe-coding/src/vibe_coding/workflow_engine.py` 等 | `vibe-coding-maintainer` | `tests/test_workflow_*.py`、`tests/agent/test_advanced_workflow.py`；见 `skill-workflow-engine-update` |
| 平台运行时（DB 技能组、员工节点） | `MODstore_deploy/modstore_server/workflow_engine.py` | `modstore-backend-api` | 回归测试写在 `MODstore_deploy/tests/**`；结构化日志字段契约由 `log-monitor-incident` 在 runbook 中备案 |

本员工 **不** 修改 `MODstore_deploy/modstore_server/**`。若变更需落 MODstore 引擎，请提交给 `modstore-backend-api`，并由 `test-qa-runner` 补充/维护 `MODstore_deploy/tests/` 用例。

### 异常 7：文档与代码不一致

**排查**：`docs/` 中引用的 API 签名与 `src/` 实际签名做 diff。  
**修复**：更新文档章节 → 验证示例代码可运行。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
