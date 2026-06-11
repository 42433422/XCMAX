# ESkill：pre-commit hook 维护（skill-pre-commit-maintain）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-pre-commit-maintain` |
| 所属员工 | `test-qa-runner` |
| 业务域 | pre-commit hook 配置维护与代码质量门禁 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
1. 读取 .pre-commit-config.yaml 中的现有 hook 列表
2. 扫描项目实际使用的 linter/formatter：
   - Python：ruff（pyproject.toml 中的配置）
   - TypeScript/Vue：eslint（eslint.config.js）、prettier（.prettierrc）
3. 对比现有 hook 与实际工具，识别缺失 hook
4. 检查现有 hook 版本是否过时
5. 运行 pre-commit run --all-files 验证现有 hook 可执行
→ 输出报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "hooks_present": [],
  "hooks_missing": [],
  "hooks_outdated": [],
  "hooks_broken": [],
  "recommended_additions": []
}
```

**约束**：只修改 `.pre-commit-config.yaml`；不修改 linter/formatter 配置文件本身。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| hook 缺失 | `hooks_missing.length > 0` |
| hook 过时 | `hooks_outdated.length > 0` |
| hook 损坏 | `hooks_broken.length > 0` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。
**LLM 任务**：生成 hook 配置 diff → 验证新 hook 可执行（`pre-commit run <hook-id> --all-files`）→ 更新 `.pre-commit-config.yaml`。

## 4. 固化

**验收标准**：`hooks_missing.length == 0` 且 `hooks_broken.length == 0`，所有项目 linter/formatter 均有对应 pre-commit hook 且可正常执行。
