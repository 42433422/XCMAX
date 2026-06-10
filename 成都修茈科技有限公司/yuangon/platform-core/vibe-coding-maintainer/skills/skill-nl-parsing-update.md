# ESkill：NL 解析规则更新（skill-nl-parsing-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-nl-parsing-update` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | 自然语言解析规则维护 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**工作目录**：仓库根下 `vibe-coding/`（以下 pytest 路径均相对于该目录）。

**执行逻辑**：
```
分析失败的 NL 输入 case → 定位 nl/parsing.py 规则缺口
→ 修改解析规则或更新 nl/prompts.py
→ python -m pytest tests/nl/test_parsing.py -q --tb=short
→ 若变更涉及 LLM 提供商路由或 nl/providers/**：额外跑 tests/nl/test_providers.py
→ 输出摘要
```

**输出 schema**：
```json
{ "status": "ok | error", "fixed_cases": 0, "test_passed": true }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `test_passed == false` 或新 edge case 未覆盖 |

## 3. 固化

**验收标准**：`test_passed == true` 且新 edge case 有对应测试。
