# ESkill：文档同步（skill-doc-sync）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-doc-sync` |
| 所属员工 | `doc-knowledge-curator` |
| 业务域 | 文档资产同步与维护 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取变更信号（代码/架构/员工 yaml 变更）
→ 定位需要更新的 .md 文档
→ 生成文档 diff（保持 Markdown 格式合法）
→ markdownlint 校验 → 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "changed_docs": [],
  "markdown_lint_errors": 0,
  "diff_summary": ""
}
```

**约束**：不修改 `.py`/`.vue`/`.ts` 源码。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `markdown_lint_errors > 0` 或文档内容与 yaml/源码不一致 |

## 3. 动态阶段

**预算**：4000 tokens，4 步。  
**LLM 任务**：分析不一致点 → 生成文档更新 diff。

## 4. 固化

**验收标准**：`markdown_lint_errors == 0`，文档内容与 yaml 责任字段一致。
