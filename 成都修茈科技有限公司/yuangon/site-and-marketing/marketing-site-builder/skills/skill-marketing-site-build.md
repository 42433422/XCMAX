# ESkill — skill-marketing-site-build

## 元信息

| 字段 | 值 |
|------|-----|
| skill_id | `skill-marketing-site-build` |
| 所属员工 | `marketing-site-builder` |
| 业务域（domain） | 营销站点 Nunjucks 构建 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段（Static Phase）

**触发条件**：输入包含 `marketing-site/` 下目标路径；构建依赖可用。

**执行逻辑**：

```
校验路径 ∈ scope_globs → 读取模板/partial → 本地 build → 输出校验
```

**输出 schema**：

```json
{
  "status": "ok | error",
  "result": {},
  "metrics": {}
}
```

---

## 2. 动态触发条件（Trigger Rules）

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | build 非零退出 | 即触发 |
| 结果不达标 | 缺失 partial | 可配 |

---

## 3. 动态自适应阶段（Dynamic Phase）

**预算限制**：与 `employee.yaml` triggers 一致。

**允许改动的模块白名单**：仅 `marketing-site/**`。

---

## 4. 静态收缩与固化（Solidify）

验收：构建通过、无运行时模板错误。

---

## 5. 评估指标（Metrics）

| 指标 | 目标值 |
|------|--------|
| 静态路径成功率 | ≥ 95% |
