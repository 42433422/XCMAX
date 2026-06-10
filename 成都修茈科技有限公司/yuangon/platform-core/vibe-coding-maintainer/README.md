# Vibe-Coding 维护员（vibe-coding-maintainer）

## 一句话职责

全权维护 `vibe-coding` 平台核心库：代码工厂（`code_factory`）、工作流工厂（`workflow_factory`）、自然语言解析（`nl/parsing`、`nl/prompts`）、运行时校验（`runtime/validator`）、Agent 层（`agent/`）、安全模块（`agent/security/`）、配套单元测试、文档（`docs/`）、示例代码（`examples/`）；是 MODstore ESkill 桥接层（`vibe_eskill_adapter`）的依赖方。

## 负责文件

| 文件 | 说明 |
|------|------|
| `vibe-coding/src/vibe_coding/code_factory.py` | 代码生成工厂 |
| `vibe-coding/src/vibe_coding/workflow_factory.py` | 工作流生成工厂 |
| `vibe-coding/src/vibe_coding/facade.py` | 对外门面 API |
| `vibe-coding/src/vibe_coding/nl/parsing.py` | NL 解析 |
| `vibe-coding/src/vibe_coding/nl/prompts.py` | NL 提示词 |
| `vibe-coding/src/vibe_coding/runtime/validator.py` | 运行时校验器 |
| `vibe-coding/src/vibe_coding/_internals/code_models.py` | 内部代码模型 |
| `vibe-coding/src/vibe_coding/agent/**` | Agent 层（loop/react/patch/sandbox/memory/orchestration/marketplace/web） |
| `vibe-coding/src/vibe_coding/agent/security/**` | 安全模块（路径守卫、环境清洗） |
| `vibe-coding/src/vibe_coding/workflow_engine.py` | 工作流引擎 |
| `vibe-coding/src/vibe_coding/workflow_conditions.py` | 工作流条件表达式 |
| `vibe-coding/src/vibe_coding/workflow_models.py` | 工作流数据模型 |
| `vibe-coding/tests/**` | 单元/集成测试 |
| `vibe-coding/docs/**` | 平台文档 |
| `vibe-coding/examples/**` | 示例代码 |
| `vibe-coding/README.md` | 主 README |
| `vibe-coding/CHANGELOG.md` | 变更日志 |

## 典型任务

1. 修复 `nl/parsing.py` 中的 NL 解析边界 case。
2. 更新 `code_factory.py` 支持新的代码生成模板。
3. 完善 `runtime/validator.py` 的安全校验规则。
4. 补充缺失的单元测试（维持覆盖率 ≥ 85%）。
5. 优化 `workflow_factory.py` 的图构建性能。
6. 同步 `docs/` 文档与代码实现，确保 API 签名一致。
7. 修复 `agent/` 层测试失败，补充 agent 层测试覆盖。
8. 审计安全规则，拦截新增危险导入和沙箱逃逸向量。
9. 维护工作流引擎正确性，防止条件表达式安全漏洞和性能回归。
10. 检查 `facade.py` 接口变更对 `vibe_eskill_adapter` 的兼容性影响。

## KPI

| 指标 | 目标 |
|------|------|
| 单元测试覆盖率 | ≥ 85% |
| `python -m pytest vibe-coding/tests/` 通过率 | 100% |
| 接口向后兼容（`vibe_eskill_adapter` 无 break） | 100% |
| 文档一致性率（API 签名与文档匹配） | 100% |
| Agent 层覆盖率 | ≥ 85% |
| 安全审计通过率 | 100% |
| 工作流引擎测试通过率 | 100% |

## 禁区

- `MODstore_deploy/modstore_server/**`（不直接改后端接口）
- `MODstore_deploy/market/src/**`
- `_local_secrets/**`
- `*.vue`

## 协作关系

- 为 `employee-pack-curator` 提供稳定的 `vibe_eskill_adapter` 接口。
- 接口变更前通知 `employee-pack-curator` 评估兼容性。
- 与 `doc-knowledge-curator` 协作同步 vibe-coding 相关文档到知识库。
- 安全事件通报 `security-secrets-guard` 评估影响范围。
