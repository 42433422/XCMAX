# Runbook — marketing-site-builder

## 基本信息

| 字段 | 值 |
|------|-----|
| 员工 ID | `marketing-site-builder` |
| 负责区域 | site-and-marketing |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

---

## 日常巡检

```bash
cd marketing-site
npm ci
npm run build
```

**预期输出**：构建完成且无模板解析错误。

---

## 异常处置

### 构建失败（Nunjucks / 路径）

**排查**：检查 `templates/` 与 `scripts/build.mjs` 中的路径别名。

**回滚**：恢复上一版本模板或 `git checkout` 对应文件。

---

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |

---

## 变更记录

| 日期 | 变更内容 | 操作人 |
|------|----------|--------|
| 2026-05-08 | 初始创建 | admin |
