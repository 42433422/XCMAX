# Runbook — Flask 入口维护员

| 字段 | 值 |
|------|----|
| 员工 ID | `flask-entry-keeper` |
| 负责区域 | site-and-marketing |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

---

## 日常巡检

```bash
# 语法检查
python -m py_compile app.py && echo "app.py OK"

# 依赖安全扫描
pip-audit -r requirements.txt

# 冒烟：健康检查路由（如有）
curl -s http://localhost:5000/health || echo "health route missing"
```

---

## 异常处置

### 异常 1：路由 500 错误

**症状**：特定路由返回 500。  
**排查**：查看 Flask 错误日志；`python -m py_compile app.py`。  
**修复**：修正代码；重启 Flask 进程。

### 异常 2：requirements.txt 高危漏洞

**症状**：`pip-audit` 报告 HIGH/CRITICAL CVE。  
**排查**：查看受影响包与版本。  
**修复**：升级到安全版本；在 staging 测试；通知 `security-secrets-guard`。

### 异常 3：文件上传失败

**症状**：`uploads/` 写入权限错误。  
**排查**：`ls -la uploads/`；检查磁盘空间。  
**修复**：`chmod 755 uploads/` 或清理磁盘。

---

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
