# Runbook — SEO 站点地图管理员

| 字段 | 值 |
|------|----|
| 员工 ID | `seo-sitemap-curator` |
| 负责区域 | site-and-marketing |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

---

## 日常巡检

```bash
# 校验 sitemap.xml 格式
python -c "import xml.etree.ElementTree as ET; ET.parse('sitemap.xml'); print('sitemap OK')"

# 检查 robots.txt 可访问
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/robots.txt

# 检查 sitemap 可访问
curl -o /dev/null -s -w "%{http_code}" https://xiu-ci.com/sitemap.xml
```

---

## 异常处置

### 异常 1：sitemap.xml 解析错误

**症状**：Python XML 解析抛出异常。  
**排查**：检查 XML 特殊字符（`&`、`<`）是否转义。  
**修复**：修正转义；重新校验。

### 异常 2：百度收录量骤降

**症状**：百度站长平台收录数下降 > 20%。  
**排查**：检查 `robots.txt` 是否误封路径；检查 sitemap 条目是否减少。  
**修复**：恢复 `robots.txt` 或补回 sitemap 条目；触发百度主动推送。

---

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
