# Runbook — 发布部署主管

| 字段 | 值 |
|------|----|
| 员工 ID | `deploy-release-officer` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 发布前检查单（Pre-flight）

```bash
# 1. 确认测试全绿
cd MODstore_deploy && python -m pytest tests/ -q

# 2. 构建前端
cd market && npm run build

# 3. Docker 构建（如适用）
docker build -t xiu-ci-modstore:latest .

# 4. 检查密钥状态（联系 security-secrets-guard）

# 5. xiu-ci.com 官网（根目录 *.html）：若本轮包含 marketing-site/ 或与导航相关页面
cd marketing-site && npm ci && npm run build && cd ..
# 成功后根目录 news.html / news.json 与若干 *.html 应为最新生成结果。
```

## 发布步骤

```bash
# 腾讯云 Pages 静态站发布：以实际流水线为准。
# 营销官网若从仓库根目录整包同步，则上传根目录（含 *.html、assets/、styles.css、main.js 等）；
# 若另使用独立 dist/ 产物目录，则改为 dist/。
tcb hosting deploy . -e <env-id>
# 或：tcb hosting deploy dist/ -e <env-id>

# 重载 Nginx（联系 nginx-config-engineer）
nginx -s reload
```

## 回滚步骤

```bash
# 回滚到上一版本 tag
git checkout <prev-tag>
npm run build && tcb hosting deploy dist/
```

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
