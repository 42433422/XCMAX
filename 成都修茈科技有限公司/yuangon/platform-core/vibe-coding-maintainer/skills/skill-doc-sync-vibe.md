# ESkill：文档同步与维护（skill-doc-sync-vibe）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-doc-sync-vibe` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding 平台文档与代码一致性维护 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段

**触发条件**：代码变更涉及 `facade.py`、`code_factory.py`、`workflow_factory.py`、`workflow_engine.py`、`runtime/validator.py`、`nl/parsing.py`、`agent/` 子包中任一模块的公开 API 签名变更时。

**执行逻辑**：

```
扫描 vibe-coding/docs/ 下所有 .md 文件
→ 提取文档中引用的 API 签名（类名、方法名、参数列表）
→ 与 src/vibe_coding/ 对应模块的 __all__ / 公开方法做 diff
→ 标记过时章节（签名不匹配、缺失参数、已删除方法仍被引用）
→ 检查 examples/ 代码片段是否能被当前 API 正确调用
→ 输出一致性报告
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "total_docs": 0,
  "outdated_sections": 0,
  "broken_examples": 0,
  "details": [
    {
      "doc_file": "ARCHITECTURE.md",
      "section": "Module map",
      "issue": "缺少 agent/orchestration/ 模块说明"
    }
  ]
}
```

**工具绑定**：
- `grep` / `ripgrep` — 扫描文档中的代码引用
- `python -c "import ast; ..."` — 提取源码公开 API 签名
- `python -m pytest tests/ -q` — 验证示例代码可运行性

---

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 结果不达标 | `outdated_sections > 0` 或 `broken_examples > 0` | 即触发 |
| 代码变更 | `facade.py` 或 `__init__.py` 的 `__all__` 变更 | 即触发 |

---

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：5000
- 最大步数：6

**允许改动的模块白名单**：
- `vibe-coding/docs/**`
- `vibe-coding/examples/**`
- `vibe-coding/README.md`
- `vibe-coding/README_GITHUB.md`
- `vibe-coding/CHANGELOG.md`

**LLM 任务**：根据一致性报告，更新过时文档章节、修复示例代码片段、补充缺失模块说明。

---

## 4. 固化

**验收标准**：
- `outdated_sections == 0`
- `broken_examples == 0`
- 文档中所有 API 签名与源码一致
- 示例代码可被当前 API 正确调用

---

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 文档一致性率 | 100% |
| 示例可运行率 | 100% |
| 静态路径成功率 | ≥ 95% |
| 平均延迟 | < 15s（静态扫描） |
