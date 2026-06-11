# ESkill：Sitemap 更新（skill-sitemap-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-sitemap-update` |
| 所属员工 | `seo-sitemap-curator` |
| 业务域 | xiu-ci.com SEO 资产维护 |
| 版本 | 1.0.0 |
| 父版本 | — |

---

## 1. 静态阶段

**执行逻辑**：
```
读取现有 sitemap.xml → 对比实际页面列表（由 site-content-editor 触发）
→ 增/删 <url> 条目 → 更新 <lastmod> → XML 格式校验 → 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "added_urls": [],
  "removed_urls": [],
  "xml_valid": true
}
```

---

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | XML 解析失败 |
| 结果不达标 | `xml_valid == false` |

---

## 3. 动态自适应阶段

**预算**：2000 tokens，3 步。  
**LLM 任务**：修复非法 XML 字符或缺失命名空间声明。

---

## 4. 固化

**验收标准**：`xml_valid == true` 且 Google/百度 sitemap 工具验证通过。
